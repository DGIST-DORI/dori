#!/usr/bin/env python3
"""Build validated, immutable RAG generations from source-backed documents."""
import argparse
from contextlib import contextmanager
from collections import Counter
import fcntl
import json
import math
import os
import re
from pathlib import Path
import sys
import uuid

import numpy as np

# Also support direct invocation by the dashboard and CLI.
if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dori_llm.corpus import atomic_write, available, digest, expired, read_document, sync_directory, utc_now
from dori_llm.index_store import (
    INDEX_FILE, META_FILE, HASH_FILE, MANIFEST_FILE, active_directory, read_manifest,
)
from dori_llm.paths import find_repo_root

EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBED_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
CHUNK_SIZE = 300
CHUNK_OVERLAP = 60
SIGNATURE = {"model": EMBED_MODEL, "revision": EMBED_REVISION,
             "chunker": "sections-bilingual-headings-v3", "overlap_tokens": 20,
             "retrieval": "dense-bm25-rrf-campus-query-v2", "min_score": 0.35,
             "lexical_min_coverage": 0.35, "lexical_relative_cutoff": 0.35,
             "normalize_embeddings": True}


def chunk_text(text, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """Legacy character helper; production builds use token_chunks instead."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Require size > 0 and 0 <= overlap < size")
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if text[start:end].strip():
            chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = end - overlap
    return chunks


def token_chunks(text, model, title="", section_titles_en=None, section_titles_ko=None):
    """Keep explicit source sections apart and repeat their headings in long sections."""
    for section in re.split(r"(?=^## )", text, flags=re.MULTILINE):
        if not section.strip():
            continue
        heading = section.splitlines()[0][3:] if section.startswith("## ") else ""
        prefix = f"{title} / {heading}" if heading else title
        # Preserve both the original and translated retrieval representation.
        # They share identical source text and an evidence ID at indexing time.
        aliases = [(titles or {}).get(heading) for titles in (section_titles_en, section_titles_ko)]
        alternate = " / ".join(filter(None, aliases))
        yield from _token_windows(section, model, prefix, f"{alternate} / {prefix}" if alternate else None)


def _token_windows(text, model, title, alternate_title=None):
    """Use tokenizer offsets so Korean and long lines are never silently truncated."""
    tokenizer = model.tokenizer
    # Titles are useful to disambiguate isolated table cells; bound their budget.
    prefixes = []
    for candidate in ([title, alternate_title] if alternate_title else [title]):
        title_offsets = tokenizer(candidate, add_special_tokens=False, return_offsets_mapping=True, verbose=False)["offset_mapping"]
        if len(title_offsets) > 24:
            candidate = candidate[:title_offsets[23][1]]
        prefix = candidate.strip() + "\n" if candidate.strip() else ""
        if prefix not in prefixes:
            prefixes.append(prefix)
    reserved = max(len(tokenizer(prefix, add_special_tokens=False)["input_ids"]) for prefix in prefixes)
    budget = model.max_seq_length - tokenizer.num_special_tokens_to_add(False) - reserved - 2
    if budget <= 20:
        raise ValueError("Embedding model token budget is too small")
    offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, verbose=False)["offset_mapping"]
    start = 0
    while start < len(offsets):
        end = min(start + budget, len(offsets))
        for prefix in prefixes:
            value = prefix + text[offsets[start][0]:offsets[end - 1][1]].strip()
            if len(tokenizer(value)["input_ids"]) > model.max_seq_length:
                raise ValueError("Chunk exceeds embedding token budget")
            yield value
        if end == len(offsets):
            break
        start = end - 20


def load_documents(docs_dir):
    root = Path(docs_dir).resolve()
    if not root.is_dir():
        raise ValueError(f"Document root does not exist: {root}")
    return [read_document(p, root) for p in sorted(root.rglob("*.txt"))]


def file_hash(path):
    return digest(Path(path).read_bytes())


@contextmanager
def build_lock(output):
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".build.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another index build is already running") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def load_model():
    import torch
    from sentence_transformers import SentenceTransformer
    torch.set_num_threads(min(2, os.cpu_count() or 1))
    cache = os.getenv("DORI_RAG_MODEL_CACHE", str(find_repo_root() / ".state/rag/models"))
    options = dict(revision=EMBED_REVISION, device="cpu", cache_folder=cache, trust_remote_code=False)
    try:
        return SentenceTransformer(EMBED_MODEL, local_files_only=True, **options)
    except OSError:
        return SentenceTransformer(EMBED_MODEL, **options)


def lexical_tokens(text):
    tokens = []
    for word in re.findall(r"[a-z0-9]+|[가-힣]+", text.lower()):
        if re.search(r"[가-힣]", word) and len(word) > 1:
            # Korean particles do not require a heavy morphological analyzer.
            tokens.extend(word[i:i + 2] for i in range(len(word) - 1))
        else:
            tokens.append(word)
    return tokens


def retrieval_query(query):
    """Match common spoken campus terms to the terminology used by the sources."""
    for pattern, replacement in (
        (r"디지스트|대구경북과학기술원", "DGIST"),
        (r"와이파이", "Wi-Fi"),
        (r"도서관", "도서관 학술정보관"),
        (r"분실물", "유실물"),
        (r"저녁", "석식"),
        (r"점심", "중식"),
    ):
        query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)
    query = re.sub(r"어디(?:에|서)?(?:\s*(?:있어|있나요|인가요|야))?", " 위치 ", query)
    query = re.sub(r"몇\s*시", " 시간 ", query)
    # Canonicalize short "where is X?" questions for the embedding model too.
    # Keep full wording for procedural/time questions, where it carries intent.
    if re.search(r"위치\s*[?!.]*$", query):
        query = lexical_query(query).strip(" ?!.")
    return query


def lexical_query(query):
    # Spoken question endings are not evidence-bearing terms. Keeping them in
    # coverage made short location questions lose their exact-name BM25 boost.
    query = re.sub(r"알려\s*주세요|알려줘|어떻게|언제|뭐야|몇|인가요|있나요|있어", " ", query)
    query = re.sub(r"\b(?:what|where|when|how|is|are|the|a|an|of|to|do|i|on|in|at)\b", " ", query,
                   flags=re.IGNORECASE)
    return re.sub(r"([가-힣]{2,})(?:에서|으로|은|는|이|가|을|를|의|에)(?=\s|[?!.]|$)", r"\1", query)


def lexical_scores(metadata, query, with_coverage=False):
    documents = [Counter(lexical_tokens(m["text"])) for m in metadata]
    lengths = [sum(d.values()) for d in documents]
    average = sum(lengths) / max(len(lengths), 1) or 1
    scores = [0.] * len(documents)
    coverage = [0.] * len(documents)
    total_weight = 0.
    for term in set(lexical_tokens(query)):
        frequency = sum(term in doc for doc in documents)
        if not frequency:
            continue
        inverse = math.log(1 + (len(documents) - frequency + .5) / (frequency + .5))
        total_weight += inverse
        for i, doc in enumerate(documents):
            count = doc[term]
            scores[i] += inverse * count * 2.2 / (count + 1.2 * (.25 + .75 * lengths[i] / average))
            if count:
                coverage[i] += inverse
    coverage = [value / (total_weight or 1) for value in coverage]
    return (scores, coverage) if with_coverage else scores


def search_index(index, metadata, model, query, top_k=3, min_score=0.35):
    if not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be positive")
    if not query.strip() or not index.ntotal:
        return []
    query = retrieval_query(query)
    vector = np.asarray(model.encode([query], normalize_embeddings=True,
                                    convert_to_numpy=True), dtype="float32")
    scores, indices = index.search(vector, index.ntotal)
    lexical, coverage = lexical_scores(metadata, lexical_query(query), with_coverage=True)
    lexical_order = sorted(range(len(metadata)), key=lambda i: lexical[i], reverse=True)
    strongest = max(lexical, default=0)
    lexical_rank = {i: rank for rank, i in enumerate(lexical_order, 1)
                    if lexical[i] > 0 and lexical[i] >= .35 * strongest and coverage[i] >= .35}
    candidates = []
    for rank, (score, idx) in enumerate(zip(scores[0], indices[0]), 1):
        if idx >= 0 and float(score) >= min_score:
            # Reciprocal rank fusion preserves semantic matching across languages,
            # while exact names, room IDs and Korean term fragments refine the order.
            fusion = 1 / (60 + rank)
            if int(idx) in lexical_rank:
                fusion += 1 / (60 + lexical_rank[int(idx)])
            candidates.append((fusion, float(score), int(idx)))
    candidates.sort(reverse=True)
    results, seen = [], set()
    for _, score, idx in candidates:
        entry = metadata[int(idx)]
        evidence = ((entry["source_key"], entry["evidence_id"])
                    if entry.get("evidence_id") else entry["text"])
        if not available(entry) or evidence in seen:
            continue
        seen.add(evidence)
        results.append({**entry, "score": float(score)})
        if len(results) >= top_k:
            break
    return results


class IndexBuilder:
    def __init__(self, output_dir, model=None):
        self.output_dir = Path(output_dir)
        self._model = model
        self._index = None
        self._meta = []
        self._hashes = {}
        self.generation = None

    def _get_model(self):
        if self._model is None:
            print(f"Loading pinned CPU embedding model: {EMBED_MODEL}@{EMBED_REVISION}", flush=True)
            self._model = load_model()
        return self._model

    def _embed(self, texts, batch_size):
        return np.asarray(self._get_model().encode(
            texts, batch_size=batch_size, normalize_embeddings=True,
            convert_to_numpy=True, show_progress_bar=False), dtype="float32")

    def build(self, docs_dir, incremental=False, batch_size=8, chunk_batch_size=256,
              evaluation=None, publish=True):
        try:
            if batch_size <= 0 or chunk_batch_size <= 0:
                raise ValueError("Batch sizes must be positive")
            with build_lock(self.output_dir):
                return self._build(Path(docs_dir).resolve(), incremental, batch_size,
                                   chunk_batch_size, evaluation, publish)
        except Exception as exc:
            print(f"[ERROR] Build aborted; active generation unchanged: {exc}", flush=True)
            return False

    def _build(self, root, incremental, batch_size, chunk_batch_size, evaluation, publish):
        import faiss
        documents = load_documents(root)
        if not documents and not incremental:
            raise ValueError("No source documents found; refusing an empty full rebuild")
        excluded = [d["source_key"] for d in documents if expired(d)]
        docs = [d for d in documents if not expired(d)]
        current = active_directory(self.output_dir)
        self._index, self._meta, self._hashes = None, [], {}
        old_meta, old_hashes, old_index = [], {}, None
        if incremental and (current / INDEX_FILE).exists():
            if not (current / MANIFEST_FILE).exists():
                raise ValueError("Legacy index has no build manifest; run one full rebuild without --incremental")
            manifest = read_manifest(current)
            if manifest["signature"] != SIGNATURE or manifest["corpus_root"] != str(root):
                raise ValueError("Model/chunker/document root changed; a full rebuild is required")
            old_index = faiss.read_index(str(current / INDEX_FILE))
            old_meta = json.loads((current / META_FILE).read_text(encoding="utf-8"))
            old_hashes = json.loads((current / HASH_FILE).read_text(encoding="utf-8"))
            if old_index.ntotal != len(old_meta):
                raise ValueError("Index/metadata count mismatch")
        model = self._get_model()
        dimension = model.get_sentence_embedding_dimension()
        self._index = faiss.IndexFlatIP(dimension)
        if old_index is not None and old_index.d != dimension:
            raise ValueError("Embedding dimension changed; a full rebuild is required")
        existing = {d["source_key"]: d["fingerprint"] for d in docs}
        unchanged = {key for key, value in existing.items() if old_hashes.get(key) == value}
        keep = [i for i, meta in enumerate(old_meta) if meta["source_key"] in unchanged]
        if keep:
            vectors = np.stack([old_index.reconstruct(i) for i in keep]).astype("float32")
            self._index.add(vectors)
            self._meta.extend(old_meta[i] for i in keep)
        pending = []
        for doc in docs:
            if doc["source_key"] in unchanged:
                continue
            title = " / ".join(filter(None, (doc.get("title"), doc.get("title_en"))))
            for chunk_id, text in enumerate(token_chunks(doc["text"], model, title,
                                                        doc.get("section_titles_en"), doc.get("section_titles_ko"))):
                pending.append({key: value for key, value in doc.items()
                                if key in ("source", "source_key", "source_url", "source_file", "title",
                                           "fetched_at", "parsed_at", "valid_from", "valid_until", "text_sha256",
                                           "book_title", "edition", "page_number", "page_label",
                                           "source_sha256", "raw_snapshot", "review_export", "extraction_method", "review_status",
                                           "language", "publisher", "source_role", "reference_note", "retrieval_note",
                                           "content_scope", "omitted_sections")}
                               | {"chunk_id": chunk_id, "text": text,
                                  "evidence_id": digest(text.split("\n", 1)[1] if title and "\n" in text else text)})
        for start in range(0, len(pending), chunk_batch_size):
            batch = pending[start:start + chunk_batch_size]
            vectors = self._embed([m["text"] for m in batch], batch_size)
            if vectors.shape != (len(batch), dimension) or not np.isfinite(vectors).all():
                raise ValueError("Invalid embedding shape or nonfinite vector")
            if not np.allclose(np.linalg.norm(vectors, axis=1), 1, atol=.01):
                raise ValueError("Embeddings must be normalized")
            self._index.add(vectors)
            self._meta.extend(batch)
            print(f"[Embed] {self._index.ntotal} vectors", flush=True)
        self._hashes = existing
        if self._index.ntotal != len(self._meta):
            raise ValueError("Index/metadata count mismatch")
        # Re-read the source snapshot before publishing: concurrent ingestion must
        # never mark partially updated content as a successful build.
        snapshot = {d["source_key"]: d["fingerprint"] for d in documents}
        if snapshot != {d["source_key"]: d["fingerprint"] for d in load_documents(root)}:
            raise ValueError("Documents changed during build; retry after ingestion finishes")
        checks = []
        if evaluation:
            cases = json.loads(Path(evaluation).read_text(encoding="utf-8"))
            if not isinstance(cases, list) or not cases:
                raise ValueError("Evaluation must contain a nonempty list of cases")
            for case in cases:
                hits = search_index(self._index, self._meta, model, case["query"],
                                    top_k=case.get("top_k", 3), min_score=case.get("min_score", .35))
                expected = case.get("source_key")
                passed = (not hits if expected is None else any(
                    h["source_key"] == expected and case.get("contains", "") in h["text"] for h in hits))
                forbidden = case.get("must_not_contain", [])
                if not isinstance(forbidden, list) or any(not isinstance(s, str) or not s for s in forbidden):
                    raise ValueError("must_not_contain must be a list of nonempty strings")
                passed = passed and not any(s in h["text"] for h in hits for s in forbidden)
                checks.append({"query": case["query"], "passed": passed,
                               "sources": [h["source_key"] for h in hits]})
            if not all(c["passed"] for c in checks):
                raise ValueError("Retrieval checks failed: " + json.dumps(checks, ensure_ascii=False))
        self.generation = uuid.uuid4().hex
        target = self.output_dir / "generations" / self.generation
        target.mkdir(parents=True)
        faiss.write_index(self._index, str(target / INDEX_FILE))
        with (target / INDEX_FILE).open("rb") as stream:
            os.fsync(stream.fileno())
        for name, payload in ((META_FILE, self._meta), (HASH_FILE, self._hashes)):
            atomic_write(target / name, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        manifest = {"schema_version": 1, "generation": self.generation, "built_at": utc_now(),
                    "signature": SIGNATURE, "corpus_root": str(root), "dimension": dimension,
                    "total_vectors": self._index.ntotal, "total_docs": len(docs),
                    "reused_chunks": len(keep), "embedded_chunks": len(pending),
                    "removed_sources": sorted(set(old_hashes) - set(existing)),
                    "expired_sources": excluded, "evaluation": checks,
                    "checksums": {name: digest((target / name).read_bytes())
                                  for name in (INDEX_FILE, META_FILE, HASH_FILE)}}
        atomic_write(target / MANIFEST_FILE, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        read_manifest(target)
        reloaded = faiss.read_index(str(target / INDEX_FILE))
        if reloaded.ntotal != len(self._meta) or reloaded.d != dimension:
            raise ValueError("Saved index validation failed")
        sync_directory(target.parent)
        if publish:
            atomic_write(self.output_dir / "CURRENT", self.generation + "\n")
        print(f"Done. Generation: {self.generation} ({'active' if publish else 'staged'})")
        print(f"  Total vectors : {self._index.ntotal}\n  Total chunks  : {len(self._meta)}")
        print(f"  Index saved   : {target / INDEX_FILE}")
        return True


class Retriever:
    def __init__(self, index_dir, model=None):
        import faiss
        directory = active_directory(index_dir)
        manifest = read_manifest(directory)
        if manifest["signature"] != SIGNATURE:
            raise ValueError("Embedding configuration differs from index; rebuild required")
        self._index = faiss.read_index(str(directory / INDEX_FILE))
        self._meta = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
        if self._index.ntotal != len(self._meta) or self._index.d != manifest["dimension"]:
            raise ValueError("Index/metadata dimensions or counts differ")
        self._model = model if model is not None else load_model()
        if self._model.get_sentence_embedding_dimension() != self._index.d:
            raise ValueError("Model/index dimension mismatch")
        self.generation = manifest["generation"]

    def search(self, query, top_k=3, min_score=.35):
        return search_index(self._index, self._meta, self._model, query, top_k, min_score)


def activate_generation(output, generation):
    """Activate/roll back an existing validated generation without rewriting it."""
    import faiss
    output = Path(output)
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", generation):
        raise ValueError("Invalid generation ID")
    with build_lock(output):
        target = output / "generations" / generation
        manifest = read_manifest(target)
        if manifest["signature"] != SIGNATURE:
            raise ValueError("Generation uses a different embedding configuration")
        metadata = json.loads((target / META_FILE).read_text(encoding="utf-8"))
        vectors = faiss.read_index(str(target / INDEX_FILE))
        if vectors.ntotal != len(metadata) or vectors.d != manifest["dimension"]:
            raise ValueError("Index/metadata dimensions or counts differ")
        if any(not case["passed"] for case in manifest["evaluation"]):
            raise ValueError("Generation failed retrieval evaluation")
        atomic_write(output / "CURRENT", generation + "\n")
    print(f"Activated generation: {generation}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docs")
    parser.add_argument("--output", default="./data/campus/indexed")
    parser.add_argument("--incremental", action="store_true", help="Sync changes AND deletions within the same corpus root")
    parser.add_argument("--batch-size", type=int, default=int(os.getenv("DORI_EMBED_BATCH_SIZE", "8")))
    parser.add_argument("--chunk-batch-size", type=int, default=int(os.getenv("DORI_CHUNK_BATCH_SIZE", "256")))
    parser.add_argument("--evaluation", help="JSON retrieval cases; failures leave the active index untouched")
    parser.add_argument("--stage-only", action="store_true", help="Validate/save without changing CURRENT")
    parser.add_argument("--activate", metavar="GENERATION", help="Activate or roll back a previously validated generation")
    args = parser.parse_args()
    if args.activate:
        if args.docs or args.incremental or args.stage_only:
            parser.error("--activate cannot be combined with build options")
        activate_generation(args.output, args.activate)
        return 0
    if not args.docs:
        parser.error("--docs is required for building")
    ok = IndexBuilder(args.output).build(args.docs, args.incremental, args.batch_size,
                                        args.chunk_batch_size, args.evaluation, not args.stage_only)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

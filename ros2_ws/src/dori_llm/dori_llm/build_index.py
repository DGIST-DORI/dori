#!/usr/bin/env python3
"""
DORI Campus Guide Robot - Knowledge Base Index Builder

Chunks data/campus/processed/*.txt files, embeds them with a lightweight
multilingual sentence-transformer, and saves a FAISS index + metadata.

Designed for NVIDIA Jetson Orin Nano Super (8GB).
Embedding model: paraphrase-multilingual-MiniLM-L12-v2 (~120 MB, CPU/GPU)

Usage:
    # First time or full rebuild
    python3 build_index.py --docs ./data/campus/processed --output ./data/campus/indexed

    # Tune embedding/build memory usage
    python3 build_index.py --docs ./data/campus/processed --output ./data/campus/indexed --batch-size 8 --chunk-batch-size 256

    # Incremental: only re-embed changed/new files
    python3 build_index.py --docs ./data/campus/processed --output ./data/campus/indexed --incremental

    # After adding new menu files
    python3 build_index.py --docs ./data/campus/processed/cafeteria --output ./data/campus/indexed --incremental

Install:
    pip install sentence-transformers faiss-cpu numpy
    # On Jetson with CUDA: pip install faiss-gpu  (optional, minor speedup for build)
"""

import argparse
import hashlib
import json
import os
import math
import sys
import time
from pathlib import Path

import numpy as np

# Configuration

EMBED_MODEL   = "paraphrase-multilingual-MiniLM-L12-v2"  # 120 MB, KO/EN bilingual
CHUNK_SIZE    = 300    # characters per chunk (shorter = more precise retrieval)
CHUNK_OVERLAP = 60     # overlap to avoid cutting mid-sentence
INDEX_FILE    = "index.faiss"
META_FILE     = "metadata.json"   # chunk text + source info
HASH_FILE     = "file_hashes.json"  # for incremental updates


# Chunking

def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """
    Split text into overlapping character-level chunks.
    Tries to break at newlines first to avoid mid-sentence splits.
    """
    if size <= 0:
        raise ValueError("size must be > 0")
    if overlap >= size:
        overlap = size - 1

    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))

        # Try to break at a newline within the last 60 chars of the window
        if end < len(text):
            break_pos = text.rfind('\n', start + size - 60, end)
            if break_pos > start:
                end = break_pos + 1

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        next_start = max(start + 1, end - overlap)
        start = next_start

    return chunks


def load_documents(docs_dir: Path) -> list[dict]:
    """
    Recursively load all .txt files under docs_dir.
    Returns list of {source, source_key, text} dicts.
    """
    docs_dir = docs_dir.resolve()
    docs = []
    for path in sorted(docs_dir.rglob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                docs.append({
                    "source": str(path),  # user-visible path
                    "source_key": path.relative_to(docs_dir).as_posix(),  # canonical internal key
                    "text": text,
                })
        except Exception as e:
            print(f"  [WARN] Could not read {path}: {e}")
    return docs


def file_hash(path: str) -> str:
    """MD5 hash of file content for change detection."""
    return hashlib.md5(Path(path).read_bytes()).hexdigest()


# Index builder

class IndexBuilder:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.index_path = output_dir / INDEX_FILE
        self.meta_path  = output_dir / META_FILE
        self.hash_path  = output_dir / HASH_FILE

        self._model  = None   # lazy load
        self._index  = None
        self._meta   = []     # list of {source, chunk_id, text}
        self._hashes = {}     # {filepath: md5}

    # Model (lazy)

    def _get_model(self):
        if self._model is None:
            print(f"Loading embedding model: {EMBED_MODEL} ...")
            t0 = time.time()
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(EMBED_MODEL)
            print(f"  Model loaded in {time.time()-t0:.1f}s")
        return self._model

    # Embed

    def _embed(self, texts: list[str], batch_size: int) -> np.ndarray:
        model = self._get_model()
        return model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=len(texts) > 50,
            normalize_embeddings=True,   # cosine similarity via dot product
            convert_to_numpy=True,
        ).astype("float32")

    # Load existing index

    def _load_existing(self):
        import faiss
        try:
            if self.index_path.exists() and self.meta_path.exists():
                self._index  = faiss.read_index(str(self.index_path))
                self._meta   = json.loads(self.meta_path.read_text())
                print(f"  Loaded existing index: {self._index.ntotal} vectors, "
                      f"{len(self._meta)} chunks")
            if self.hash_path.exists():
                self._hashes = json.loads(self.hash_path.read_text())
        except Exception as e:
            raise RuntimeError(f"existing index/meta load failed: {e}") from e

    @staticmethod
    def _meta_source_key(meta: dict, docs_dir: Path) -> str:
        """Resolve canonical source_key from metadata (backward compatible)."""
        if "source_key" in meta and meta["source_key"]:
            return meta["source_key"]

        source = meta.get("source")
        if not source:
            return ""

        src_path = Path(source)
        if not src_path.is_absolute():
            src_path = (Path.cwd() / src_path).resolve()
        else:
            src_path = src_path.resolve()

        try:
            return src_path.relative_to(docs_dir).as_posix()
        except ValueError:
            return str(source)

    def _migrate_hashes(self, docs_dir: Path, docs: list[dict]) -> None:
        """
        Migrate legacy file_hashes keys (absolute/legacy path) to source_key.
        Unknown keys are preserved as-is.
        """
        if not self._hashes:
            return

        alias_to_key = {}
        for doc in docs:
            source = doc["source"]
            source_key = doc["source_key"]
            src_path = Path(source)

            alias_to_key[source_key] = source_key
            alias_to_key[source] = source_key
            alias_to_key[str(src_path)] = source_key
            alias_to_key[str(src_path.resolve())] = source_key
            alias_to_key[str((docs_dir / source_key).resolve())] = source_key

        migrated = {}
        for old_key, h in self._hashes.items():
            new_key = alias_to_key.get(old_key)
            if new_key is None:
                old_path = Path(old_key)
                if old_path.is_absolute():
                    try:
                        new_key = old_path.resolve().relative_to(docs_dir).as_posix()
                    except ValueError:
                        new_key = None
            migrated[new_key or old_key] = h

        self._hashes = migrated

    # Build / rebuild

    def build(
        self,
        docs_dir: Path,
        incremental: bool = False,
        batch_size: int = 16,
        chunk_batch_size: int = 512,
    ) -> bool:
        import faiss

        print(f"\n{'Incremental' if incremental else 'Full'} index build")
        print(f"  Docs dir : {docs_dir}")
        print(f"  Output   : {self.output_dir}")

        docs = load_documents(docs_dir)
        if not docs:
            print("[ERROR] No .txt files found.")
            return False

        docs_dir = docs_dir.resolve()
        if incremental:
            try:
                self._load_existing()
                self._migrate_hashes(docs_dir, docs)
            except Exception as e:
                print(f"[ERROR] {e}")
                return False

        # Determine which files need (re-)indexing
        to_index = []
        for doc in docs:
            h = file_hash(doc["source"])
            if incremental and self._hashes.get(doc["source_key"]) == h:
                continue   # unchanged
            to_index.append((doc, h))

        if not to_index and incremental:
            print("  All files up-to-date. Nothing to do.")
            # Keep summary format identical so downstream parsers can reuse regex.
            if self._index is None:
                print("[ERROR] Existing index is not loaded in incremental mode.")
                return False
            total_vectors = self._index.ntotal
            total_chunks = len(self._meta)
            print(f"\nDone.")
            print(f"  Total vectors : {total_vectors}")
            print(f"  Total chunks  : {total_chunks}")
            print(f"  Index saved   : {self.index_path}")
            return True

        print(f"  Files to index: {len(to_index)} / {len(docs)}")

        # If incremental, remove old chunks for files being re-indexed
        if incremental and self._meta:
            stale_sources = {doc["source_key"] for doc, _ in to_index}
            keep_idx = [i for i, m in enumerate(self._meta)
                        if self._meta_source_key(m, docs_dir) not in stale_sources]
            if keep_idx:
                # Rebuild a fresh index from kept vectors
                dim = self._index.d
                old_vecs = np.zeros((len(keep_idx), dim), dtype="float32")
                for new_i, old_i in enumerate(keep_idx):
                    self._index.reconstruct(old_i, old_vecs[new_i])
                new_index = faiss.IndexFlatIP(dim)
                if keep_idx:
                    new_index.add(old_vecs)
                self._index = new_index
                self._meta  = [self._meta[i] for i in keep_idx]
            else:
                dim = self._embed(["test"], batch_size=1).shape[1]
                self._index = faiss.IndexFlatIP(dim)
                self._meta  = []

        # Chunk new/changed files
        all_chunks  = []
        chunk_metas = []
        for doc, h in to_index:
            chunks = chunk_text(doc["text"])
            for i, chunk in enumerate(chunks):
                all_chunks.append(chunk)
                chunk_metas.append({
                    "source":   doc["source"],
                    "source_key": doc["source_key"],
                    "chunk_id": i,
                    "text":     chunk,
                })
            self._hashes[doc["source_key"]] = h
            print(f"  Chunked {Path(doc['source']).name}: {len(chunks)} chunks")

        if not all_chunks:
            print("[ERROR] No chunks to embed.")
            return False

        # Embed in chunks to reduce peak memory
        print(f"  Embedding {len(all_chunks)} chunks (encoder batch={batch_size}, stream batch={chunk_batch_size}) ...")
        t0 = time.time()
        total_batches = math.ceil(len(all_chunks) / chunk_batch_size)
        for batch_idx, start in enumerate(range(0, len(all_chunks), chunk_batch_size), start=1):
            end = min(start + chunk_batch_size, len(all_chunks))
            chunk_batch = all_chunks[start:end]
            meta_batch = chunk_metas[start:end]

            try:
                vecs = self._embed(chunk_batch, batch_size=batch_size)
            except Exception as e:
                print(f"[ERROR] Embedding failed for batch {batch_idx}/{total_batches}: {e}")
                return False

            if self._index is None:
                dim = vecs.shape[1]
                self._index = faiss.IndexFlatIP(dim)  # inner product = cosine (normalized)

            self._index.add(vecs)
            self._meta.extend(meta_batch)

            print(
                f"    [Embed] Batch {batch_idx}/{total_batches} | "
                f"+{len(vecs)} vectors | cumulative={self._index.ntotal}"
            )

        print(f"  Embedded in {time.time()-t0:.1f}s")

        # Save
        try:
            faiss.write_index(self._index, str(self.index_path))
            self.meta_path.write_text(
                json.dumps(self._meta, ensure_ascii=False, indent=2), encoding="utf-8")
            self.hash_path.write_text(
                json.dumps(self._hashes, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            print(f"[ERROR] Failed to save index/metadata: {e}")
            return False

        print(f"\nDone.")
        print(f"  Total vectors : {self._index.ntotal}")
        print(f"  Total chunks  : {len(self._meta)}")
        print(f"  Index saved   : {self.index_path}")
        return True


# Retriever (used by llm_node.py)

class Retriever:
    """
    Lightweight retriever for use inside llm_node.py.

    Usage:
        from build_index import Retriever
        retriever = Retriever("./data/campus/indexed")
        results = retriever.search("오늘 학생식당 점심", top_k=3)
        for r in results:
            print(r['score'], r['source'], r['text'])
    """

    def __init__(self, index_dir: str):
        import faiss
        from sentence_transformers import SentenceTransformer

        index_dir = Path(index_dir)
        self._index = faiss.read_index(str(index_dir / INDEX_FILE))
        self._meta  = json.loads((index_dir / META_FILE).read_text())
        self._model = SentenceTransformer(EMBED_MODEL)
        print(f"[Retriever] Loaded index: {self._index.ntotal} vectors")

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        """
        Return top_k most relevant chunks for the query.
        Each result: {score, source, chunk_id, text}
        """
        vec = self._model.encode(
            [query], normalize_embeddings=True, convert_to_numpy=True
        ).astype("float32")

        scores, indices = self._index.search(vec, top_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:   # FAISS returns -1 for empty slots
                continue
            meta = self._meta[idx]
            results.append({
                "score":    float(score),
                "source":   meta["source"],
                "chunk_id": meta["chunk_id"],
                "text":     meta["text"],
            })
        return results


# CLI

def main():
    parser = argparse.ArgumentParser(description="DORI RAG Index Builder")
    parser.add_argument("--docs",        required=True, #TODO: default="./data/campus/processed",
                        help="Directory containing .txt document files")
    parser.add_argument("--output",      default="./data/campus/indexed",
                        help="Directory to save FAISS index + metadata")
    parser.add_argument("--incremental", action="store_true",
                        help="Only re-embed changed/new files (faster updates)")
    parser.add_argument("--batch-size", type=int,
                        default=int(os.getenv("DORI_EMBED_BATCH_SIZE", "16")),
                        help="Embedding model batch size (env: DORI_EMBED_BATCH_SIZE, default: 16)")
    parser.add_argument("--chunk-batch-size", type=int,
                        default=int(os.getenv("DORI_CHUNK_BATCH_SIZE", "512")),
                        help="Chunks per streaming embed/add pass (env: DORI_CHUNK_BATCH_SIZE, default: 512)")
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be > 0")
    if args.chunk_batch_size <= 0:
        raise ValueError("--chunk-batch-size must be > 0")

    builder = IndexBuilder(Path(args.output))
    try:
        ok = builder.build(
            Path(args.docs),
            incremental=args.incremental,
            batch_size=args.batch_size,
            chunk_batch_size=args.chunk_batch_size,
        )
    except Exception as e:
        print(f"[ERROR] Unexpected build failure: {e}")
        ok = False

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

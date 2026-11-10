# dori_llm

## External LLM (Gemini)

The node uses the `google-genai` SDK (`client.models.generate_content`) with
the current RAG/location context as `system_instruction` and the last three
conversation turns plus the current question as `contents`. The node owns the
history, so `llm/reset` clears the next request's conversation context too.
All conversation, including greetings and thanks, uses the LLM when available.
Destination guidance stays local and only selects registered destinations.

The standard build installs the Gemini SDK from `requirements-runtime.txt`.
From the repository root, install optional RAG/other-provider dependencies:

```bash
.venv/bin/python -m pip install -c constraints-robot.txt -r ros2_ws/src/dori_llm/requirements.txt
```

Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/apikey).
Set it in the environment of the user/process that starts ROS, then launch from
a built and sourced workspace:

```bash
export GEMINI_API_KEY="your_key_here"
ros2 launch dori_bringup voice.launch.py \
  use_external_llm:=true llm_model:=gemini-3.5-flash-lite
```

`bringup.launch.py` and `robot.launch.py` accept the same `use_external_llm` and `llm_model`
arguments. For only the LLM node:

```bash
ros2 run dori_llm llm_node --ros-args \
  -p use_external_llm:=true -p model_name:=gemini-3.5-flash-lite
```

Credential precedence is `api_key` (ROS parameter) > `GEMINI_API_KEY` >
`GOOGLE_API_KEY`. DORI explicitly preserves this order even though the SDK's
automatic environment lookup prefers `GOOGLE_API_KEY`. Prefer environment
variables so keys are not passed on the command line. To persist the setting for
interactive Bash sessions, add the export to `~/.bashrc`; services need their own
environment configuration. `.env` files are not loaded automatically, and the
Google Cloud TTS JSON credential is not a Gemini API key. Restart the node after
changing credentials or the model.

`use_external_llm` defaults to `true` in the node and all three launch entrypoints.
To deliberately use only local responses, launch with `use_external_llm:=false`.
On successful initialization the node logs
`Gemini client ready: <model>`; this confirms client creation, not API access.
Missing dependencies/credentials disable the external client, log a warning and
retain local KB responses. API failures or empty model output return a localized
service-unavailable message. Gemini requests have a 20-second HTTP timeout and
one attempt; successful generation logs the model and elapsed time.

Vector retrieval is optional: missing FAISS/embedding dependencies are logged
once per index generation and do not prevent Gemini conversation. Restart after
installing dependencies; new index generations reload on the next query. Missing structured campus data
does not supply demo opening hours or coordinates to the model.

### Model selection (reviewed 2026-11-05)

The default is `gemini-3.5-flash-lite`. This is a candidate suited to DORI's short,
latency-sensitive campus RAG answers; validate Korean answer quality and latency
on representative campus questions before deployment.

| Model | Role in DORI | Standard paid text pricing per 1M input / output tokens |
| --- | --- | --- |
| `gemini-3.5-flash-lite` | Default; low latency/cost and Google's recommended 2.5 Flash replacement | $0.30 / $2.50 |
| `gemini-3.8-flash` | Compare when more complex reasoning or answer quality warrants the cost | $0.75 / $3.75 through 2026-12-31; $1.50 / $7.50 from 2027-01-01 |
| `gemini-2.5-flash` | Legacy override for existing users; deprecated | $0.30 / $2.50 before migration |

Output pricing includes thinking tokens. Google limits 2.5-model access to users
who actively used them in the past and says 2.5 Flash requests will automatically
route to 3.5 Flash-Lite from 2026-12-01. It is therefore unsuitable as a new-install
default. Model choice is still configurable via the launch/node arguments above.
The Gemini request avoids deprecated sampling parameters and ends in a user turn,
as required by the newer models.

Sources: [deprecation schedule](https://aistudio.google.com/docs/deprecations#gemini-2.5-flash-models),
[3.5 Flash-Lite](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite),
[3.8 Flash](https://aistudio.google.com/docs/models/gemini-3.8-flash),
[pricing](https://aistudio.google.com/docs/pricing),
[migration notes](https://aistudio.google.com/docs/whats-new-gemini-3.6#api-changes-and-parameter-updates).

## Source-backed RAG pipeline

Install the CPU ingestion/indexing toolchain from the repository root:

```bash
.venv/bin/python -s -m pip install -r requirements-rag.txt
```

This preserves the robot's NumPy 1 ABI. The embedding model is multilingual
MiniLM L12 v2, pinned to commit `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`, with a
384-dimensional vector and a 128-token input limit. It runs on CPU with at most
two PyTorch threads and caches under `.state/rag/models` (`DORI_RAG_MODEL_CACHE`
overrides the cache). The [model card](https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2)
and [SentenceTransformer revision parameter](https://sbert.net/docs/package_reference/sentence_transformer/model.html)
describe these model/loading contracts.

For the normal full refresh, run `scripts/refresh_knowledge.sh`. It stops on
collection failure and chooses a full build for legacy data or an incremental
sync for an existing versioned index. New generations reload on the next query.

The equivalent individual steps are below; stop if either command fails:

```bash
.venv/bin/python -s tools/crawler/crawl_campus.py --output data/campus
.venv/bin/python -s ros2_ws/src/dori_llm/dori_llm/build_index.py \
  --docs data/campus/processed --output data/campus/indexed \
  --evaluation data/campus/evaluation.json
```

The first rebuild of a legacy index must omit `--incremental`. Legacy `.txt`
files without source metadata must be re-ingested; they are not silently treated
as current or trusted. Subsequent builds may add `--incremental`, always using
**the same full document root**. Changed and deleted files, expired sources and
metadata changes are synchronized; unchanged vectors are reused. Passing only a
cafeteria subdirectory is rejected to prevent mixing incompatible source keys.
An incremental sync can intentionally remove all documents; an empty full rebuild
is rejected.

Each processed `.txt` has a matching `.json` source record with its URL or original
filename, collection/parsing time, validity window and SHA-256 content digest.
Missing/malformed records or content mismatches abort the build. Re-run ingestion
after editing a source; editing just the text cannot silently bypass provenance.
The crawler archives HTML/text evidence under `raw/<id>/<html-hash>/`. Optional
LLM summaries are review-only metadata, never authoritative retrieval text.

Sections are split at source headings, then by tokenizer offsets with overlap.
Chunks retain Korean/English document titles and section headings, fit the actual
model token limit and include source provenance. Table row/column spans are
expanded before chunking. No 6,000-character truncation is applied to source text.

Builds use an exclusive writer lock. They validate vector dimensions, normalization,
finite values, metadata counts, checksums and a stable source snapshot. When an
`--evaluation` file is supplied, every retrieval case must pass before publication.
The dashboard build endpoint automatically uses `data/campus/evaluation.json`.
Its 52 bilingual, guidebook and negative checks are smoke coverage, not a comprehensive quality
benchmark; add cases when adding or changing source topics. If official facts
change, review/update the expected evidence instead of weakening the checks.

Spoken campus aliases (for example, 디지스트/DGIST, 와이파이/Wi-Fi and
분실물/유실물) are normalized before retrieval. Korean question endings and
particles, and English question/function words, are removed for lexical matching; the semantic relevance threshold
still applies. This retrieval configuration requires a full rebuild when upgrading
from `dense-bm25-rrf-v1`.

The 2026 guidebook import retains the original PDF, physical page numbers, edition
and extraction review status. Of its 90 pages, 28 pages covering calendars,
contacts and essential campus life have been checked against the original and
included. All 90 OCR pages are archived; unreviewed academic/fee tables and image
pages are excluded explicitly in `data/campus/reports/pdf_import_2026dgist.json`.
The [PDF import workflow](../../../tools/parser/README.md) explains how to review
and add the remaining pages. Guidebook dates describe its edition, not a live
confirmation of opening hours or schedules.

The August 2025 English *Living Guide for International Members* supplements this
with reviewed excerpts from eight physical PDF pages. Original/translated search
headings are embedded as paired representations and deduplicated by evidence ID.
English library, lost-property and building queries thus retrieve the 2026 Korean
facts; the English guide adds international-member topics with an explicit dated
reference label. Old cafeteria hours and unverified fees/policies are excluded.
The full extraction, selected passages and omissions are archived. See
`data/campus/reports/pdf_import_2025dgisteng.json` for coverage. The bilingual
chunker requires a full rebuild when upgrading from `sections-token-offsets-v2`.

Successful builds create immutable `indexed/generations/<id>/` directories and
atomically switch `indexed/CURRENT`. Failed builds leave the previous generation
active. Previous files/generations are retained; nothing is automatically pruned.
The dashboard reads the active generation and reports whether it has a validated
manifest. Concurrent builds return an error rather than overwriting one another.

To review a candidate before activation, add `--stage-only`. To activate that
candidate or roll back to a retained generation:

```bash
.venv/bin/python -s ros2_ws/src/dori_llm/dori_llm/build_index.py \
  --output data/campus/indexed --activate GENERATION_ID
```

The LLM detects a new `CURRENT` generation on the next query, without a service
restart. A failed reload retains its last verified snapshot; expired records are
still excluded on every query. Web sources default to 30 days of freshness
(`crawl_campus.py --fresh-days N`); menus have explicit Korean-time validity
windows. The LLM prompt includes today's Korean date and source collection times.
Similarity scores below 0.35 are excluded. Dense and BM25 ranks are combined
when there is substantial lexical overlap; Korean bigrams preserve matching
across particles, and exact names/room identifiers refine semantic ranking. Missing reference information must be
reported as unverified rather than filled with invented campus facts.

Refresh is **on demand**; no scheduled network job is installed. A fresh download
means the official page was checked, not that the university verified every fact
on it. A failed collection preserves the last source record and reports failure;
it does not renew that record's freshness window.

Run the offline regression suite after sourcing `scripts/env.sh`:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q \
  tests/control_and_nav/test_rag_pipeline.py tests/control_and_nav/test_llm_gemini.py
```

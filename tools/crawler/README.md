# Campus source collection

Run from the repository root after installing `requirements-rag.txt`:

```bash
.venv/bin/python -s tools/crawler/crawl_campus.py --output data/campus
```

Collection defaults to source text only. It preserves full extracted text and
content-addressed HTML/text evidence, and creates a matching source `.json` next
to each processed `.txt`. Every record includes the requested/final URL,
collection time, validity deadline (30 days by default), and content checksum.
The configured five official DGIST pages are fetched once per run.

Use `--refine` to add optional Gemini summaries for review. The model is selected
by `DORI_CRAWLER_MODEL` (default `gemini-3.5-flash-lite`); credentials prefer
`GEMINI_API_KEY`, then `GOOGLE_API_KEY`. Generated prose is never substituted for
source text in the retrieval corpus. `--no-llm` explicitly selects the default.
Successful re-collection replaces a single canonical document; old `_raw.txt`
fallback duplicates are removed after that document is written.

Additional URL lists accept comments and optional category/ID columns:

```text
https://www.dgist.ac.kr/kor/ # 한국어
https://library.dgist.ac.kr/libGuidance/facility.do library library_facilities
```

```bash
.venv/bin/python -s tools/crawler/crawl_campus.py \
  --urls tools/crawler/url_list.txt --output data/campus
```

Duplicate URLs are collected once. Auto IDs include a URL hash; categories must
use lowercase letters, digits, underscores or hyphens. `--urls-only` excludes the
built-in list. Tune `--delay`, `--timeout`, `--retries` and `--fresh-days` as needed.
404/non-HTML/empty/error pages are rejected. HTTP 429/5xx and connection failures
have bounded retries; permanent 4xx responses do not get repeated requests.

A failed source preserves its previous document and freshness deadline. The
command exits nonzero on collection failure, so stop before indexing and inspect
`reports/crawl_report_*.json`. Optional summary failures are recorded separately;
the successfully collected original source remains usable. Collection does not
build an index or install a recurring job. See the
[RAG build and rollback workflow](../../ros2_ws/src/dori_llm/README.md#source-backed-rag-pipeline).

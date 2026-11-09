# Cafeteria source import

Run from the repository root after installing `requirements-rag.txt`:

```bash
.venv/bin/python -s tools/parser/parse_cafeteria_menu.py \
  --input ./menus/학생식당_2026_주간메뉴표.xlsx \
  --output ./data/campus/processed/cafeteria
```

`--input` also accepts a directory of XLSX/PDF files. Date cells with a full year
or an Excel serial date are accepted directly. Month/day-only dates require a
year in the original filename or an explicit `--year 2026`; the parser does not
silently assign the current year to old documents.

Imports require five distinct, ordered Monday–Friday dates in one week and at
least one meal. XLSX extraction handles namespaced XML, shared/inline strings,
and numeric date cells. Cafeteria-specific sheet/row layouts remain fixed; an
unrecognized or changed template requires review rather than guessed data.

Each output `.txt` has a source `.json` containing the original filename and
SHA-256, parsed time, text checksum and Korean-time validity window. Future menus
are excluded until their start date; expired menus are excluded after Friday.
Keep the original uploaded file for later verification; the parser records its
hash but does not archive the binary file. Parse failures return a nonzero exit
code and do not publish an empty/unknown-date menu.

For incremental indexing, always use the full `data/campus/processed` root, not
only the cafeteria subfolder. See the
[RAG workflow](../../ros2_ws/src/dori_llm/README.md#source-backed-rag-pipeline).

## Guidebook PDFs

`import_pdf_pages.py` imports a page-addressed extraction into the same corpus.
Extract text/tables first (OCR is necessary for image or outlined-text PDFs),
compare important facts with the original pages, and prepare a JSON export:

```json
{
  "schema_version": 1,
  "source_sha256": "SHA-256 of the original PDF bytes",
  "book_title": "Campus life guidebook",
  "edition": "2026",
  "page_count": 2,
  "pages": [{
    "page_number": 2,
    "page_label": "1",
    "title": "Library",
    "text": "## Borrowing\nOriginal source content, including table headers and exceptions.",
    "extraction_method": "OCR",
    "review_status": "machine_extracted"
  }],
  "excluded_pages": [{"page_number": 1, "reason": "Cover"}]
}
```

`page_number` is the **one-based physical PDF page**; `page_label` is the printed
page label, when verified. Every page must appear exactly once in `pages` or
`excluded_pages`. Missing/empty pages and mismatched PDF hashes abort before
changing an existing import. Use `visually_verified` or
`corrected_against_original` only for pages actually compared with the source.
Preserve headings and table relationships; do not replace source facts with
generated summaries. Maps require visual review and do not supply robot poses.

```bash
.venv/bin/python -s tools/parser/import_pdf_pages.py \
  --input /path/to/guidebook.pdf --pages /path/to/reviewed-pages.json \
  --document-id campus_2026 --output data/campus
.venv/bin/python -s ros2_ws/src/dori_llm/dori_llm/build_index.py \
  --docs data/campus/processed --output data/campus/indexed --incremental \
  --evaluation data/campus/evaluation.json
```

The importer archives the original PDF and a content-addressed page export under
`raw/guidebook/<document-id>/<pdf-sha256>/`, writes one source-backed document per
included page, and reports exclusions in `reports/pdf_import_<document-id>.json`.
Reimporting the same ID replaces its pages and removes pages explicitly excluded
in the new export. Import alone does not change the active index. Index the full
corpus only after reviewing retrieval checks; `--stage-only` is also available.
Omit `--incremental` on the first build or when the model/retrieval signature has
changed; old generations remain archived but require a compatible configuration
to reactivate.

For `2026dgist`, the import report names the exact archived `pages-<hash>.json`
review export. The adjacent `ocr-pages.json` retains all 90 raw OCR pages as a
draft; it is not the reviewed corpus. Continue from the report's review export
when checking additional pages, remove their exclusion records, and reimport.

PDF results retain their edition and page through retrieval into LLM context.
The parse date is not a publication date or proof that opening hours are current.
Guidebook facts have no inferred expiry: inspect newer editions and official
notices for changes, and state the edition when citing dated information.

### Bilingual labels and dated supplementary passages

Optional document fields `language`, `publisher`, `source_role` (`primary` or
`dated_supplement`) and `reference_note` survive indexing into the answer context.
Use `dated_supplement` for an older reference whose present availability/policies
have not been reverified. Source language never overrides a newer applicable
source for the same fact.

For an excerpt, set the page's `content_scope` to `selected_sections` and list
what was left out and why in `omitted_sections`. Physical PDF page numbers and
printed labels can differ: the English guide's physical page 42 contains printed
pages 82–83. A page record can cite only the printed page actually excerpted.

`section_titles_en` and `section_titles_ko` map exact original `##` headings to
translated retrieval labels. These are search labels, not translated factual
sources. For example:

```json
{"section_titles_en": {"학술정보관 이용안내": "Central Library location and opening hours"}}
```

Both original and alternate headings are embedded with identical source bodies,
bounded by the model token limit. Shared evidence IDs prevent the two forms from
taking up two search result slots. Page, edition, publisher and original text
remain attached. Label keys that do not match source headings are rejected.
Changes to this chunker require a full rebuild (omit `--incremental`).

The August 2025 English guide import uses reviewed excerpts from eight physical
pages. It adds arrival preparation, Korean language programs, Buddy Program,
DISA, laundry and housing information as dated references. Conflicting cafeteria
hours, fee tables, immigration procedures and unchecked schedules are excluded
from active retrieval; the original PDF and complete extraction remain archived.
The corresponding import report records both excluded pages and omissions within
included pages. Selected 2026 Korean sections carry English retrieval labels for
library, lost-property and building questions. Retrieval checks can specify
`must_not_contain` to reject obsolete facts even if the expected source also appears.

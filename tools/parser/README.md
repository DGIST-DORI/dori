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

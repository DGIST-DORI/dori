#!/usr/bin/env python3
"""Import a page-addressed PDF extraction after reviewing its content and coverage.

PDF/OCR extraction is a separate step. This importer binds the exported text to
the original binary, archives both, and uses the existing source-backed corpus.
It never guesses missing pages, publication dates, facts or navigation coordinates.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ros2_ws/src/dori_llm"))
from dori_llm.corpus import atomic_write, digest, utc_now, write_document

SOURCE_FIELDS = ("language", "publisher", "source_role", "reference_note")
PAGE_FIELDS = ("title_en", "section_titles_en", "section_titles_ko", "retrieval_note", "content_scope", "omitted_sections")


def validate_optional_fields(record):
    for field in (*SOURCE_FIELDS, "title_en", "retrieval_note", "content_scope"):
        if field in record and (not isinstance(record[field], str) or not record[field].strip()):
            raise ValueError(f"Invalid {field}")
    if record.get("source_role", "primary") not in ("primary", "dated_supplement"):
        raise ValueError("source_role must be primary or dated_supplement")
    if record.get("content_scope", "full_page") not in ("full_page", "selected_sections"):
        raise ValueError("Invalid content_scope")
    omitted = record.get("omitted_sections", [])
    if not isinstance(omitted, list) or any(not isinstance(x, str) or not x.strip() for x in omitted):
        raise ValueError("omitted_sections must list omitted content and reasons")
    if record.get("content_scope") == "selected_sections" and not omitted:
        raise ValueError("Selected sections require an explicit omission record")


def validate_export(data, source_bytes):
    if not source_bytes.startswith(b"%PDF-"):
        raise ValueError("Input is not a PDF")
    if data.get("schema_version") != 1 or data.get("source_sha256") != digest(source_bytes):
        raise ValueError("PDF/export checksum or schema mismatch; review the matching PDF")
    for field in ("book_title", "edition"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise ValueError(f"Missing {field}")
    count = data.get("page_count")
    if type(count) is not int or count < 1:
        raise ValueError("page_count must be positive")
    pages, excluded = data.get("pages"), data.get("excluded_pages", [])
    if not isinstance(pages, list) or not pages or not isinstance(excluded, list):
        raise ValueError("Require nonempty pages and an excluded_pages list")
    validate_optional_fields(data)
    seen = set()
    for record in pages + excluded:
        number = record.get("page_number")
        if type(number) is not int or not 1 <= number <= count or number in seen:
            raise ValueError("Invalid or duplicate PDF page_number")
        seen.add(number)
    if seen != set(range(1, count + 1)):
        raise ValueError("Every PDF page must be imported or explicitly excluded with a reason")
    for page in pages:
        validate_optional_fields(page)
        for field in ("title", "text", "extraction_method"):
            if not isinstance(page.get(field), str) or not page[field].strip():
                raise ValueError(f"Page {page['page_number']} has no {field}")
        if page.get("review_status") not in ("machine_extracted", "visually_verified", "corrected_against_original"):
            raise ValueError("Specify the actual extraction review status for each page")
        if "page_label" in page and not isinstance(page["page_label"], str):
            raise ValueError("page_label must be a string")
        headings = set(re.findall(r"^## (.+)$", page["text"], re.MULTILINE))
        for field in ("section_titles_en", "section_titles_ko"):
            aliases = page.get(field, {})
            if (not isinstance(aliases, dict) or any(
                    k not in headings or not isinstance(v, str) or not v.strip()
                    for k, v in aliases.items())):
                raise ValueError("Retrieval headings must refer to existing source sections")
    for page in excluded:
        if not isinstance(page.get("reason"), str) or not page["reason"].strip():
            raise ValueError("Excluded pages require a reason")


def import_pages(source, export, output, document_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", document_id):
        raise ValueError("document_id must use lowercase letters, digits, underscores or hyphens")
    source, export, output = Path(source), Path(export), Path(output)
    binary = source.read_bytes()
    data = json.loads(export.read_text(encoding="utf-8"))
    validate_export(data, binary)
    target = output / "processed" / "guidebook" / document_id
    previous = list(target.glob("page_*.txt"))
    # Validate ownership before replacing/removing anything in an existing import.
    for old in previous:
        record = json.loads(old.with_suffix(".json").read_text(encoding="utf-8"))
        if record.get("kind") != "pdf" or record.get("doc_id") != document_id:
            raise ValueError(f"Refusing to replace an unrelated document: {old}")
    snapshot = output / "raw" / "guidebook" / document_id / data["source_sha256"]
    snapshot.mkdir(parents=True, exist_ok=True)
    archive = snapshot / "source.pdf"
    if archive.exists():
        if digest(archive.read_bytes()) != data["source_sha256"]:
            raise ValueError("Archived PDF checksum mismatch")
    else:
        temporary = snapshot / ".pending-source.pdf"
        temporary.write_bytes(binary)
        temporary.replace(archive)
    exported_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    exported_name = "pages-" + digest(exported_text) + ".json"
    atomic_write(snapshot / exported_name, exported_text)
    parsed_at = utc_now()
    kept = set()
    for page in sorted(data["pages"], key=lambda value: value["page_number"]):
        path = target / f"page_{page['page_number']:03d}.txt"
        record = {
            "kind": "pdf", "doc_id": document_id, "category": "guidebook",
            "source_file": source.name, "source_sha256": data["source_sha256"],
            "book_title": data["book_title"], "edition": data["edition"],
            "page_number": page["page_number"], "page_label": page.get("page_label", ""),
            "title": page["title"], "parsed_at": parsed_at,
            "extraction_method": page["extraction_method"], "review_status": page["review_status"],
            "raw_snapshot": str(snapshot.relative_to(output)), "review_export": exported_name,
        }
        record.update({field: page.get(field, data.get(field)) for field in SOURCE_FIELDS
                       if field in page or field in data})
        record.update({field: page[field] for field in PAGE_FIELDS if field in page})
        write_document(path, page["text"], record)
        kept.add(path)
    for old in previous:
        if old not in kept:
            old.unlink()
            old.with_suffix(".json").unlink()
    report = {
        "source_file": source.name, "source_sha256": data["source_sha256"],
        "book_title": data["book_title"], "edition": data["edition"], "parsed_at": parsed_at,
        "page_count": data["page_count"], "imported_pages": sorted(p["page_number"] for p in data["pages"]),
        "excluded_pages": data.get("excluded_pages", []), "raw_snapshot": str(snapshot.relative_to(output)),
        "review_export": exported_name, "index_published": False,
        "selected_sections": [{"page_number": p["page_number"], "omitted_sections": p["omitted_sections"]}
                              for p in data["pages"] if p.get("content_scope") == "selected_sections"],
    }
    report_path = output / "reports" / f"pdf_import_{document_id}.json"
    atomic_write(report_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Imported {len(kept)}/{data['page_count']} pages into {target}")
    print(f"Coverage report: {report_path}; rebuild the full corpus to publish")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Original PDF; archived without modification")
    parser.add_argument("--pages", required=True, help="Reviewed JSON page export bound to the original SHA-256")
    parser.add_argument("--document-id", required=True)
    parser.add_argument("--output", default="data/campus")
    args = parser.parse_args(argv)
    try:
        import_pages(args.input, args.pages, args.output, args.document_id)
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"[ERROR] PDF import failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

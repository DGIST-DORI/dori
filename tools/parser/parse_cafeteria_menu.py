#!/usr/bin/env python3
"""
DORI Campus Guide Robot - Cafeteria Menu Parser
Parses weekly menu files (xlsx / pdf) and outputs structured JSON + txt documents.

Supported cafeterias:
  - 학생식당 (Student Cafeteria)  : xlsx, 2 sheets (KO / EN)
  - 교직원식당 (Staff Cafeteria)  : xlsx, KO only
  - 연구동식당 (R&D Cafeteria)    : pdf, 2 pages (KO / EN)

Usage:
  python3 parse_cafeteria_menu.py --input <file_or_dir> --output <output_dir>
  python3 parse_cafeteria_menu.py --input ./menus/ --output ./data/campus/processed/cafeteria/
"""

import argparse
import html
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

# Shared helpers

DAYS_KO = ["월", "화", "수", "목", "금"]
DAYS_EN = ["Mon", "Tue", "Wed", "Thu", "Fri"]

COL_TO_DAY_IDX = {"D": 0, "E": 1, "F": 2, "G": 3, "H": 4}  # student cafeteria
COL_TO_DAY_IDX_STAFF = {"B": 0, "C": 1, "D": 2, "E": 3, "F": 4}  # staff cafeteria


def col_letter(ref: str) -> str:
    """Extract column letter(s) from cell reference like 'D8' -> 'D'."""
    return re.match(r"([A-Z]+)", ref).group(1)


def clean(text: str) -> str:
    """Unescape HTML entities and strip whitespace."""
    return html.unescape(text).strip()


def parse_date_from_value(val: str) -> str:
    """Try to parse various date string formats into YYYY-MM-DD."""
    val = val.strip()
    # 2026.3.9
    m = re.match(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", val)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # 03월 09일 or 3월9일
    m = re.search(r"(\d{1,2})월\s*(\d{1,2})일?", val)
    if m:
        year = datetime.now().year
        return f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    # 3/9
    m = re.match(r"(\d{1,2})/(\d{1,2})", val)
    if m:
        year = datetime.now().year
        return f"{year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return val


# XLSX parser (shared string + sheet XML approach)


def _load_shared_strings(z: zipfile.ZipFile) -> list[str]:
    with z.open("xl/sharedStrings.xml") as f:
        ss_xml = f.read().decode("utf-8")
    si_blocks = re.findall(r"<x:si>(.*?)</x:si>", ss_xml, re.DOTALL)
    result = []
    for block in si_blocks:
        texts = re.findall(r"<x:t[^>]*>([^<]*)</x:t>", block)
        result.append(clean("".join(texts)))
    return result


def _parse_sheet_rows(
    z: zipfile.ZipFile, sheet_path: str, shared: list[str]
) -> dict[str, dict[str, str]]:
    """Return {row_num: {col_letter: cell_value}} for string-typed cells."""
    with z.open(sheet_path) as f:
        sheet_xml = f.read().decode("utf-8")
    row_map: dict[str, dict[str, str]] = {}
    rows = re.findall(r'<x:row r="(\d+)"[^>]*>(.*?)</x:row>', sheet_xml, re.DOTALL)
    for row_num, row_content in rows:
        cells = re.findall(
            r'<x:c r="([A-Z]+\d+)"[^>]*t="s"[^>]*>.*?<x:v>(\d+)</x:v>',
            row_content,
            re.DOTALL,
        )
        if cells:
            row_map[row_num] = {col_letter(ref): shared[int(idx)] for ref, idx in cells}
    return row_map


def parse_student_cafeteria_xlsx(filepath: str) -> dict:
    """
    Parse 학생식당 xlsx.
    Sheet1 = Korean, Sheet2 = English.
    Layout:
      Row 6 : header (구분 / 월~금)
      Row 7 : dates
      Row 8  (C8) : 중식 일품  label + D-H = menus
      Row 9-11    : 중식 일품  continuation
      Row 12 (C12): 중식 정식  label + D-H = menus
      Row 13-17   : 중식 정식  continuation
      Row 18 (C18): 석식 정식  label + D-H = menus
      Row 19-23   : 석식 정식  continuation
    """
    result = {
        "cafeteria_id": "student",
        "cafeteria_ko": "학생식당",
        "cafeteria_en": "Student Cafeteria",
        "week_dates": [],
        "meals": {
            day: {"lunch_ilpum": [], "lunch_jeongsik": [], "dinner": []}
            for day in DAYS_KO
        },
        "meals_en": {
            day: {"lunch_ilpum": [], "lunch_jeongsik": [], "dinner": []}
            for day in DAYS_EN
        },
        "hours": {"lunch": "11:30-13:00", "dinner": "17:30-18:40"},
        "note": "",
        "parsed_at": datetime.now().isoformat(),
    }

    col_map = COL_TO_DAY_IDX  # D->0 … H->4

    def fill_meals(rows: dict, lang: str):
        days = DAYS_KO if lang == "ko" else DAYS_EN
        meals_key = "meals" if lang == "ko" else "meals_en"

        # Dates from row 7 (only populate once, from the KO sheet)
        if lang == "ko" and "7" in rows:
            for col, val in rows["7"].items():
                if col in col_map:
                    result["week_dates"].append(parse_date_from_value(val))

        # Lunch ilpum rows 8-11, jeongsik rows 12-17, dinner rows 18-23
        sections = [
            (range(8, 12), "lunch_ilpum"),
            (range(12, 18), "lunch_jeongsik"),
            (range(18, 24), "dinner"),
        ]
        for row_range, meal_key in sections:
            for r in row_range:
                row = rows.get(str(r), {})
                for col, val in row.items():
                    if (
                        col in col_map
                        and val
                        and val not in ("백미밥", "white rice", "    ")
                    ):
                        day = days[col_map[col]]
                        result[meals_key][day][meal_key].append(val)

    with zipfile.ZipFile(filepath) as z:
        shared = _load_shared_strings(z)
        sheets = [
            n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml", n)
        ]
        sheets.sort()

        rows_ko = _parse_sheet_rows(z, sheets[0], shared)
        fill_meals(rows_ko, "ko")

        if len(sheets) >= 2:
            rows_en = _parse_sheet_rows(z, sheets[1], shared)
            fill_meals(rows_en, "en")

    return result


def parse_staff_cafeteria_xlsx(filepath: str) -> dict:
    """
    Parse 교직원식당 xlsx.
    Sheet1 = Korean (lunch rows 7-13 only — no dinner data)
    Sheet2 = Mixed: EN lunch (rows 7-13) + KO dinner (rows 15-20)
    Layout:
      Row 5 : header (구분 / MON~FRI)
      Row 6 : dates (Korean format both sheets)
      Row 7-13 : lunch
      Row 15-20: dinner (sheet2, Korean text)
    """
    result = {
        "cafeteria_id": "staff",
        "cafeteria_ko": "교직원식당",
        "cafeteria_en": "Staff Cafeteria",
        "week_dates": [],
        "meals": {day: {"lunch": [], "dinner": []} for day in DAYS_KO},
        "meals_en": {day: {"lunch": [], "dinner": []} for day in DAYS_EN},
        "hours": {"lunch": "11:30-13:00", "dinner": "17:30-19:00"},
        "note": "",
        "parsed_at": datetime.now().isoformat(),
    }

    col_map = COL_TO_DAY_IDX_STAFF  # B->0 … F->4
    SKIP_KO = {"흑미밥/백미밥", "잡곡밥/백미밥", "백미밥", "    ", "석식"}
    SKIP_EN = {"black/white rice", "white rice", "    ", "LUNCH"}

    with zipfile.ZipFile(filepath) as z:
        shared = _load_shared_strings(z)
        rows_ko = _parse_sheet_rows(z, "xl/worksheets/sheet1.xml", shared)
        rows_en = _parse_sheet_rows(z, "xl/worksheets/sheet2.xml", shared)

    # Dates from row 6 (sheet1)
    if "6" in rows_ko:
        for col, val in rows_ko["6"].items():
            if col in col_map:
                result["week_dates"].append(parse_date_from_value(val))

    # KO lunch: sheet1 rows 7-13
    for r in range(7, 14):
        row = rows_ko.get(str(r), {})
        for col, val in row.items():
            if col in col_map and val and val not in SKIP_KO:
                result["meals"][DAYS_KO[col_map[col]]]["lunch"].append(val)

    # EN lunch: sheet2 rows 7-13
    for r in range(7, 14):
        row = rows_en.get(str(r), {})
        for col, val in row.items():
            if col in col_map and val and val not in SKIP_EN:
                result["meals_en"][DAYS_EN[col_map[col]]]["lunch"].append(val)

    # KO dinner: sheet2 rows 15-20 (Korean text in the English sheet)
    for r in range(15, 21):
        row = rows_en.get(str(r), {})
        for col, val in row.items():
            if col in col_map and val and val not in SKIP_KO:
                day_ko = DAYS_KO[col_map[col]]
                day_en = DAYS_EN[col_map[col]]
                result["meals"][day_ko]["dinner"].append(val)
                result["meals_en"][day_en]["dinner"].append(val)  # KO text as-is

    # Note
    if "22" in rows_en:
        for val in rows_en["22"].values():
            if val:
                result["note"] = val

    return result


# PDF parser (연구동식당)


def parse_rnd_cafeteria_pdf(filepath: str) -> dict:
    """
    Parse 연구동식당 PDF using pdfplumber.
    Page 1 = Korean, Page 2 = English.
    Table layout (each page):
      Row 2: header  [구분 | 월 | 화 | 수 | 목 | 금]
      Row 3: dates
      Row 4: lunch   (cell contains newline-joined items)
      Row 5: lunch PLUS
      Row 6: takeout
      Row 7: dinner
      Row 8: dinner PLUS
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "pdfplumber is required for PDF parsing. " "Install: pip install pdfplumber"
        )

    result = {
        "cafeteria_id": "rnd",
        "cafeteria_ko": "연구동식당",
        "cafeteria_en": "R&D Restaurant",
        "week_dates": [],
        "meals": {
            day: {
                "lunch": [],
                "lunch_plus": [],
                "takeout": [],
                "dinner": [],
                "dinner_plus": [],
            }
            for day in DAYS_KO
        },
        "meals_en": {
            day: {
                "lunch": [],
                "lunch_plus": [],
                "takeout": [],
                "dinner": [],
                "dinner_plus": [],
            }
            for day in DAYS_EN
        },
        "hours": {"lunch": "11:30-13:00", "dinner": "18:00-19:00"},
        "note": "",
        "parsed_at": datetime.now().isoformat(),
    }

    # Map first-column keyword -> meal key
    SECTION_MAP = {
        "정성": "lunch",
        "점심": "lunch",
        "Lunch": "lunch",
        "PLUS": "lunch_plus",
        "Take": "takeout",
        "하루": "dinner",
        "저녁": "dinner",
        "Dinner": "dinner",
    }
    # Rows to skip (metadata / allergy)
    SKIP_KEYWORDS = [
        "알레르기",
        "원산지",
        "쌀(",
        "제공되는",
        "Allergy",
        "Origin",
        "above",
        "Country",
    ]

    def cell_items(text: str) -> list[str]:
        """Split a multi-line cell into individual menu items."""
        if not text:
            return []
        items = [i.strip() for i in text.splitlines() if i.strip()]
        return [i for i in items if i not in ("-", "OR", "")]

    def extract_page(page, days: list[str], meals_key: str, populate_dates: bool):
        table = page.extract_table()
        if not table:
            return
        for row in table:
            if not row or all(c is None or str(c).strip() == "" for c in row):
                continue
            cells = [str(c).strip() if c else "" for c in row]
            first = cells[0]

            # Skip metadata rows
            if any(kw in first for kw in SKIP_KEYWORDS):
                continue

            # Date row
            if populate_dates and re.search(r"\d{1,2}월", first) is None:
                date_found = False
                for c in cells[1:6]:
                    if re.search(r"\d{1,2}월", c):
                        result["week_dates"].append(parse_date_from_value(c))
                        date_found = True
                if date_found:
                    continue

            # Section row
            section = None
            for kw, key in SECTION_MAP.items():
                if kw in first:
                    section = key
                    break
            if section is None:
                continue

            # Fill menu items per day
            for col_idx, day in enumerate(days):
                cell_text = cells[col_idx + 1] if col_idx + 1 < len(cells) else ""
                items = cell_items(cell_text)
                result[meals_key][day][section].extend(items)

    with pdfplumber.open(filepath) as pdf:
        if len(pdf.pages) >= 1:
            extract_page(pdf.pages[0], DAYS_KO, "meals", populate_dates=True)
        if len(pdf.pages) >= 2:
            extract_page(pdf.pages[1], DAYS_EN, "meals_en", populate_dates=False)

    return result


# Output serializers


def to_json(data: dict, out_dir: Path):
    """Save structured menu as JSON."""
    week_tag = data["week_dates"][0] if data["week_dates"] else "unknown"
    fname = f"{data['cafeteria_id']}_menu_{week_tag}.json"
    out_path = out_dir / fname
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [JSON] saved -> {out_path}")
    return out_path


def to_txt(data: dict, out_dir: Path):
    """
    Save human-readable bilingual menu as txt for RAG document store.
    One file per cafeteria per week.
    """
    week_tag = data["week_dates"][0] if data["week_dates"] else "unknown"
    fname = f"{data['cafeteria_id']}_menu_{week_tag}.txt"
    out_path = out_dir / fname

    lines = []
    date_str = " / ".join(data["week_dates"])

    # Korean section
    lines.append(f"[{data['cafeteria_ko']}] 주간 메뉴 ({date_str})")
    lines.append(
        f"운영시간: " + ", ".join(f"{k} {v}" for k, v in data["hours"].items())
    )
    lines.append("")

    days_ko = [d for d in DAYS_KO if d in data["meals"]]
    for day in days_ko:
        lines.append(f"▶ {day}요일")
        for meal_type, items in data["meals"][day].items():
            if items:
                label = {
                    "lunch": "점심",
                    "lunch_ilpum": "점심(일품)",
                    "lunch_jeongsik": "점심(정식)",
                    "lunch_plus": "점심 PLUS",
                    "takeout": "Take-out",
                    "dinner": "저녁",
                    "dinner_plus": "저녁 PLUS",
                }.get(meal_type, meal_type)
                lines.append(f"  [{label}] {' / '.join(items)}")
        lines.append("")

    # English section
    lines.append("")
    lines.append(f"[{data['cafeteria_en']}] Weekly Menu ({date_str})")
    lines.append(f"Hours: " + ", ".join(f"{k} {v}" for k, v in data["hours"].items()))
    lines.append("")

    days_en = [d for d in DAYS_EN if d in data["meals_en"]]
    for day in days_en:
        lines.append(f"▶ {day}")
        for meal_type, items in data["meals_en"][day].items():
            if items:
                label = {
                    "lunch": "Lunch",
                    "lunch_ilpum": "Lunch (Special)",
                    "lunch_jeongsik": "Lunch (Set)",
                    "lunch_plus": "Lunch PLUS",
                    "takeout": "Take-out",
                    "dinner": "Dinner",
                    "dinner_plus": "Dinner PLUS",
                }.get(meal_type, meal_type)
                lines.append(f"  [{label}] {' / '.join(items)}")
        lines.append("")

    if data.get("note"):
        lines.append(f"* {data['note']}")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  [TXT]  saved -> {out_path}")
    return out_path


# File dispatcher

FILENAME_HINTS = {
    "학생식당": "student",
    "student": "student",
    "교직원식당": "staff",
    "staff": "staff",
    "연구동식당": "rnd",
    "r_d": "rnd",
    "rnd": "rnd",
}


def detect_cafeteria_type(filepath: Path) -> str:
    name_lower = filepath.name.lower()
    for hint, ctype in FILENAME_HINTS.items():
        if hint in name_lower or hint in filepath.name:
            return ctype
    return "unknown"


def parse_file(filepath: Path) -> dict | None:
    ctype = detect_cafeteria_type(filepath)
    suffix = filepath.suffix.lower()

    print(f"Parsing [{ctype}] {filepath.name} ...")

    if ctype == "student" and suffix == ".xlsx":
        return parse_student_cafeteria_xlsx(str(filepath))
    elif ctype == "staff" and suffix == ".xlsx":
        return parse_staff_cafeteria_xlsx(str(filepath))
    elif ctype == "rnd" and suffix == ".pdf":
        return parse_rnd_cafeteria_pdf(str(filepath))
    else:
        print(
            f"  [WARN] Unrecognized combination: type={ctype}, ext={suffix} — skipped."
        )
        return None


# CLI entry point


def main():
    parser = argparse.ArgumentParser(description="DORI Cafeteria Menu Parser")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to a menu file or directory containing menu files",
    )
    parser.add_argument(
        "--output",
        default="./data/campus/processed/cafeteria",
        help="Output directory for JSON + TXT files",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Collect files
    if input_path.is_dir():
        files = list(input_path.glob("*.xlsx")) + list(input_path.glob("*.pdf"))
    elif input_path.is_file():
        files = [input_path]
    else:
        print(f"[ERROR] Input path not found: {input_path}")
        return

    if not files:
        print("[ERROR] No .xlsx or .pdf files found.")
        return

    results = []
    for f in files:
        data = parse_file(f)
        if data:
            to_json(data, out_dir)
            to_txt(data, out_dir)
            results.append(data)

    print(f"\nDone. Parsed {len(results)} file(s) -> {out_dir}")


if __name__ == "__main__":
    main()

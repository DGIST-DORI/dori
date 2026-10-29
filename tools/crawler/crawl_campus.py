#!/usr/bin/env python3
"""
DORI Campus Guide Robot — Campus Knowledge Crawler
Crawls DGIST pages, extracts clean text, and refines with Google API into
structured JSON + txt documents for the RAG knowledge base.

Usage:
  # Crawl all URLs and refine with LLM
  python3 crawl_campus.py --output ./data/campus/

  # Crawl only (no LLM, save raw text for manual review)
  python3 crawl_campus.py --output ./data/campus/ --no-llm

  # Add more URLs at runtime
  python3 crawl_campus.py --urls extra_urls.txt --output ./data/campus/

Dependencies:
  pip install requests beautifulsoup4 google-genai
"""

import argparse
import json
import time
import re
import os
import hashlib
import random
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# URL registry
# Format: (url, category, doc_id, description_ko, description_en)
URL_REGISTRY = [
    # 소개
    (
        "https://www.dgist.ac.kr/kor/sub01_02_04.do",
        "intro",
        "dgist_history",
        "학교 연혁",
        "DGIST History",
    ),
    (
        "https://www.dgist.ac.kr/kor/sub01_03_01.do",
        "intro",
        "dgist_directions",
        "찾아오시는 길",
        "Directions to DGIST",
    ),
    # 학부시설 안내
    (
        "https://www.dgist.ac.kr/college/sub04_01_01.do",
        "facility",
        "facility_edu",
        "교육시설",
        "Educational Facilities",
    ),
    (
        "https://www.dgist.ac.kr/college/sub04_01_02.do",
        "facility",
        "facility_research",
        "연구시설",
        "Research Facilities",
    ),
    (
        "https://www.dgist.ac.kr/college/sub04_01_03.do",
        "facility",
        "facility_welfare",
        "복지시설",
        "Welfare Facilities",
    ),
]

# Crawl config
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DORI-CampusBot/1.0; " "+https://www.dgist.ac.kr)"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}
REQUEST_DELAY = 1.5  # seconds between requests (be polite)
REQUEST_TIMEOUT = 15
MAX_RETRIES = 3
BACKOFF_BASE = 0.5

# Tags whose content we always discard
STRIP_TAGS = [
    "script",
    "style",
    "noscript",
    "iframe",
    "header",
    "footer",
    "nav",
    "aside",
    "form",
    "button",
    "meta",
    "link",
]

# CSS selectors for common DGIST page content containers (try in order)
CONTENT_SELECTORS = [
    "#contents",
    "#content",
    ".contents_area",
    ".content_area",
    "main",
    "article",
    ".board_view",
    ".sub_content",
]

SAFE_DOC_ID_RE = re.compile(r"^[a-z0-9_-]+$")


# Crawler


def _slugify(value: str) -> str:
    """Convert arbitrary text to a filesystem-safe slug."""
    value = value.lower()
    value = re.sub(r"[/?&=:+.%#]+", "_", value)
    value = re.sub(r"[^a-z0-9_-]+", "", value)
    value = re.sub(r"[_-]{2,}", "_", value)
    return value.strip("_-")


def normalize_doc_id(url: str, fallback: str = "page") -> str:
    """
    Build a safe doc_id from URL path (+ partial query).
    Allowed chars: [a-z0-9_-]
    """
    parsed = urlparse(url)
    source = parsed.path or ""
    if parsed.query:
        query_tokens = []
        for pair in parsed.query.split("&")[:4]:
            if not pair:
                continue
            key, _, value = pair.partition("=")
            if key:
                query_tokens.append(key)
            if value:
                query_tokens.append(value)
        if query_tokens:
            source = f"{source}_{'_'.join(query_tokens)}"

    slug = _slugify(source)
    if len(slug) < 3:
        slug = _slugify(fallback)
    return slug or "page"


def ensure_safe_doc_id(doc_id: str) -> str:
    """Validate and return a safe doc_id."""
    safe_id = _slugify(doc_id)
    if not safe_id or not SAFE_DOC_ID_RE.fullmatch(safe_id):
        raise ValueError(f"Unsafe doc_id: {doc_id!r}")
    return safe_id


def sanitize_error_message(err: Exception | str, max_len: int = 400) -> str:
    """Sanitize exception text for reports (best-effort secret redaction)."""
    msg = str(err).strip()
    msg = re.sub(
        r"(?i)(api[_-]?key|token|secret|password)\s*[=:]\s*\S+", r"\1=[REDACTED]", msg
    )
    msg = re.sub(r"(?i)bearer\s+[a-z0-9\-_\.=]+", "Bearer [REDACTED]", msg)
    if len(msg) > max_len:
        msg = msg[:max_len] + "...(truncated)"
    return msg


def fetch_page(
    url: str, session: requests.Session, timeout: float, retries: int
) -> tuple[str | None, str | None]:
    """Fetch a URL and return (raw HTML, error_message)."""
    attempts = max(1, retries)
    last_error = None
    last_status_code = None

    for attempt in range(1, attempts + 1):
        try:
            resp = session.get(url, timeout=timeout)
            last_status_code = resp.status_code

            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                if attempt < attempts:
                    backoff = BACKOFF_BASE * (2 ** (attempt - 1))
                    jitter = random.uniform(0, backoff * 0.2)
                    time.sleep(backoff + jitter)
                    continue
                resp.raise_for_status()

            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text, None
        except requests.exceptions.HTTPError as e:
            last_error = e
            if attempt < attempts:
                backoff = BACKOFF_BASE * (2 ** (attempt - 1))
                jitter = random.uniform(0, backoff * 0.2)
                time.sleep(backoff + jitter)
                continue
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            if attempt < attempts:
                backoff = BACKOFF_BASE * (2 ** (attempt - 1))
                jitter = random.uniform(0, backoff * 0.2)
                time.sleep(backoff + jitter)
                continue
            break
        except Exception as e:
            last_error = e
            break

    print(
        f"  [WARN] Failed to fetch URL={url} attempts={attempts} "
        f"last_status={last_status_code}: {last_error}"
    )
    return None, sanitize_error_message(last_error or "Unknown fetch error")


def extract_text(html: str, url: str) -> str:
    """Extract clean readable text from HTML."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise tags
    for tag in soup(STRIP_TAGS):
        tag.decompose()

    # Try content containers first
    content = None
    for sel in CONTENT_SELECTORS:
        content = soup.select_one(sel)
        if content:
            break

    target = content if content else soup.body or soup

    # Get text, collapse whitespace
    lines = []
    for elem in target.stripped_strings:
        text = elem.strip()
        if text and len(text) > 1:
            lines.append(text)

    raw = "\n".join(lines)
    # Collapse 3+ blank lines to 2
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def crawl_url(
    url: str, doc_id: str, session: requests.Session, timeout: float, retries: int
) -> tuple[dict | None, dict]:
    """Crawl one URL and return (raw_result_or_none, url_status)."""
    status = {
        "fetch": "failed",
        "extract": "failed",
        "llm": "skipped",
        "fallback_used": False,
        "overall": "failed",
    }
    error = None
    print(f"  Fetching: {url}")
    html, fetch_error = fetch_page(
        url, session=session, timeout=timeout, retries=retries
    )
    if not html:
        if fetch_error:
            error = {"stage": "fetch", "message": fetch_error}
        return None, {"status": status, "error": error}
    status["fetch"] = "success"

    try:
        text = extract_text(html, url)
    except Exception as e:
        print(f"  [WARN] Text extraction failed for {url}: {e}")
        error = {"stage": "extract", "message": sanitize_error_message(e)}
        return None, {"status": status, "error": error}

    if not text:
        print(f"  [WARN] No text extracted from {url}")
        error = {"stage": "extract", "message": "No text extracted"}
        return None, {"status": status, "error": error}

    status["extract"] = "success"
    status["overall"] = "success"

    return (
        {
            "url": url,
            "doc_id": doc_id,
            "raw_text": text,
            "fetched_at": datetime.now().isoformat(),
        },
        {"status": status, "error": error},
    )


# LLM refinement

REFINE_SYSTEM = """You are a data extraction assistant for a campus guide robot at DGIST (Daegu Gyeongbuk Institute of Science and Technology), South Korea.

Your job: given raw crawled text from a DGIST webpage, extract the key information and return ONLY a valid JSON object — no markdown fences, no preamble.

JSON schema:
{
  "title_ko": "페이지 제목 (Korean)",
  "title_en": "Page title (English)",
  "summary_ko": "2-3 sentence Korean summary a robot would say to a student",
  "summary_en": "2-3 sentence English summary a robot would say to a student",
  "key_facts": [
    {"label_ko": "...", "label_en": "...", "value": "..."}
  ],
  "full_text_ko": "Clean, well-structured Korean prose preserving all important details",
  "full_text_en": "Clean, well-structured English prose preserving all important details"
}

Rules:
- Remove navigation menus, copyright notices, repeated headers, and UI chrome.
- Preserve dates, building names, room numbers, contact info, and any factual data.
- key_facts should capture the most robot-useful structured info (e.g. addresses, phone numbers, hours, names of facilities).
- If English content is absent, translate naturally from Korean.
- Return ONLY the JSON object."""


def refine_with_llm(
    raw_text: str, description_ko: str, description_en: str, url: str
) -> tuple[dict | None, str | None]:
    """Call Gemini AI to refine raw crawled text into structured data."""
    try:
        from google import genai
    except ImportError:
        print("  [WARN] google-genai package not installed — skipping LLM refinement.")
        return None, "google-genai package not installed"

    try:
        client = genai.Client()

        user_prompt = (
            f"Page: {description_ko} / {description_en}\n"
            f"URL: {url}\n\n"
            f"--- RAW TEXT ---\n{raw_text[:6000]}\n--- END ---\n\n"
            "Extract and structure the information as described."
        )

        prompt = f"{REFINE_SYSTEM}\n\n{user_prompt}"

        resp = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)

        content = resp.text.strip()

        # Strip accidental markdown fences
        content = re.sub(r"^```json\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
        return json.loads(content), None

    except json.JSONDecodeError as e:
        print(f"  [WARN] LLM returned invalid JSON: {e}")
        return None, sanitize_error_message(e)
    except Exception as e:
        print(f"  [WARN] LLM API error: {e}")
        return None, sanitize_error_message(e)


# Output writers


def save_raw(raw: dict, out_dir: Path):
    """Save raw crawled text for review or re-processing."""
    doc_id = ensure_safe_doc_id(raw["doc_id"])
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{doc_id}.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"URL: {raw['url']}\n")
        f.write(f"Fetched: {raw['fetched_at']}\n")
        f.write("=" * 60 + "\n\n")
        f.write(raw["raw_text"])
    print(f"  [RAW]  -> {path}")
    return str(path)


def save_refined(
    refined: dict,
    raw: dict,
    category: str,
    description_ko: str,
    description_en: str,
    out_dir: Path,
):
    """Save LLM-refined data as JSON + txt."""
    doc_id = ensure_safe_doc_id(raw["doc_id"])

    # JSON (structured metadata + key facts)
    json_payload = {
        "doc_id": doc_id,
        "category": category,
        "url": raw["url"],
        "fetched_at": raw["fetched_at"],
        "description_ko": description_ko,
        "description_en": description_en,
        "title_ko": refined.get("title_ko", ""),
        "title_en": refined.get("title_en", ""),
        "summary_ko": refined.get("summary_ko", ""),
        "summary_en": refined.get("summary_en", ""),
        "key_facts": refined.get("key_facts", []),
    }

    json_dir = out_dir / "indexed"
    json_dir.mkdir(parents=True, exist_ok=True)
    json_path = json_dir / f"{doc_id}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, ensure_ascii=False, indent=2)
    print(f"  [JSON] -> {json_path}")

    # TXT (full prose, for RAG vector search)
    txt_dir = out_dir / "processed" / category
    txt_dir.mkdir(parents=True, exist_ok=True)
    txt_path = txt_dir / f"{doc_id}.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"[{refined.get('title_ko', description_ko)}]\n")
        f.write(f"출처: {raw['url']}\n\n")
        f.write(refined.get("full_text_ko", "") + "\n\n")
        f.write("---\n\n")
        f.write(f"[{refined.get('title_en', description_en)}]\n")
        f.write(f"Source: {raw['url']}\n\n")
        f.write(refined.get("full_text_en", "") + "\n")
    print(f"  [TXT]  -> {txt_path}")
    return str(json_path), str(txt_path)


def save_fallback_txt(
    raw: dict, category: str, description_ko: str, description_en: str, out_dir: Path
):
    """Save raw text as txt when LLM refinement fails/skipped."""
    doc_id = ensure_safe_doc_id(raw["doc_id"])
    txt_dir = out_dir / "processed" / category
    txt_dir.mkdir(parents=True, exist_ok=True)
    txt_path = txt_dir / f"{doc_id}_raw.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"[{description_ko} / {description_en}]\n")
        f.write(f"URL: {raw['url']}\n\n")
        f.write(raw["raw_text"])
    print(f"  [TXT]  -> {txt_path} (raw fallback)")
    return str(txt_path)


def save_run_report(report: dict, out_dir: Path, finished_at: datetime) -> str:
    """Persist per-run crawler report for dashboard API consumption."""
    reports_dir = out_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    ts = finished_at.strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"crawl_report_{ts}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[REPORT] -> {report_path}")
    return str(report_path)


# URL list loader


def load_extra_urls(path: str) -> list[tuple]:
    """
    Load extra URLs from a text file.
    Format (one per line):
      https://... [category] [doc_id] # optional comment
    or plain URL lines (category=misc, doc_id auto-generated).
    """
    entries = []
    seen_doc_ids = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            url = parts[0]
            category = parts[1] if len(parts) > 1 else "misc"
            doc_hint = parts[2] if len(parts) > 2 else None
            if doc_hint:
                doc_id = ensure_safe_doc_id(doc_hint)
            else:
                doc_id = normalize_doc_id(url, fallback="page")

            if doc_id in seen_doc_ids:
                suffix = hashlib.sha1(url.encode("utf-8")).hexdigest()[:6]
                doc_id = f"{doc_id}_{suffix}"
            seen_doc_ids.add(doc_id)
            entries.append((url, category, doc_id, doc_id, doc_id))
    return entries


# Main


def main():
    parser = argparse.ArgumentParser(description="DORI Campus Knowledge Crawler")
    parser.add_argument(
        "--output", default="./data/campus", help="Output root directory"
    )
    parser.add_argument(
        "--no-llm", action="store_true", help="Skip LLM refinement, save raw text only"
    )
    parser.add_argument("--urls", default=None, help="Path to extra URL list file")
    parser.add_argument(
        "--delay",
        type=float,
        default=REQUEST_DELAY,
        help=f"Delay between requests in seconds (default {REQUEST_DELAY})",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=MAX_RETRIES,
        help=f"Max fetch attempts for timeout/connection/429/5xx (default {MAX_RETRIES})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=REQUEST_TIMEOUT,
        help=f"Request timeout in seconds (default {REQUEST_TIMEOUT})",
    )
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update(HEADERS)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    registry = list(URL_REGISTRY)
    if args.urls:
        registry += load_extra_urls(args.urls)

    print(f"DORI Crawler — {len(registry)} URL(s) to process\n")
    started_at = datetime.now()
    run_report = {
        "report_version": "1.0",
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "duration_sec": None,
        "options": {
            "no_llm": args.no_llm,
            "delay": args.delay,
            "retries": args.retries,
            "timeout": args.timeout,
            "urls": args.urls,
            "output": str(out_dir),
        },
        "summary": {
            "input_url_count": len(registry),
            "success_count": 0,
            "failure_count": 0,
        },
        "urls": [],
    }

    for url, category, doc_id, desc_ko, desc_en in registry:
        print(f"[{doc_id}] {desc_ko}")
        entry = {
            "url": url,
            "doc_id": doc_id,
            "category": category,
            "status": {
                "fetch": "failed",
                "extract": "failed",
                "llm": "skipped",
                "fallback_used": False,
                "overall": "failed",
            },
            "error": None,
            "outputs": {
                "raw_txt": None,
                "indexed_json": None,
                "processed_txt": None,
            },
        }

        raw, crawl_meta = crawl_url(
            url,
            doc_id,
            session=session,
            timeout=args.timeout,
            retries=args.retries,
        )
        entry["status"].update(crawl_meta["status"])
        entry["error"] = crawl_meta["error"]
        if not raw:
            print("  [SKIP] Could not fetch page.\n")
            run_report["summary"]["failure_count"] += 1
            run_report["urls"].append(entry)
            continue

        entry["outputs"]["raw_txt"] = save_raw(raw, out_dir)

        if not args.no_llm:
            print("  Refining with LLM...")
            refined, llm_error = refine_with_llm(raw["raw_text"], desc_ko, desc_en, url)
            if refined:
                entry["status"]["llm"] = "success"
                json_path, txt_path = save_refined(
                    refined, raw, category, desc_ko, desc_en, out_dir
                )
                entry["outputs"]["indexed_json"] = json_path
                entry["outputs"]["processed_txt"] = txt_path
            else:
                print("  [WARN] LLM refinement failed — saving raw fallback.")
                entry["status"]["llm"] = "failed"
                entry["status"]["fallback_used"] = True
                if llm_error:
                    entry["error"] = {"stage": "llm", "message": llm_error}
                entry["outputs"]["processed_txt"] = save_fallback_txt(
                    raw, category, desc_ko, desc_en, out_dir
                )
        else:
            entry["status"]["llm"] = "skipped"
            entry["status"]["fallback_used"] = True
            entry["outputs"]["processed_txt"] = save_fallback_txt(
                raw, category, desc_ko, desc_en, out_dir
            )

        if (
            entry["status"]["extract"] == "success"
            and entry["outputs"]["processed_txt"]
        ):
            entry["status"]["overall"] = "success"
            run_report["summary"]["success_count"] += 1
        else:
            run_report["summary"]["failure_count"] += 1

        run_report["urls"].append(entry)

        time.sleep(args.delay)

    finished_at = datetime.now()
    run_report["finished_at"] = finished_at.isoformat()
    run_report["duration_sec"] = round((finished_at - started_at).total_seconds(), 3)
    report_path = save_run_report(run_report, out_dir, finished_at)

    print(f"\nDone. Output -> {out_dir}")
    print(f"Report -> {report_path}")


if __name__ == "__main__":
    main()

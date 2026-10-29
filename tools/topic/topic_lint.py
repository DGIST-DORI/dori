#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOPIC_PATH = ROOT / "config/ros2_topics.yaml"
ARCH_PATH = ROOT / "docs/dev/architecture.md"
STORE_PATH = ROOT / "web/src/core/store.js"
ARCH_START = "<!-- TOPIC:START -->"
ARCH_END = "<!-- TOPIC:END -->"
TOPIC_RE = re.compile(r"['\"](/dori/[a-zA-Z0-9_\-/]+)['\"]")


def load_topic() -> list[dict]:
    data = json.loads(TOPIC_PATH.read_text(encoding="utf-8"))
    topics = data.get("topics", [])
    if not isinstance(topics, list):
        raise ValueError('config/ros2_topics.yaml: "topics" must be a list')
    return topics


def md_list(items: list[str]) -> str:
    return ", ".join(items) if items else "-"


def render_arch_topic_section(entries: list[dict]) -> str:
    app = [e for e in entries if str(e.get("topic", "")).startswith("/dori/")]
    base = [e for e in entries if not str(e.get("topic", "")).startswith("/dori/")]

    lines = [
        "#### Topic List source of truth",
        "",
        "- Source file: `config/ros2_topics.yaml`.",
        "- This section is generated/synchronized from the YAML file via `python3 tools/topic/topic_lint.py --sync-architecture`.",
        "- CI runs `python3 tools/topic/topic_lint.py --check` and emits warnings if drift is detected.",
        "",
        ARCH_START,
        "#### In-scope application topics",
        "",
        "| Topic | Msg type | Publisher(s) | Subscriber(s) | Description |",
        "|---|---|---|---|---|",
    ]
    for e in app:
        lines.append(
            f"| `{e['topic']}` | `{e.get('msg_type', 'unknown')}` | {md_list(e.get('publishers', []))} | {md_list(e.get('subscribers', []))} | {e.get('description', '')} |"
        )

    lines += [
        "",
        "#### Out of documentation scope (base platform topics)",
        "",
        "| Topic | Msg type | Publisher(s) | Subscriber(s) | Description |",
        "|---|---|---|---|---|",
    ]
    for e in base:
        lines.append(
            f"| `{e['topic']}` | `{e.get('msg_type', 'unknown')}` | {md_list(e.get('publishers', []))} | {md_list(e.get('subscribers', []))} | {e.get('description', '')} |"
        )

    lines += [ARCH_END, ""]
    return "\n".join(lines)


def extract_code_topics() -> set[str]:
    out: set[str] = set()
    for base in [ROOT / "ros2_ws/src", ROOT / "web/src"]:
        for p in base.rglob("*"):
            if p.suffix.lower() not in {
                ".py",
                ".cpp",
                ".hpp",
                ".c",
                ".h",
                ".js",
                ".jsx",
                ".ts",
                ".tsx",
            }:
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            out.update(TOPIC_RE.findall(text))
    return out


def extract_topic_meta_topics() -> set[str]:
    text = STORE_PATH.read_text(encoding="utf-8")
    m = re.search(r"export const TOPIC_META = \{(?P<body>.*?)\n\};", text, flags=re.S)
    if not m:
        return set()
    return set(TOPIC_RE.findall(m.group("body")))


def check(sync_arch: bool, check_only: bool) -> int:
    entries = load_topic()
    yaml_topics = {e["topic"] for e in entries if "topic" in e}

    code_topics = extract_code_topics()
    meta_topics = extract_topic_meta_topics()

    missing_from_yaml = sorted(t for t in code_topics if t not in yaml_topics)
    stale_in_yaml = sorted(t for t in yaml_topics if t not in code_topics)

    missing_meta_in_yaml = sorted(t for t in meta_topics if t not in yaml_topics)
    missing_yaml_in_meta = sorted(
        t for t in yaml_topics if t.startswith("/dori/") and t not in meta_topics
    )

    generated = render_arch_topic_section(entries)
    arch_text = ARCH_PATH.read_text(encoding="utf-8")

    arch_ok = generated in arch_text
    if sync_arch and not arch_ok:
        new = re.sub(
            rf"{re.escape(ARCH_START)}.*?{re.escape(ARCH_END)}\\n?",
            generated,
            arch_text,
            flags=re.S,
        )
        if new == arch_text:
            anchor = "### ROS2 Topic List (Actual Nodes)"
            if anchor in arch_text:
                new = arch_text.replace(anchor, anchor + "\n\n" + generated, 1)
        ARCH_PATH.write_text(new, encoding="utf-8")
        arch_ok = True

    def warn(msg: str) -> None:
        print(f"::warning::{msg}")

    if missing_from_yaml:
        warn(
            f'Code topic scan found topics missing in ros2_topics.yaml: {", ".join(missing_from_yaml)}'
        )
    if stale_in_yaml:
        warn(
            f'ros2_topics.yaml has topics not found in code scan: {", ".join(stale_in_yaml)}'
        )
    if missing_meta_in_yaml:
        warn(
            f'TOPIC_META has topics missing in ros2_topics.yaml: {", ".join(missing_meta_in_yaml)}'
        )
    if missing_yaml_in_meta:
        warn(
            f'ros2_topics.yaml /dori topics missing in TOPIC_META: {", ".join(missing_yaml_in_meta)}'
        )
    if check_only and not arch_ok:
        warn(
            "docs/dev/architecture.md topic section is out-of-sync with ros2_topics.yaml. Run --sync-architecture."
        )

    print(
        f"ros2_topics.yaml entries={len(yaml_topics)} code_topics={len(code_topics)} topic_meta={len(meta_topics)}"
    )
    # warning-only lint by design
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--check", action="store_true", help="Run drift checks and emit warnings."
    )
    ap.add_argument(
        "--sync-architecture",
        action="store_true",
        help="Synchronize architecture topic section from YAML.",
    )
    args = ap.parse_args()

    return check(sync_arch=args.sync_architecture, check_only=args.check)


if __name__ == "__main__":
    raise SystemExit(main())

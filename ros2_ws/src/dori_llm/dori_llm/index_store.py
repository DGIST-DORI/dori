"""Immutable index generations selected by a single atomic CURRENT pointer."""
import json
from pathlib import Path
import re

from .corpus import digest

INDEX_FILE = "index.faiss"
META_FILE = "metadata.json"
HASH_FILE = "file_hashes.json"
MANIFEST_FILE = "manifest.json"


def active_directory(root):
    root = Path(root)
    pointer = root / "CURRENT"
    if not pointer.exists():
        return root  # Legacy layout is recognized so builders can request migration.
    generation = pointer.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", generation):
        raise ValueError("Invalid index generation pointer")
    path = root / "generations" / generation
    if not path.is_dir():
        raise ValueError("Active index generation is missing")
    return path


def read_manifest(path, verify=True):
    path = Path(path)
    manifest = json.loads((path / MANIFEST_FILE).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported index manifest version")
    if verify:
        for name in (INDEX_FILE, META_FILE, HASH_FILE):
            if digest((path / name).read_bytes()) != manifest["checksums"].get(name):
                raise ValueError(f"Index checksum mismatch: {name}")
    return manifest

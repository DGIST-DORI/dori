"""Source records shared by ingestion and indexing; no ML dependencies."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def digest(data):
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def write_document(path, text, metadata):
    """Commit metadata last; readers reject any intermediate content mismatch."""
    text = text.strip() + "\n"
    record = {**metadata, "schema_version": 1, "text_sha256": digest(text)}
    atomic_write(path, text)
    atomic_write(Path(path).with_suffix(".json"), json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


def expired(record, now=None):
    until = record.get("valid_until")
    if not until:
        return False
    value = datetime.fromisoformat(until.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("valid_until must include a timezone")
    return value <= (now or datetime.now(timezone.utc))


def available(record, now=None):
    now = now or datetime.now(timezone.utc)
    since = record.get("valid_from")
    if since:
        value = datetime.fromisoformat(since.replace("Z", "+00:00"))
        if value.tzinfo is None:
            raise ValueError("valid_from must include a timezone")
        if value > now:
            return False
    return not expired(record, now)


def read_document(path, root):
    path, root = Path(path), Path(root)
    raw = path.read_text(encoding="utf-8")
    if not raw.strip():
        raise ValueError(f"Empty document: {path}")
    sidecar = path.with_suffix(".json")
    if not sidecar.is_file():
        raise ValueError(f"Source metadata missing: {sidecar}; re-ingest this document")
    record = json.loads(sidecar.read_text(encoding="utf-8"))
    if record.get("schema_version") != 1 or record.get("text_sha256") != digest(raw):
        raise ValueError(f"Document metadata/content mismatch: {path}; re-ingest this document")
    if not record.get("source_url") and not record.get("source_file"):
        raise ValueError(f"Source provenance missing: {path}")
    if not record.get("fetched_at") and not record.get("parsed_at"):
        raise ValueError(f"Source timestamp missing: {path}")
    for key in ("fetched_at", "parsed_at", "valid_from", "valid_until"):
        if record.get(key):
            parsed = datetime.fromisoformat(record[key].replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError(f"{key} must include a timezone: {path}")
    if record.get("kind") in ("web", "menu") and not record.get("valid_until"):
        raise ValueError(f"Source validity is missing: {path}")
    key = path.relative_to(root).as_posix()
    return {**record, "source": key, "source_key": key, "text": raw.strip(),
            "fingerprint": digest(raw + json.dumps(record, sort_keys=True, ensure_ascii=False))}

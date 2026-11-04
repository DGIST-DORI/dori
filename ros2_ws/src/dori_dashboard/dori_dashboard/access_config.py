"""Persistent, non-secret Access settings; explicit environment values take priority."""
import json
import os
from pathlib import Path


def load_access_config(repo_root: Path) -> dict[str, str]:
    path = repo_root / "config" / "dashboard_access.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        config = {}
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"Cannot read Cloudflare Access configuration: {path}") from exc
    if not isinstance(config, dict):
        raise RuntimeError(f"Cloudflare Access configuration must be an object: {path}")

    settings = {}
    for key, variable in (
        ("team_domain", "DORI_CF_TEAM_DOMAIN"),
        ("audience", "DORI_CF_AUDIENCE"),
        ("role_map", "DORI_CF_ROLE_MAP"),
    ):
        value = os.environ.get(variable, config.get(key, ""))
        if not isinstance(value, str):
            raise RuntimeError(f"Cloudflare Access setting {key} must be a string")
        settings[key] = value.strip()
    return settings

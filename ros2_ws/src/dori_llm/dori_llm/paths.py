"""
Shared path utilities for DORI packages.

Priority order for asset resolution:
  1) ROS2 share directory (installed, production)
  2) Repo root data/ directory (development fallback)

Usage:
    from dori_llm.paths import get_knowledge_file, get_rag_index_dir
    from dori_llm.paths import get_asset  # generic helper
"""

from pathlib import Path


def is_repo_root(parent: Path) -> bool:
    """Return True when parent matches repository-root markers."""
    has_readme = (parent / 'README.md').exists()
    has_ros2_src = (parent / 'ros2_ws' / 'src').is_dir()
    has_git = (parent / '.git').exists()
    return has_readme and (has_ros2_src or has_git)


def find_repo_root(start: Path = None) -> Path:
    """Walk up from start until we find the repo root.

    Root markers:
      - ros2_ws/src directory + README.md
      - OR .git + README.md
    """
    start = start or Path(__file__).resolve().parent
    for parent in [start, *start.parents]:
        if is_repo_root(parent):
            return parent
    return start


def get_asset(relative_to_share: str, pkg_name: str) -> Path:
    """
    Resolve an asset path.
    Tries share directory first (installed/production), then repo root (development).

    Args:
        relative_to_share: path relative to the package's share directory,
                           e.g. 'config/campus_knowledge.json'
        pkg_name:          ROS2 package name that owns the asset

    Returns:
        Path to the asset (may not exist if neither location has it)
    """
    # Priority 1: ROS2 share directory (production)
    try:
        from ament_index_python.packages import get_package_share_directory
        share_path = Path(get_package_share_directory(pkg_name)) / relative_to_share
        if share_path.exists():
            return share_path
    except Exception:
        pass

    # Priority 2: repo root fallback (development)
    return find_repo_root() / relative_to_share


# ── Convenience helpers ────────────────────────────────────────────────────────

def get_knowledge_file() -> Path:
    """
    Path to campus_knowledge.json.
    Share: dori_llm/config/campus_knowledge.json
    Dev:   data/campus/indexed/campus_knowledge.json
    """
    # Try share first
    path = get_asset('config/campus_knowledge.json', 'dori_llm')
    if path.exists():
        return path
    # Dev fallback: data/campus/indexed/
    return find_repo_root() / 'data' / 'campus' / 'indexed' / 'campus_knowledge.json'


def get_rag_index_dir() -> Path:
    """
    Directory containing FAISS index (index.faiss, metadata.json, file_hashes.json).
    Dev:  data/campus/indexed/
    """
    return find_repo_root() / 'data' / 'campus' / 'indexed'



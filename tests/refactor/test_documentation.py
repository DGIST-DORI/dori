"""Check current operating instructions without treating legacy notes as current."""
from pathlib import Path
import re
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = (
    'README.md', 'docs/user/DORI-AMM.md', 'docs/dev/package-ownership.md',
    'docs/dev/refactor-validation.md', 'maps/README.md', 'web/README.md', 'tools/drive/README.md',
    'ros2_ws/src/third_party/cubemars_hardware/README.md',
)


def test_active_document_links_and_removed_root_commands():
    for name in DOCUMENTS:
        document = ROOT/name
        text = document.read_text()
        for link in re.findall(r'\]\(([^)]+)\)', text):
            target = unquote(link.split('#', 1)[0])
            if not target or '://' in target:
                continue
            assert (document.parent/target).exists(), (name, link)
        # Package-local scripts remain valid; only the deleted root helpers
        # must not be presented as current operating commands.
        assert not re.search(r'(?<![\w/])scripts/[\w.-]+\.(?:py|sh)\b', text), name

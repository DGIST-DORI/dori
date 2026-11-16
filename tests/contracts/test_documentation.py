"""Check current operating instructions without treating legacy notes as current."""
from pathlib import Path
import re
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = (
    'README.md', 'docs/user/DORI-AMM.md', 'docs/dev/package-ownership.md',
    'docs/dev/architecture.md', 'ros2_ws/src/dori_perception/README.md',
    'ros2_ws/src/dori_perception_camera/README.md',
    'docs/dev/refactor-validation.md', 'maps/README.md', 'web/README.md', 'tools/drive/README.md',
    'ros2_ws/src/third_party/cubemars_hardware/README.md',
)


def test_active_document_links_and_root_commands_exist():
    for name in DOCUMENTS:
        document = ROOT/name
        text = document.read_text()
        for link in re.findall(r'\]\(([^)]+)\)', text):
            target = unquote(link.split('#', 1)[0])
            if not target or '://' in target:
                continue
            assert (document.parent/target).exists(), (name, link)
        # Root launch/build helpers exist again. Reject missing helpers, rather
        # than treating every scripts/ reference as a retired command.
        for helper in re.findall(r'(?<![\w/])scripts/[\w.-]+\.(?:py|sh)\b', text):
            assert (ROOT / helper).is_file(), (name, helper)

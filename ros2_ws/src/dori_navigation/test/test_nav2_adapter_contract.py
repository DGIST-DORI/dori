"""Regression checks for the public DORI-to-Nav2 navigation boundary."""

from pathlib import Path
from ament_index_python.packages import get_package_prefix


ROOT = Path(__file__).resolve().parents[1]


def test_legacy_navigator_is_not_packaged():
    installed = Path(get_package_prefix('dori_navigation')) / 'lib' / 'dori_navigation'
    assert (installed / 'nav2_adapter').is_file()
    assert not (installed / 'navigator_node').exists()
    assert not (ROOT / 'dori_navigation' / 'navigator.py').exists()
    assert not (ROOT / 'launch' / 'navigation.launch.py').exists()


def test_adapter_keeps_dori_action_and_uses_nav2():
    source = (ROOT / 'dori_navigation' / 'nav2_adapter.py').read_text()
    assert '/dori/nav/navigate_to' in source
    assert 'NavigateToPose' in source
    assert 'GoalStatus.STATUS_SUCCEEDED' in source


def test_real_profile_uses_the_adapter():
    launch = (ROOT / 'launch' / 'real_navigation.launch.py').read_text()
    assert "executable='nav2_adapter'" in launch or 'executable="nav2_adapter"' in launch

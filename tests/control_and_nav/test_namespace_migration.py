"""Installed package graph and generated DDS contracts after the DORI merge."""
from graphlib import TopologicalSorter
from pathlib import Path
import xml.etree.ElementTree as ET

from ament_index_python.packages import get_packages_with_prefixes, get_package_prefix
from rclpy.serialization import deserialize_message, serialize_message

ROOT = Path(__file__).resolve().parents[2]


def test_source_and_clean_install_have_the_same_acyclic_package_graph():
    manifests = [ET.parse(path).getroot() for path in (ROOT/'ros2_ws/src').rglob('package.xml')]
    names = [manifest.findtext('name') for manifest in manifests]
    assert len(names) == len(set(names)) == 24
    assert not any(name.startswith('robot_') for name in names)
    graph = {manifest.findtext('name'): {child.text for child in manifest
             if child.tag.endswith('depend') and child.text in names} for manifest in manifests}
    assert len(tuple(TopologicalSorter(graph).static_order())) == 24
    installed = {name for name, prefix in get_packages_with_prefixes().items()
                 if Path(prefix).is_relative_to(ROOT/'ros2_ws/install')}
    assert installed == set(names)
    assert not list((ROOT/'ros2_ws/install').glob('robot_*'))


def test_merged_navigation_installs_python_actions_cpp_plugin_and_web():
    import dori_navigation.nav2_adapter
    import dori_navigation.named_goal_adapter
    import dori_web.bridge
    prefix = Path(get_package_prefix('dori_navigation'))
    for executable in ('nav2_adapter', 'named_goal_adapter', 'web_viewer.py'):
        assert (prefix/'lib/dori_navigation'/executable).is_file()
    assert (prefix/'lib/librelaxed_heading_planner.so').is_file()
    for asset in ('launch/real_nav2.launch.py', 'launch/real_navigation.launch.py',
                  'config/motion_interpreter.yaml', 'static/index.html'):
        assert (prefix/'share/dori_navigation'/asset).is_file()


def test_control_messages_and_hri_actions_share_working_native_type_support():
    from dori_msgs.msg import MitCommand, CommandFeedback, SystemError, TransformStep, TransformStepResult
    from dori_msgs.action import Navigate, NavigateNamed, Speak, LLMQuery
    command = MitCommand(motor_id=1, v_des=2.5, tau_ff=.3)
    for message in (command, CommandFeedback(), SystemError(), TransformStep(), TransformStepResult(),
                    Navigate.Goal(), NavigateNamed.Goal(), Speak.Goal(), LLMQuery.Goal()):
        restored = deserialize_message(serialize_message(message), type(message))
        assert restored == message
        assert type(restored).__module__.startswith('dori_msgs.')

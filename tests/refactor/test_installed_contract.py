"""P0/P2 acceptance on a clean Humble overlay; never executes a ROS node.

This deliberately does not collect the legacy integration suite awaiting P1.
"""
from graphlib import TopologicalSorter
import importlib
import os
from pathlib import Path
import runpy
import shutil
import sys
import xml.etree.ElementTree as ET

import pytest
from ament_index_python.packages import get_package_prefix, get_package_share_directory
from ament_index_python.packages import get_packages_with_prefixes
from launch import LaunchContext, LaunchDescription
from launch.actions import (
    DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription, OpaqueFunction,
    RegisterEventHandler, SetLaunchConfiguration,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.utilities import normalize_to_list_of_substitutions, perform_substitutions
from launch_ros.actions import Node
from launch_ros.utilities import evaluate_parameters
from rclpy.serialization import deserialize_message, serialize_message

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    'cubemars_hardware', 'dori_bringup', 'dori_bt', 'dori_control', 'dori_core',
    'dori_dashboard', 'dori_diagnostics', 'dori_hardware', 'dori_hri', 'dori_llm',
    'dori_mapping', 'dori_msgs', 'dori_navigation', 'dori_observability',
    'dori_perception', 'dori_perception_camera', 'dori_supervisor',
    'dynamixel_sdk', 'dynamixel_sdk_custom_interfaces', 'dynamixel_sdk_examples',
    'sllidar_ros2',
}
REMOVED = {
    'dori_drive', 'dori_input', 'dori_transform', 'dori_error', 'imu_serial',
    'robot_bringup', 'robot_drive', 'robot_input', 'robot_transform', 'robot_error',
    'robot_mapping', 'robot_navigation', 'robot_msgs', 'robot_supervisor',
}
IMU_NODES = ('imu_node', 'body_pitch_node', 'body_stabilizer_node', 'servo3_pitch_follower_node')


def test_source_install_and_dependency_graph():
    manifests = [ET.parse(p).getroot() for p in (ROOT/'ros2_ws/src').rglob('package.xml')]
    names = [m.findtext('name') for m in manifests]
    assert len(names) == len(EXPECTED) == len(set(names))
    assert set(names) == EXPECTED
    graph = {}
    for manifest in manifests:
        name = manifest.findtext('name')
        dependencies = {c.text for c in manifest if c.tag.endswith('depend')}
        assert not dependencies & (REMOVED | {name}), (name, dependencies)
        graph[name] = dependencies & EXPECTED
    assert set(TopologicalSorter(graph).static_order()) == EXPECTED
    installed = get_packages_with_prefixes()
    assert not set(installed) & REMOVED, 'A removed package is leaking from another overlay'
    local = {name for name, prefix in installed.items()
             if Path(prefix).is_relative_to(ROOT/'ros2_ws/install')}
    assert local == EXPECTED
    assert not {p.name for p in (ROOT/'ros2_ws/install').iterdir()} & REMOVED


@pytest.mark.parametrize('package,executables', [
    ('dori_control', ('drive_controller_node', 'bldc_command_bridge_node',
                      'wheel_odometry_node', 'tf_authority_check', 'transform_manager_node',
                      'transform_controller_node', 'fake_joint_states_node',
                      'joystick_input_node', 'keyboard_input_node', 'virtual_vlm_input_node')),
    ('dori_hardware', ('dxl_bridge_node', 'dxl_state_publisher_node', *IMU_NODES)),
    ('dori_diagnostics', ('error_manager_node',)),
    ('dori_navigation', ('nav2_adapter', 'named_goal_adapter', 'web_viewer.py')),
])
def test_installed_executables(package, executables):
    directory = Path(get_package_prefix(package))/'lib'/package
    for executable in executables:
        path = directory/executable
        assert path.is_file() and os.access(path, os.X_OK), path


@pytest.mark.parametrize('name', IMU_NODES)
def test_installed_imu_entrypoint_imports_without_opening_devices(name, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Packaging checks must not open hardware or initialize ROS')
    import rclpy
    import serial
    monkeypatch.setattr(serial, 'Serial', forbidden)
    monkeypatch.setattr(rclpy, 'init', forbidden)
    module = importlib.import_module('dori_hardware.'+name)
    assert Path(module.__file__).is_relative_to(ROOT/'ros2_ws/install/dori_hardware')
    path = Path(get_package_prefix('dori_hardware'))/'lib/dori_hardware'/name
    namespace = runpy.run_path(str(path), run_name='packaging_import_only')
    assert namespace['main'] is module.main


def test_message_and_action_type_support():
    from dori_msgs.msg import MitCommand, CommandFeedback, SystemError, TransformStep, TransformStepResult
    from dori_msgs.action import Navigate, NavigateNamed, Speak, LLMQuery
    for message in (MitCommand(motor_id=1, v_des=2.5), CommandFeedback(), SystemError(),
                    TransformStep(), TransformStepResult(), Navigate.Goal(),
                    NavigateNamed.Goal(), Speak.Goal(), LLMQuery.Goal()):
        assert deserialize_message(serialize_message(message), type(message)) == message


def resolve(context, value):
    return perform_substitutions(context, normalize_to_list_of_substitutions(value))


def inspect_launch(package, filename, overrides):
    """Whitelist launch-description expansion, without starting a LaunchService.

    Node/ExecuteProcess.execute are never called. Parameter evaluation may invoke
    xacro, which only expands the URDF. Humble's normalized Node parameter list
    is inspected before execution so missing YAML files cannot be hidden.
    """
    context = LaunchContext()
    context.launch_configurations.update(overrides)
    nodes = []

    def expand(actions):
        for action in actions:
            condition = getattr(action, 'condition', None)
            if condition is not None and not condition.evaluate(context):
                continue
            if isinstance(action, Node):
                pkg = resolve(context, action.node_package)
                exe = resolve(context, action.node_executable)
                path = Path(get_package_prefix(pkg))/'lib'/pkg/exe
                assert path.is_file() and os.access(path, os.X_OK), path
                parameters = evaluate_parameters(context, action._Node__parameters)
                for parameter in parameters:
                    if isinstance(parameter, (str, Path)):
                        assert Path(parameter).is_file(), parameter
                    elif isinstance(parameter, dict) and 'robot_description' in parameter:
                        assert ET.fromstring(parameter['robot_description']).tag == 'robot'
                nodes.append((pkg, exe, parameters))
            elif isinstance(action, ExecuteProcess):
                command = [resolve(context, item) for item in action.cmd]
                assert shutil.which(command[0]), command
                for argument in command[1:]:
                    if argument.endswith(('.py', '.yaml', '.xml')):
                        assert Path(argument).is_file(), argument
            elif isinstance(action, LaunchDescription):
                expand(action.entities)
            elif isinstance(action, (DeclareLaunchArgument, SetLaunchConfiguration,
                                     IncludeLaunchDescription, OpaqueFunction)):
                expand(action.execute(context) or [])
            elif isinstance(action, RegisterEventHandler):
                # Process-exit handlers only apply to a running launch service.
                continue
            else:
                raise AssertionError(f'Unreviewed launch action: {type(action)}')

    path = Path(get_package_share_directory(package))/'launch'/filename
    expand([PythonLaunchDescriptionSource(str(path)).get_launch_description(context)])
    return nodes


@pytest.fixture
def no_process_launch(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError('A launch test attempted to execute a process')
    monkeypatch.setattr(Node, 'execute', forbidden)
    monkeypatch.setattr(ExecuteProcess, 'execute', forbidden)
    # Isolate generated Cartographer config and launch-added import directories.
    monkeypatch.setattr('tempfile.tempdir', str(tmp_path))
    monkeypatch.setattr(sys, 'path', list(sys.path))


@pytest.mark.parametrize('package,filename,options', [
    ('dori_hardware', 'system_real_with_imu.launch.py', {'use_joystick': 'true'}),
    ('dori_control', 'odometry.launch.py', {}),
    ('dori_mapping', 'lidar_odometry.launch.py', {}),
    ('dori_mapping', 'lidar_only_cartographer.launch.py', {}),
    ('dori_navigation', 'real_nav2.launch.py', {}),
    ('dori_bringup', 'dori_dev.launch.py', {}),
])
def test_installed_launch_paths(no_process_launch, package, filename, options):
    nodes = inspect_launch(package, filename, {
        'map': str(ROOT/'maps/live_navigation_20261023_1938.yaml'), **options})
    assert nodes


def test_full_robot_resolves_and_excludes_inherited_virtual_inputs(no_process_launch):
    nodes = inspect_launch('dori_bringup', 'real_robot.launch.py', {
        'map': str(ROOT/'maps/live_navigation_20261023_1938.yaml'),
        'use_input_nodes': 'true',
    })
    executables = [exe for _, exe, _ in nodes]
    assert executables.count('drive_controller_node') == 1
    assert executables.count('mode_manager_node') == 1
    assert set(IMU_NODES) <= set(executables)
    assert not {'virtual_vlm_input_node', 'keyboard_input_node',
                'joystick_input_node', 'wheel_odometry_node'} & set(executables)
    assert {'rosbridge_websocket', 'rosapi_node', 'nav2_adapter', 'named_goal_adapter',
            'web_viewer.py', 'dori_tree_executor', 'stt_node', 'tts_node'} <= set(executables)


def test_dashboard_and_native_plugin_assets_installed():
    nav = Path(get_package_prefix('dori_navigation'))
    assert (nav/'lib/librelaxed_heading_planner.so').is_file()
    assert (nav/'share/dori_navigation/static/index.html').is_file()
    web = Path(get_package_share_directory('dori_dashboard'))/'web'
    assert (web/'index.html').is_file()
    assert list((web/'assets').glob('*.js'))

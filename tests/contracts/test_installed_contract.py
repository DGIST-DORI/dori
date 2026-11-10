"""Overlay, packaging, launch and interface contracts on a clean Humble install.

Validates the package dependency graph, absence of deprecated overlays, installed
executables, custom message and action serialization, and launch resolution without
starting any hardware or background nodes.
"""

from graphlib import TopologicalSorter
import importlib
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from unittest.mock import patch

import pytest
from ament_index_python.packages import get_package_prefix, get_package_share_directory
from ament_index_python.packages import get_packages_with_prefixes
from launch import LaunchContext, LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    OpaqueFunction,
    RegisterEventHandler,
    SetLaunchConfiguration,
    SetEnvironmentVariable,
    GroupAction,
    PushLaunchConfigurations,
    PopLaunchConfigurations,
    PushEnvironment,
    PopEnvironment,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.utilities import normalize_to_list_of_substitutions, perform_substitutions
from launch_ros.actions import Node
from launch_ros.utilities import evaluate_parameters
from rclpy.serialization import deserialize_message, serialize_message

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = {
    "cubemars_hardware",
    "dori_bringup",
    "dori_bt",
    "dori_control",
    "dori_core",
    "dori_dashboard",
    "dori_diagnostics",
    "dori_hardware",
    "dori_hri",
    "dori_llm",
    "dori_mapping",
    "dori_msgs",
    "dori_navigation",
    "dori_observability",
    "dori_perception",
    "dori_perception_camera",
    "dori_supervisor",
    "dynamixel_sdk",
    "dynamixel_sdk_custom_interfaces",
    "dynamixel_sdk_examples",
    "sllidar_ros2",
}
REMOVED = {
    "dori_drive",
    "dori_input",
    "dori_transform",
    "dori_error",
    "imu_serial",
    "robot_bringup",
    "robot_drive",
    "robot_input",
    "robot_transform",
    "robot_error",
    "robot_mapping",
    "robot_navigation",
    "robot_msgs",
    "robot_supervisor",
}
IMU_NODES = (
    "imu_node",
    "body_pitch_node",
    "body_stabilizer_node",
    "servo3_pitch_follower_node",
)


def test_source_install_and_dependency_graph():
    manifests = [
        ET.parse(p).getroot() for p in (ROOT / "ros2_ws/src").rglob("package.xml")
    ]
    names = [m.findtext("name") for m in manifests]
    assert len(names) == len(EXPECTED) == len(set(names))
    assert set(names) == EXPECTED
    graph = {}
    for manifest in manifests:
        name = manifest.findtext("name")
        dependencies = {c.text for c in manifest if c.tag.endswith("depend")}
        assert not dependencies & (REMOVED | {name}), (name, dependencies)
        graph[name] = dependencies & EXPECTED
        if name != "dori_bringup":
            assert "dori_bringup" not in dependencies, name
    assert set(TopologicalSorter(graph).static_order()) == EXPECTED
    installed = get_packages_with_prefixes()
    assert (
        not set(installed) & REMOVED
    ), "A removed package is leaking from another overlay"
    local = {
        name
        for name, prefix in installed.items()
        if Path(prefix).is_relative_to(ROOT / "ros2_ws/install")
    }
    assert local == EXPECTED
    assert not {p.name for p in (ROOT / "ros2_ws/install").iterdir()} & REMOVED


@pytest.mark.parametrize(
    "package,executables",
    [
        (
            "dori_control",
            (
                "drive_controller_node",
                "bldc_command_bridge_node",
                "wheel_odometry_node",
                "tf_authority_check",
                "transform_manager_node",
                "transform_controller_node",
                "fake_joint_states_node",
                "joystick_input_node",
                "keyboard_input_node",
                "virtual_vlm_input_node",
            ),
        ),
        ("dori_hardware", ("dxl_driver_node", "dxl_bridge_node", "dxl_state_publisher_node", *IMU_NODES)),
        ("dori_diagnostics", ("error_manager_node",)),
        ("dori_navigation", ("nav2_adapter", "named_goal_adapter", "web_viewer.py")),
    ],
)
def test_installed_executables(package, executables):
    directory = Path(get_package_prefix(package)) / "lib" / package
    for executable in executables:
        path = directory / executable
        assert path.is_file() and os.access(path, os.X_OK), path


def test_behavior_tree_executor_links_humble_v3():
    executable = Path(get_package_prefix("dori_bt")) / "lib/dori_bt/dori_tree_executor"
    result = subprocess.run(
        ["ldd", str(executable)], capture_output=True, text=True, check=True
    )
    assert "libbehaviortree_cpp_v3.so" in result.stdout, result.stdout
    assert "libbehaviortree_cpp.so" not in result.stdout, result.stdout
    assert "not found" not in result.stdout, result.stdout


@pytest.mark.parametrize("name", IMU_NODES)
def test_installed_imu_entrypoint_imports_without_opening_devices(name, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Packaging checks must not open hardware or initialize ROS"
        )

    import rclpy
    import serial

    monkeypatch.setattr(serial, "Serial", forbidden)
    monkeypatch.setattr(rclpy, "init", forbidden)
    module = importlib.import_module("dori_hardware." + name)
    assert Path(module.__file__).is_relative_to(ROOT / "ros2_ws/install/dori_hardware")
    path = Path(get_package_prefix("dori_hardware")) / "lib/dori_hardware" / name
    namespace = runpy.run_path(str(path), run_name="packaging_import_only")
    assert namespace["main"] is module.main


def test_message_and_action_type_support():
    from dori_msgs.msg import (
        MitCommand,
        CommandFeedback,
        SystemError,
        TransformStep,
        TransformStepResult,
    )
    from dori_msgs.action import Navigate, NavigateNamed, Speak, LLMQuery

    for message in (
        MitCommand(motor_id=1, v_des=2.5),
        CommandFeedback(),
        SystemError(),
        TransformStep(),
        TransformStepResult(),
        Navigate.Goal(),
        NavigateNamed.Goal(),
        Speak.Goal(),
        LLMQuery.Goal(),
    ):
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
            condition = getattr(action, "condition", None)
            if condition is not None and not condition.evaluate(context):
                continue
            if isinstance(action, Node):
                pkg = resolve(context, action.node_package)
                exe = resolve(context, action.node_executable)
                path = Path(get_package_prefix(pkg)) / "lib" / pkg / exe
                assert path.is_file() and os.access(path, os.X_OK), path
                parameters = evaluate_parameters(context, action._Node__parameters)
                for parameter in parameters:
                    if isinstance(parameter, (str, Path)):
                        assert Path(parameter).is_file(), parameter
                    elif (
                        isinstance(parameter, dict) and "robot_description" in parameter
                    ):
                        assert (
                            ET.fromstring(parameter["robot_description"]).tag == "robot"
                        )
                nodes.append((pkg, exe, parameters))
            elif isinstance(action, ExecuteProcess):
                command = [resolve(context, item) for item in action.cmd]
                assert shutil.which(command[0]), command
                for argument in command[1:]:
                    if argument.endswith((".py", ".yaml", ".xml")):
                        assert Path(argument).is_file(), argument
            elif isinstance(action, LaunchDescription):
                expand(action.entities)
            elif isinstance(
                action,
                (
                    DeclareLaunchArgument,
                    SetLaunchConfiguration,
                    SetEnvironmentVariable,
                    IncludeLaunchDescription,
                    OpaqueFunction,
                    GroupAction,
                    PushLaunchConfigurations,
                    PopLaunchConfigurations,
                    PushEnvironment,
                    PopEnvironment,
                ),
            ):
                expand(action.execute(context) or [])
            elif isinstance(action, RegisterEventHandler):
                # Process-exit handlers only apply to a running launch service.
                continue
            else:
                raise AssertionError(f"Unreviewed launch action: {type(action)}")

    path = Path(get_package_share_directory(package)) / "launch" / filename
    # SetEnvironmentVariable mutates os.environ on Humble; introspection must
    # not change the provider seen by later tests or launch descriptions.
    with patch.dict(os.environ):
        expand([PythonLaunchDescriptionSource(str(path)).get_launch_description(context)])
    return nodes


@pytest.fixture
def no_process_launch(monkeypatch, tmp_path):
    # Device readiness is exercised separately without hardware. Here only
    # expand the descriptions and verify installed programs/parameters.
    monkeypatch.setattr("dori_hardware.startup_checks.validate_devices", lambda *args, **kwargs: None)
    monkeypatch.setattr("dori_hardware.serial_identity.resolve_dxl_port",
                        lambda port, **kwargs: "/dev/test-dynamixel" if port == "auto" else port)
    monkeypatch.setenv("DORI_INTERNAL_TOKEN", "test-only-internal-secret-32-characters")
    # Launch preflight validates SDK/config only; it never contacts Azure.
    monkeypatch.delenv("DORI_VISITOR_STT", raising=False)
    monkeypatch.setenv("AZURE_SPEECH_KEY", "test-only-not-a-service-key")
    monkeypatch.setenv("AZURE_SPEECH_REGION", "koreacentral")
    monkeypatch.setenv("AZURE_SPEECH_TIER", "F0")
    monkeypatch.setenv("DORI_AZURE_ENV_FILE", str(tmp_path / "absent.env"))
    def forbidden(*args, **kwargs):
        raise AssertionError("A launch test attempted to execute a process")

    monkeypatch.setattr(Node, "execute", forbidden)
    monkeypatch.setattr(ExecuteProcess, "execute", forbidden)
    # Isolate generated Cartographer config and launch-added import directories.
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    monkeypatch.setattr(sys, "path", list(sys.path))


@pytest.mark.parametrize(
    "package,filename,options",
    [
        ("dori_hardware", "actuation.launch.py", {}),
        ("dori_hardware", "body_control.launch.py", {"use_joystick": "true"}),
        ("dori_hardware", "hardware.launch.py", {}),
        ("dori_control", "odometry.launch.py", {}),
        ("dori_mapping", "lidar_odometry.launch.py", {}),
        ("dori_mapping", "lidar_only_cartographer.launch.py", {}),
        ("dori_navigation", "nav2.launch.py", {}),
        ("dori_navigation", "navigation_adapters.launch.py", {}),
        ("dori_hri", "voice.launch.py", {}),
        ("dori_bt", "interaction.launch.py", {}),
        ("dori_perception", "perception.launch.py", {}),
        ("dori_bringup", "bringup.launch.py", {}),
    ],
)
def test_installed_launch_paths(no_process_launch, package, filename, options):
    nodes = inspect_launch(
        package,
        filename,
        {"map": str(ROOT / "maps/live_navigation_20261023_1938.yaml"), **options},
    )
    assert nodes


@pytest.mark.parametrize("package,filenames", [
    ("dori_bringup", {"bringup", "robot", "desktop"}),
    ("dori_hardware", {"hardware", "body_control", "actuation"}),
    ("dori_navigation", {"nav2", "navigation_adapters"}),
    ("dori_hri", {"voice"}),
    ("dori_bt", {"interaction"}),
    ("dori_perception", {"perception"}),
])
def test_launch_ownership_and_no_stale_installed_entrypoints(package, filenames):
    expected = {name + ".launch.py" for name in filenames}
    for root in (ROOT / "ros2_ws/src" / package, Path(get_package_share_directory(package))):
        paths = list((root / "launch").glob("*.launch.py"))
        assert {path.name for path in paths} == expected, root
        assert all(path.is_file() for path in paths), "Dangling installed launch symlink"
    if package == "dori_navigation":
        config = Path(get_package_share_directory(package)) / "config"
        assert (config / "nav2_params.yaml").is_file()
        retired = config / "nav2_real.yaml"
        assert not retired.exists() and not retired.is_symlink()


def test_standalone_interaction_defaults_to_visitor_mode(no_process_launch):
    nodes = inspect_launch("dori_bt", "interaction.launch.py", {})
    parameters = next(params for _, exe, params in nodes if exe == "dori_tree_executor")
    assert any(isinstance(p, dict) and p.get("visitor_mode") is True for p in parameters)


@pytest.mark.parametrize("hardware", [True, False])
def test_bringup_is_visitor_ready_with_robot_by_default(no_process_launch, hardware):
    options = {"map": str(ROOT / "maps/live_navigation_20261023_1938.yaml")} if hardware else {"dori_mode": "desktop"}
    nodes = inspect_launch("dori_bringup", "bringup.launch.py", options)
    executables = {exe for _, exe, _ in nodes}
    assert {"llm_node", "tts_node", "dori_tree_executor", "rosbridge_websocket"} <= executables
    assert "stt_node" not in executables
    if hardware:
        assert {"ros2_control_node", "nav2_adapter", "named_goal_adapter", "sllidar_node", "dxl_driver_node", "depth_camera_node", "person_detection_node", "readiness_monitor"} <= executables
    else:
        assert not {"ros2_control_node", "nav2_adapter", "sllidar_node", "dxl_driver_node"} & executables
    bt_params = next(params for _, exe, params in nodes if exe == "dori_tree_executor")
    assert any(params.get("visitor_mode") is True for params in bt_params)
    retired = Path(get_package_share_directory("dori_bringup")) / "launch/bringup_dev.launch.py"
    assert not retired.exists() and not retired.is_symlink()
    retired = retired.with_name("hardware.launch.py")
    assert not retired.exists() and not retired.is_symlink()


def test_profile_yaml_and_cli_reach_installed_nodes(no_process_launch, tmp_path):
    config = tmp_path / "robot.yaml"
    config.write_text(f"""common:
  llm_model: from-yaml
robot:
  map: {ROOT / 'maps/live_navigation_20261023_1938.yaml'}
  front_serial: 'camera-123'
  dxl_baudrate: 115200
""")
    nodes = inspect_launch("dori_bringup", "bringup.launch.py", {
        "config_file": str(config), "llm_model": "from-cli",
    })
    for executable, key, expected in (
        ("llm_node", "model_name", "from-cli"),
        ("depth_camera_node", "serial_number", "camera-123"),
        ("dxl_driver_node", "baudrate", 115200),
    ):
        parameters = next(params for _, exe, params in nodes if exe == executable)
        assert any(isinstance(p, dict) and p.get(key) == expected for p in parameters)


def test_profiles_share_voice_hri_and_perception_parameters(no_process_launch):
    common = {"map": str(ROOT / "maps/live_navigation_20261023_1938.yaml"),
              "enable_perception": "true", "require_user_tracking": "true"}
    selected = {"llm_node", "tts_node", "dori_tree_executor", "person_detection_node", "depth_camera_node"}
    def parameters(mode):
        nodes = inspect_launch("dori_bringup", "bringup.launch.py", {**common, "dori_mode": mode})
        assert not {"gesture_recognition_node", "facial_expression_node", "landmark_detection_node"} & {exe for _, exe, _ in nodes}
        return {exe: params for _, exe, params in nodes if exe in selected}
    assert parameters("robot") == parameters("desktop")


def test_full_robot_resolves_and_excludes_inherited_virtual_inputs(no_process_launch):
    nodes = inspect_launch(
        "dori_bringup",
        "robot.launch.py",
        {
            "map": str(ROOT / "maps/live_navigation_20261023_1938.yaml"),
            "use_input_nodes": "true",
            "visitor_mode": "false",
        },
    )
    executables = [exe for _, exe, _ in nodes]
    assert executables.count("drive_controller_node") == 1
    assert executables.count("mode_manager_node") == 1
    assert executables.count("dxl_driver_node") == 1
    assert "read_write_node" not in executables
    assert set(IMU_NODES) <= set(executables)
    assert not {
        "virtual_vlm_input_node",
        "keyboard_input_node",
        "joystick_input_node",
        "wheel_odometry_node",
    } & set(executables)
    assert {
        "rosbridge_websocket",
        "rosapi_node",
        "nav2_adapter",
        "named_goal_adapter",
        "web_viewer.py",
        "dori_tree_executor",
        "stt_node",
        "tts_node",
    } <= set(executables)


def test_physical_device_parameters_reach_every_driver(no_process_launch):
    nodes = inspect_launch("dori_bringup", "bringup.launch.py", {
        "dori_mode": "robot",
        "map": str(ROOT / "maps/live_navigation_20261023_1938.yaml"),
        "can_interface": "can7",
        "dxl_port": "/dev/serial/by-id/test-dxl",
        "dxl_baudrate": "115200",
        "imu_port": "/dev/serial/by-id/test-imu",
        "lidar_port": "/dev/test-lidar",
    })
    def parameters(executable):
        return next(params for _, exe, params in nodes if exe == executable)
    for exe, key, expected in (
        ("dxl_driver_node", "device_name", "/dev/serial/by-id/test-dxl"),
        ("dxl_driver_node", "baudrate", 115200),
        ("imu_node", "port", "/dev/serial/by-id/test-imu"),
        ("sllidar_node", "serial_port", "/dev/test-lidar"),
        ("motor4_servo_node", "can_interface", "can7"),
    ):
        assert any(isinstance(p, dict) and p.get(key) == expected for p in parameters(exe)), exe
    description = next(p["robot_description"] for p in parameters("ros2_control_node")
                       if isinstance(p, dict) and "robot_description" in p)
    assert ET.fromstring(description).find("ros2_control/hardware/param[@name='can_interface']").text == "can7"


def test_discovered_port_reaches_driver_without_a_second_probe(no_process_launch, monkeypatch):
    def validate(can_interface, serial_ports, **kwargs):
        ports = dict(serial_ports)
        if ports["Dynamixel"] == "auto":
            ports["Dynamixel"] = "/dev/serial/by-id/usb-CP2102N-servos"
        return ports
    def resolved_only(port, **kwargs):
        assert port != "auto", "The parent must forward the identified device"
        return port
    monkeypatch.setattr("dori_hardware.startup_checks.validate_devices", validate)
    monkeypatch.setattr("dori_hardware.serial_identity.resolve_dxl_port", resolved_only)
    nodes = inspect_launch("dori_bringup", "bringup.launch.py", {
        "map": str(ROOT / "maps/live_navigation_20261023_1938.yaml"),
    })
    params = next(params for _, exe, params in nodes if exe == "dxl_driver_node")
    assert any(isinstance(p, dict) and p.get("device_name") ==
               "/dev/serial/by-id/usb-CP2102N-servos" for p in params)


def test_navigation_does_not_inherit_lidar_odometry_parameters(no_process_launch):
    import yaml
    nodes = inspect_launch("dori_bringup", "bringup.launch.py", {
        "map": str(ROOT / "maps/live_navigation_20261023_1938.yaml"),
    })
    for _, executable, parameters in nodes:
        if executable == "lifecycle_manager":
            config = next(p for p in parameters if isinstance(p, dict) and "node_names" in p)
            assert config["autostart"] == ("controller_server" not in config["node_names"])
        if executable not in {"amcl", "controller_server", "lidar_odometry_node.py"}:
            continue
        paths = [Path(p) for p in parameters if isinstance(p, (str, Path))]
        if executable == "lidar_odometry_node.py":
            assert [p.name for p in paths] == ["lidar_odometry.yaml"]
        else:
            assert [p.name for p in paths] == ["nav2_params.yaml"]
            config = yaml.safe_load(paths[0].read_text())[executable]["ros__parameters"]
            if executable == "amcl":
                assert config["base_frame_id"] == "base_link"
            else:
                assert config["FollowPath"]["plugin"] == (
                    "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController")


def test_dashboard_and_native_plugin_assets_installed():
    nav = Path(get_package_prefix("dori_navigation"))
    assert (nav / "lib/librelaxed_heading_planner.so").is_file()
    assert (nav / "share/dori_navigation/static/index.html").is_file()
    web = Path(get_package_share_directory("dori_dashboard")) / "web"
    assert (web / "index.html").is_file()
    assert list((web / "assets").glob("*.js"))

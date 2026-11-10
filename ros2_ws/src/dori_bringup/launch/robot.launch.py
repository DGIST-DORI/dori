"""Complete robot: drivers, navigation, required front perception, HRI and apps."""

from pathlib import Path
import sys
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    OpaqueFunction,
    RegisterEventHandler,
    EmitEvent,
)
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from dori_hardware.startup_checks import validate_devices
from dori_bringup.configuration import arguments
from dori_bringup.launch_support import include, prepare, services


def setup(context):
    value = lambda n: LaunchConfiguration(n).perform(context)
    environment = prepare(context)
    nav_share = Path(get_package_share_directory("dori_navigation"))
    sys.path.insert(0, str(nav_share / "scripts"))
    from navigation_contract import validate_map

    validate_map(value("map"))
    if value("namespace") != "/dori":
        raise ValueError(
            "Physical robot uses /dori and global hardware topics; isolate robots by ROS_DOMAIN_ID"
        )
    if value("named_goals_file") and not Path(value("named_goals_file")).is_file():
        raise ValueError("named_goals_file does not exist")
    resolved = validate_devices(value("can_interface"), {
        "Dynamixel": value("dxl_port"), "IMU": value("imu_port"),
        "LiDAR": value("lidar_port"),
    }, can_wait_timeout=value("can_wait_timeout"), dxl_baudrate=value("dxl_baudrate"))
    if resolved:
        context.launch_configurations["dxl_port"] = resolved["Dynamixel"]

    def failed(event, _context):
        # Teardown exits must not start another shutdown sequence.
        if _context.is_shutdown:
            return []
        name = event.action.process_details.get("name", "")
        if event.returncode == 0 and ("spawner" in name or "rviz" in name):
            return []
        return [
            EmitEvent(
                event=Shutdown(
                    reason=f"{name} exited ({event.returncode}); stopping robot session"
                )
            )
        ]

    actions = [
        RegisterEventHandler(OnProcessExit(on_exit=failed)),
        include(
            "dori_hardware",
            "hardware.launch.py",
            {k: value(k) for k in ("use_joystick", "can_interface", "can_wait_timeout", "dxl_port", "dxl_baudrate", "imu_port")},
        ),
        include(
            "sllidar_ros2",
            "sllidar_c1_launch.py",
            {
                "serial_port": value("lidar_port"),
                "serial_baudrate": "460800",
                "frame_id": "laser",
                "scan_mode": "Standard",
            },
        ),
        include(
            "dori_mapping",
            "lidar_odometry.launch.py",
            {
                "laser_" + axis: value("laser_" + axis)
                for axis in ("x", "y", "z", "roll", "pitch", "yaw")
            },
        ),
        include(
            "dori_navigation",
            "nav2.launch.py",
            {
                "map": value("map"),
                "named_goals_file": value("named_goals_file"),
                "publish_laser_tf": "false",
                "rviz": value("rviz"),
            },
        ),
        Node(
            package="dori_navigation",
            executable="web_viewer.py",
            name="dori_web_viewer",
            arguments=[
                "--mode",
                "navigation",
                "--goals-file",
                value("named_goals_file"),
                "--host",
                value("web_host"),
                "--port",
                "8080",
                "--user-port",
                "7070",
            ],
            output="screen",
        ),
    ]
    actions = actions[:1] + environment + actions[1:] + services(context, robot=True)
    actions.append(Node(
        package="dori_bringup", executable="readiness_monitor", name="bringup_readiness",
        namespace=value("namespace"), output="screen",
        parameters=[{
            "startup_timeout": float(value("startup_timeout")),
            "enable_hri": value("enable_hri") == "true",
            "enable_dashboard": value("enable_dashboard") == "true",
            "enable_stt": value("enable_stt") == "true",
            "visitor_mode": value("visitor_mode") == "true",
            "enable_rear_camera": value("enable_rear_camera") == "true",
        }],
    ))
    return actions


def generate_launch_description():
    return LaunchDescription(arguments("robot", fixed=True) + [OpaqueFunction(function=setup)])

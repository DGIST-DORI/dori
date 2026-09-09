from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, GroupAction, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    root = Path(__file__).resolve().parents[1]
    nav2 = Path(get_package_share_directory("nav2_bringup"))
    use_sim_time = LaunchConfiguration("use_sim_time")
    params = LaunchConfiguration("params_file")
    map_yaml = LaunchConfiguration("map")

    return LaunchDescription([
        DeclareLaunchArgument("map", default_value=str(root / "maps" / "isaac_saved_map.yaml")),
        DeclareLaunchArgument("params_file", default_value=str(root / "config" / "nav2_jetson.yaml")),
        DeclareLaunchArgument("points_file", default_value=str(root / "maps" / "isaac_saved_map.points.csv")),
        DeclareLaunchArgument("use_sim_time", default_value="false"),
        DeclareLaunchArgument("start_lidar_driver", default_value="true"),
        DeclareLaunchArgument("restamp_scan", default_value="true"),
        DeclareLaunchArgument("serial_port", default_value="/dev/slamtec_c1"),
        DeclareLaunchArgument("laser_frame", default_value="laser"),
        DeclareLaunchArgument("publish_laser_tf", default_value="true"),
        DeclareLaunchArgument("no_robot_workload", default_value="true"),
        DeclareLaunchArgument("laser_x", default_value="0.0"),
        DeclareLaunchArgument("laser_y", default_value="0.0"),
        DeclareLaunchArgument("laser_z", default_value="0.0"),
        DeclareLaunchArgument("laser_yaw", default_value="0.0"),
        Node(
            package="sllidar_ros2", executable="sllidar_node", name="sllidar_node",
            condition=IfCondition(LaunchConfiguration("start_lidar_driver")), output="screen",
            respawn=True, respawn_delay=2.0,
            parameters=[{
                "channel_type": "serial",
                "serial_port": LaunchConfiguration("serial_port"),
                "serial_baudrate": 460800,
                "frame_id": LaunchConfiguration("laser_frame"),
                "inverted": False,
                "angle_compensate": True,
                "scan_mode": "Standard",
            }],
            remappings=[("scan", "/scan_raw"), ("/scan", "/scan_raw")],
        ),
        ExecuteProcess(
            cmd=[
                "/usr/bin/python3", str(root / "scripts" / "restamp_scan.py"),
                "--input", "/scan_raw", "--output", "/scan",
            ], output="screen", condition=IfCondition(LaunchConfiguration("restamp_scan")),
        ),
        Node(
            package="tf2_ros", executable="static_transform_publisher",
            name="base_link_to_laser", condition=IfCondition(LaunchConfiguration("publish_laser_tf")),
            arguments=[
                "--x", LaunchConfiguration("laser_x"), "--y", LaunchConfiguration("laser_y"),
                "--z", LaunchConfiguration("laser_z"), "--yaw", LaunchConfiguration("laser_yaw"),
                "--pitch", "0", "--roll", "0", "--frame-id", "base_link",
                "--child-frame-id", LaunchConfiguration("laser_frame"),
            ], output="screen",
        ),
        GroupAction(actions=[
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(str(nav2 / "launch" / "localization_launch.py")),
                launch_arguments={
                    "map": map_yaml, "params_file": params, "use_sim_time": use_sim_time,
                    "autostart": "true", "use_composition": "False", "use_respawn": "False",
                }.items(),
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(str(nav2 / "launch" / "navigation_launch.py")),
                launch_arguments={
                    "params_file": params, "use_sim_time": use_sim_time,
                    "autostart": "true", "use_composition": "False", "use_respawn": "False",
                }.items(),
            ),
        ]),
        ExecuteProcess(
            cmd=[
                "/usr/bin/python3", str(root / "scripts" / "named_goal_bridge.py"),
                "--ros-args", "-p", ["points_file:=", LaunchConfiguration("points_file")],
                "-p", ["use_sim_time:=", use_sim_time],
            ], output="screen",
        ),
        ExecuteProcess(
            cmd=[
                "/usr/bin/python3", str(root / "scripts" / "no_robot_workload.py"),
                "--points-file", LaunchConfiguration("points_file"),
            ], output="screen", condition=IfCondition(LaunchConfiguration("no_robot_workload")),
        ),
    ])

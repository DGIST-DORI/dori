from __future__ import annotations

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description() -> LaunchDescription:
    root_dir = Path(__file__).resolve().parents[1]
    rviz_default = str(root_dir / "config" / "isaac_mapping.rviz")
    slam_params_default = str(root_dir / "config" / "slam_toolbox_isaac.yaml")
    odom_bridge_script = str(root_dir / "scripts" / "odom_to_tf.py")
    scan_restamp_script = str(root_dir / "scripts" / "restamp_scan.py")
    keyboard_drive_script = str(root_dir / "keyboard_Drive" / "unified.py")

    use_sim_time = LaunchConfiguration("use_sim_time")
    slam_params_file = LaunchConfiguration("slam_params_file")
    odom_topic = LaunchConfiguration("odom_topic")
    output_odom_topic = LaunchConfiguration("output_odom_topic")
    rviz = LaunchConfiguration("rviz")
    rviz_config = LaunchConfiguration("rviz_config")
    keyboard = LaunchConfiguration("keyboard")
    image_topic = LaunchConfiguration("image_topic")
    cmd_vel_topic = LaunchConfiguration("cmd_vel_topic")
    input_scan_topic = LaunchConfiguration("input_scan_topic")
    output_scan_topic = LaunchConfiguration("output_scan_topic")

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="true"),
            DeclareLaunchArgument("slam_params_file", default_value=slam_params_default),
            DeclareLaunchArgument("odom_topic", default_value="/odom"),
            DeclareLaunchArgument("output_odom_topic", default_value="/odom_restamped"),
            DeclareLaunchArgument("rviz", default_value="false"),
            DeclareLaunchArgument("rviz_config", default_value=rviz_default),
            DeclareLaunchArgument("keyboard", default_value="false"),
            DeclareLaunchArgument("image_topic", default_value="/rgb"),
            DeclareLaunchArgument("cmd_vel_topic", default_value="/cmd_vel"),
            DeclareLaunchArgument("input_scan_topic", default_value="/scan"),
            DeclareLaunchArgument("output_scan_topic", default_value="/scan_restamped"),
            Node(
                package="tf2_ros",
                executable="static_transform_publisher",
                name="base_link_to_base_scan_tf",
                arguments=[
                    "--x",
                    "0",
                    "--y",
                    "0",
                    "--z",
                    "0",
                    "--roll",
                    "0",
                    "--pitch",
                    "0",
                    "--yaw",
                    "0",
                    "--frame-id",
                    "base_link",
                    "--child-frame-id",
                    "base_scan",
                ],
                parameters=[{"use_sim_time": use_sim_time}],
                remappings=[("/tf_static", "/tf_static_slam")],
                output="screen",
            ),
            ExecuteProcess(
                cmd=[
                    "/usr/bin/python3",
                    odom_bridge_script,
                    "--ros-args",
                    "-r",
                    "/tf:=/tf_slam",
                    "-p",
                    ["odom_topic:=", odom_topic],
                    "-p",
                    ["output_odom_topic:=", output_odom_topic],
                    "-p",
                    ["restamp_to_clock:=true"],
                    "-p",
                    ["use_sim_time:=", use_sim_time],
                ],
                output="screen",
            ),
            ExecuteProcess(
                cmd=[
                    "/usr/bin/python3",
                    scan_restamp_script,
                    "--ros-args",
                    "-p",
                    ["input_scan_topic:=", input_scan_topic],
                    "-p",
                    ["output_scan_topic:=", output_scan_topic],
                    "-p",
                    ["use_sim_time:=", use_sim_time],
                ],
                output="screen",
            ),
            Node(
                package="slam_toolbox",
                executable="async_slam_toolbox_node",
                name="slam_toolbox",
                parameters=[slam_params_file, {"use_sim_time": use_sim_time}],
                remappings=[
                    ("/tf", "/tf_slam"),
                    ("/tf_static", "/tf_static_slam"),
                ],
                output="screen",
            ),
            Node(
                package="rviz2",
                executable="rviz2",
                name="rviz2",
                arguments=["-d", rviz_config],
                parameters=[{"use_sim_time": use_sim_time}],
                remappings=[
                    ("/tf", "/tf_slam"),
                    ("/tf_static", "/tf_static_slam"),
                ],
                output="screen",
                condition=IfCondition(rviz),
            ),
            ExecuteProcess(
                cmd=[
                    "/usr/bin/python3",
                    keyboard_drive_script,
                    "--image_topic",
                    image_topic,
                    "--cmd_vel_topic",
                    cmd_vel_topic,
                ],
                output="screen",
                condition=IfCondition(keyboard),
            ),
        ]
    )

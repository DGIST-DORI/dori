"""Executable HRI behavior tree using ROS 2 Humble's Nav2-compatible BT.CPP v3."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    defaults = dict(
        namespace="/dori",
        visitor_mode="true",
        tree_xml_file="",
        require_user_tracking="false",
        require_mic_return="false",
    )
    return LaunchDescription(
        [DeclareLaunchArgument(k, default_value=v) for k, v in defaults.items()]
        + [
            Node(
                package="dori_bt",
                executable="dori_tree_executor",
                name="dori_tree_executor",
                namespace=LaunchConfiguration("namespace"),
                output="screen",
                parameters=[
                    {k: LaunchConfiguration(k) for k in defaults if k != "namespace"}
                ],
            ),
            Node(
                package="dori_hri",
                executable="emotion_publisher_node",
                name="emotion_publisher_node",
                namespace=LaunchConfiguration("namespace"),
                output="screen",
            ),
        ]
    )

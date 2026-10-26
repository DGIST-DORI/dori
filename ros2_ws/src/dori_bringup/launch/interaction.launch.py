"""Launch the BehaviorTree interaction coordinator in the DORI namespace."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('namespace', default_value='/dori'),
        DeclareLaunchArgument('tree_xml_file', default_value=''),
        Node(
            package='dori_bt',
            executable='dori_tree_executor',
            name='dori_tree_executor',
            namespace=LaunchConfiguration('namespace'),
            output='screen',
            parameters=[{'tree_xml_file': LaunchConfiguration('tree_xml_file')}],
        ),
    ])

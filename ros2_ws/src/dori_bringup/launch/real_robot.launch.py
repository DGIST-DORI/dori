"""Single real-robot profile: hardware, localization, Nav2 and DORI actions."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def _include(package, filename, arguments):
    return IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory(package), 'launch', filename)
        ),
        launch_arguments=arguments.items(),
    )


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument('namespace', default_value='/dori'),
        DeclareLaunchArgument('map', description='Absolute path to a Nav2 map YAML'),
        DeclareLaunchArgument('named_goals_file', default_value=''),
        DeclareLaunchArgument('use_joystick', default_value='false'),
        DeclareLaunchArgument('rviz', default_value='false'),
    ]
    return LaunchDescription(arguments + [
        _include('dori_hardware', 'real_hardware.launch.py', {
            'use_joystick': LaunchConfiguration('use_joystick'),
        }),
        _include('dori_mapping', 'lidar_odometry.launch.py', {}),
        _include('robot_navigation', 'real_nav2.launch.py', {
            'map': LaunchConfiguration('map'),
            'publish_laser_tf': 'false',
            'rviz': LaunchConfiguration('rviz'),
        }),
        _include('dori_navigation', 'real_navigation.launch.py', {
            'namespace': LaunchConfiguration('namespace'),
            'nav2_action_name': '/dori/internal/navigate_to_pose',
            'named_goals_file': LaunchConfiguration('named_goals_file'),
        }),
    ])

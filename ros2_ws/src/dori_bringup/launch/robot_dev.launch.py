"""
Development assembly launch for DORI.

Composes the production robot launch and optionally adds developer tools
such as dashboard/rosbridge.

Usage:
  ros2 launch dori_bringup robot_dev.launch.py
  ros2 launch dori_bringup robot_dev.launch.py enable_dashboard:=false
"""

import os
import logging

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    dori_bringup_dir = get_package_share_directory('dori_bringup')

    args = [
        DeclareLaunchArgument(
            'enable_dashboard',
            default_value='true',
            description='Launch rosbridge + web dashboard (development only)',
        ),
        DeclareLaunchArgument(
            'namespace',
            default_value='/dori',
            description='Base namespace for all DORI topics',
        ),
    ]

    robot_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(dori_bringup_dir, 'launch', 'robot.launch.py')
        ),
        launch_arguments={
            'namespace': LaunchConfiguration('namespace'),
        }.items(),
    )

    launch_list = [
        *args,
        robot_launch,
    ]

    try:
        dori_dashboard_dir = get_package_share_directory('dori_dashboard')
        launch_list.append(
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(dori_dashboard_dir, 'launch', 'dashboard.launch.py')
                ),
                condition=IfCondition(LaunchConfiguration('enable_dashboard')),
            )
        )
    except Exception as exc:
        # Dashboard is an optional development tool; skip it if the package is unavailable.
        logging.getLogger(__name__).warning(
            "Failed to include optional dashboard launch: %s", exc
        )

    return LaunchDescription(launch_list)

"""Start DORI's physical actuators, sensors and safety supervisor."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('use_joystick', default_value='false'),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(
                get_package_share_directory('dori_hardware'),
                'launch', 'system_real_with_imu.launch.py')),
            launch_arguments={
                'use_joystick': LaunchConfiguration('use_joystick'),
                # The legacy virtual VLM keyboard publishes normalized AUTO
                # inputs directly; it must never compete with the TTA bridge.
                'use_input_nodes': 'false',
                'use_wheel_odometry': 'false',
                'odom_publish_tf': 'false',
            }.items(),
        ),
    ])

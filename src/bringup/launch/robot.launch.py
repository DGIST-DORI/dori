"""
Top-level launch file for DORI campus guide robot.
Includes all subsystems: camera/HRI perception, voice interface, navigation.

Usage:
  ros2 launch bringup robot.launch.py
  ros2 launch bringup robot.launch.py use_external_llm:=true
  ros2 launch bringup robot.launch.py enable_navigation:=false  # SW dev without HW
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    bringup_dir = get_package_share_directory('bringup')

    # Launch arguments

    # Camera / HRI perception
    args_hri = [
        DeclareLaunchArgument('person_model',      default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_model',    default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_db',       default_value='landmark_db.json'),
        DeclareLaunchArgument('device',            default_value='cuda'),
        DeclareLaunchArgument('visualize',         default_value='false'),
        DeclareLaunchArgument('enable_landmark',   default_value='true'),
        DeclareLaunchArgument('enable_gesture',    default_value='true'),
        DeclareLaunchArgument('enable_expression', default_value='true'),
    ]

    # Voice interface
    args_voice = [
        DeclareLaunchArgument('use_external_llm',  default_value='false'),
        DeclareLaunchArgument('whisper_model',      default_value='small'),
        DeclareLaunchArgument('wake_word',          default_value='porcupine'),
        DeclareLaunchArgument('tts_engine',         default_value='gtts'),
        DeclareLaunchArgument('tts_language',       default_value='ko'),
    ]

    # Navigation
    args_nav = [
        DeclareLaunchArgument('max_speed',          default_value='0.5'),
        DeclareLaunchArgument('enable_navigation',  default_value='true'),
    ]

    args_system = [
        DeclareLaunchArgument('enable_system_monitor', default_value='true'),
        DeclareLaunchArgument('system_metrics_interval_sec', default_value='1.0'),
    ]

    # Sub-launch files

    hri_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_dir, 'launch', 'hri.launch.py')
        ),
        launch_arguments={
            'person_model':      LaunchConfiguration('person_model'),
            'landmark_model':    LaunchConfiguration('landmark_model'),
            'landmark_db':       LaunchConfiguration('landmark_db'),
            'device':            LaunchConfiguration('device'),
            'visualize':         LaunchConfiguration('visualize'),
            'enable_landmark':   LaunchConfiguration('enable_landmark'),
            'enable_gesture':    LaunchConfiguration('enable_gesture'),
            'enable_expression': LaunchConfiguration('enable_expression'),
        }.items(),
    )

    voice_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_dir, 'launch', 'voice_interface.launch.py')
        ),
        launch_arguments={
            'use_external_llm': LaunchConfiguration('use_external_llm'),
            'whisper_model':    LaunchConfiguration('whisper_model'),
            'wake_word':        LaunchConfiguration('wake_word'),
            'tts_engine':       LaunchConfiguration('tts_engine'),
            'tts_language':     LaunchConfiguration('tts_language'),
        }.items(),
    )

    # Navigation launch — optional, skipped if navigation_pkg not installed
    nav_launch = None
    try:
        nav_pkg_dir = get_package_share_directory('navigation_pkg')
        nav_launch = IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(nav_pkg_dir, 'launch', 'navigation.launch.py')
            ),
            launch_arguments={
                'max_speed': LaunchConfiguration('max_speed'),
            }.items(),
            condition=IfCondition(LaunchConfiguration('enable_navigation')),
        )
    except Exception:
        pass  # navigation_pkg not yet available

    # Assembly

    launch_list = [
        *args_hri,
        *args_voice,
        *args_nav,
        hri_launch,
        voice_launch,
    ]

    if nav_launch:
        launch_list.append(nav_launch)

    launch_list.extend([
        *args_system,
        Node(
            package='system_monitor_pkg',
            executable='system_monitor_node',
            name='system_monitor_node',
            output='screen',
            parameters=[{
                'interval_sec': LaunchConfiguration('system_metrics_interval_sec'),
                'publish_topic': '/dori/system/metrics',
            }],
            condition=IfCondition(LaunchConfiguration('enable_system_monitor')),
        ),
    ])

    return LaunchDescription(launch_list)

"""
hri_manager.launch.py
Launches only the HRI Manager node in isolation.
Use this for testing the HRI state machine without perception nodes.

Nodes started:
  hri_manager_node  (hri_pkg)  - central HRI state machine

Topic flow (expected counterparts):
  /dori/stt/wake_word_detected  (Bool)   ← stt_node or manual publish
  /dori/stt/result              (String) ← stt_node or manual publish
  /dori/hri/manager_state       (String) → dashboard / rosbridge
  /dori/llm/query               (String) → llm_node
  /dori/tts/text                (String) → tts_node
  /dori/tts/done                (Bool)   ← tts_node
  /dori/hri/set_follow_mode     (Bool)   → navigation

Usage:
  ros2 launch hri_pkg hri_manager.launch.py
  ros2 launch hri_pkg hri_manager.launch.py idle_timeout_sec:=30.0
  ros2 launch hri_pkg hri_manager.launch.py greeting_text:='안녕하세요!'
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    args = [
        DeclareLaunchArgument(
            'greeting_text',
            default_value='안녕하세요! 저는 캠퍼스 안내 로봇 도리입니다. 어디로 안내해드릴까요?',
            description='Greeting message spoken when wake word is detected',
        ),
        DeclareLaunchArgument(
            'idle_timeout_sec',
            default_value='10.0',
            description='Seconds to wait in LISTENING before returning to IDLE',
        ),
    ]

    hri_manager_node = Node(
        package='hri_pkg',
        executable='hri_manager_node',
        name='hri_manager_node',
        output='screen',
        parameters=[{
            'greeting_text':    LaunchConfiguration('greeting_text'),
            'idle_timeout_sec': LaunchConfiguration('idle_timeout_sec'),
        }],
    )

    log_start = LogInfo(msg=[
        '\n==============================\n'
        ' HRI Manager launch\n'
        '  idle_timeout: ', LaunchConfiguration('idle_timeout_sec'), 's\n'
        '==============================',
    ])

    return LaunchDescription([
        *args,
        log_start,
        hri_manager_node,
    ])

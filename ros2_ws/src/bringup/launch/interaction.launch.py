"""
Interaction stack launch (state machine/coordinator only).
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _topic(ns, suffix: str):
    return [ns, suffix]


def generate_launch_description():
    dori_ns = LaunchConfiguration('namespace')
    args = [
        DeclareLaunchArgument(
            'idle_timeout_sec',
            default_value='10.0',
            description='Seconds to wait for STT input before returning to IDLE',
        ),
        DeclareLaunchArgument(
            'greeting_text',
            default_value='안녕하세요! 저는 캠퍼스 안내 로봇 도리입니다. 어디로 안내해드릴까요?',
            description='Greeting spoken when wake word is detected',
        ),
        DeclareLaunchArgument(
            'wake_debounce_sec',
            default_value='1.5',
            description='Debounce interval for wake-word events',
        ),
        DeclareLaunchArgument('namespace', default_value='/dori'),
    ]

    hri_manager_node = Node(
        package='interaction_pkg',
        executable='hri_manager_node',
        name='hri_manager_node',
        output='screen',
        parameters=[{
            'idle_timeout_sec': LaunchConfiguration('idle_timeout_sec'),
            'greeting_text': LaunchConfiguration('greeting_text'),
            'wake_debounce_sec': LaunchConfiguration('wake_debounce_sec'),
            'topics.wake_word_sub': _topic(dori_ns, '/stt/wake_word_detected'),
            'topics.stt_result_sub': _topic(dori_ns, '/stt/result'),
            'topics.tracking_state_sub': _topic(dori_ns, '/hri/tracking_state'),
            'topics.gesture_command_sub': _topic(dori_ns, '/hri/gesture_command'),
            'topics.expression_command_sub': _topic(dori_ns, '/hri/expression_command'),
            'topics.landmark_context_sub': _topic(dori_ns, '/landmark/context'),
            'topics.tts_done_sub': _topic(dori_ns, '/tts/done'),
            'services.follow_mode_service': _topic(dori_ns, '/hri/set_follow_mode'),
            'topics.manager_state_pub': _topic(dori_ns, '/hri/manager_state'),
            'topics.llm_query_pub': _topic(dori_ns, '/llm/query'),
            'topics.tts_text_pub': _topic(dori_ns, '/tts/text'),
            'topics.nav_command_pub': _topic(dori_ns, '/nav/command'),
        }],
    )

    return LaunchDescription([
        *args,
        hri_manager_node,
    ])

"""
Voice interface + HRI Manager.

Nodes started:
  hri_manager_node   (hri_pkg)  - central HRI state machine
  stt_node           (stt_pkg)  - wake word + speech transcription
  llm_node           (llm_pkg)  - intent classification + RAG + LLM
  tts_node           (tts_pkg)  - text-to-speech playback

Topic flow:
  microphone
    → stt_node → /dori/stt/wake_word_detected → hri_manager_node
    → stt_node → /dori/stt/result             → hri_manager_node
    → hri_manager_node → /dori/llm/query      → llm_node
    → llm_node  → /dori/llm/response          → tts_node
    → hri_manager_node → /dori/tts/text       → tts_node  (direct speech)
    → tts_node  → /dori/tts/speaking          → stt_node  (mute while speaking)
    → tts_node  → /dori/tts/done              → hri_manager_node
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    # Resolve knowledge file path from llm_pkg if available
    try:
        llm_pkg_dir = get_package_share_directory('llm_pkg')
        knowledge_file_default = os.path.join(
            llm_pkg_dir, 'config', 'campus_knowledge.json'
        )
    except Exception:
        knowledge_file_default = ''

    # Arguments
    args = [
        DeclareLaunchArgument('use_external_llm',
            default_value='false',
            description='Use external LLM API (OpenAI / Anthropic)'),
        DeclareLaunchArgument('knowledge_file',
            default_value=knowledge_file_default,
            description='Path to campus_knowledge.json'),
        DeclareLaunchArgument('whisper_model',
            default_value='small',
            description='Whisper model size: tiny / base / small / medium / large'),
        DeclareLaunchArgument('wake_word',
            default_value='porcupine',
            description='Porcupine wake word keyword'),
        DeclareLaunchArgument('tts_engine',
            default_value='gtts',
            description='TTS engine: gtts (online) or pyttsx3 (offline)'),
        DeclareLaunchArgument('tts_language',
            default_value='ko',
            description='TTS output language'),
        DeclareLaunchArgument('idle_timeout_sec',
            default_value='10.0',
            description='Seconds to wait for STT input before returning to IDLE'),
    ]

    # HRI Manager Node
    # Central state machine — bridges perception ↔ voice interface
    hri_manager_node = Node(
        package='hri_pkg',
        executable='hri_manager_node',
        name='hri_manager_node',
        output='screen',
        parameters=[{
            'idle_timeout_sec': LaunchConfiguration('idle_timeout_sec'),
            'greeting_text':    '안녕하세요! 저는 캠퍼스 안내 로봇 도리입니다. 어디로 안내해드릴까요?',
        }],
    )

    # STT Node
    stt_node = Node(
        package='stt_pkg',
        executable='stt_node',
        name='stt_node',
        output='screen',
        parameters=[{
            'wake_word':        LaunchConfiguration('wake_word'),
            'whisper_model':    LaunchConfiguration('whisper_model'),
            'whisper_device':   'cpu',
            'vad_threshold':    0.5,
            'silence_duration': 1.2,
        }],
    )

    # LLM Node
    llm_node = Node(
        package='llm_pkg',
        executable='llm_node',
        name='llm_node',
        output='screen',
        parameters=[{
            'knowledge_file':   '/path/to/campus_knowledge.json', # TODO
            'rag_index_dir':    '/path/to/rag_index', # TODO
            'use_external_llm': True,
            'model_name':       'gemini-2.5-flash',
            'rag_top_k':        3,
        }]
    )

    # TTS Node
    tts_node = Node(
        package='tts_pkg',
        executable='tts_node',
        name='tts_node',
        output='screen',
        parameters=[{
            'tts_engine':  LaunchConfiguration('tts_engine'),
            'language':    LaunchConfiguration('tts_language'),
            'speech_rate': 150,
            'volume':      0.9,
        }],
    )

    return LaunchDescription([
        *args,
        hri_manager_node,
        stt_node,
        llm_node,
        tts_node,
    ])

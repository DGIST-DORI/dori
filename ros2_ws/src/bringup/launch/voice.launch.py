"""
Voice stack launch (stt/llm/tts only).
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node


def _topic(ns, suffix: str):
    return [ns, suffix]


def generate_launch_description():
    dori_ns = LaunchConfiguration('namespace')
    args = [
        DeclareLaunchArgument('use_external_llm', default_value='false'),
        DeclareLaunchArgument('knowledge_file', default_value=''),
        DeclareLaunchArgument('rag_index_dir', default_value=''),
        DeclareLaunchArgument('llm_model', default_value='gemini-2.5-flash'),
        DeclareLaunchArgument('rag_top_k', default_value='3'),
        DeclareLaunchArgument('whisper_model', default_value='small'),
        DeclareLaunchArgument('whisper_device', default_value='cpu'),
        DeclareLaunchArgument('wake_word', default_value='porcupine'),
        DeclareLaunchArgument('wake_word_paths', default_value=''),
        DeclareLaunchArgument('stt_audio_input_mode', default_value='microphone'),
        DeclareLaunchArgument('tts_engine', default_value='gtts'),
        DeclareLaunchArgument('tts_language', default_value='ko'),
        DeclareLaunchArgument('sfx_base_path', default_value=''),
        DeclareLaunchArgument(
            'tts_playback_mode',
            default_value=EnvironmentVariable('DORI_TTS_PLAYBACK_MODE', default_value='local_and_publish'),
        ),
        DeclareLaunchArgument('namespace', default_value='/dori'),
    ]

    stt_node = Node(
        package='stt_pkg',
        executable='stt_node',
        name='stt_node',
        output='screen',
        parameters=[{
            'wake_word': LaunchConfiguration('wake_word'),
            'wake_word_paths': LaunchConfiguration('wake_word_paths'),
            'whisper_model': LaunchConfiguration('whisper_model'),
            'whisper_device': LaunchConfiguration('whisper_device'),
            'vad_threshold': 0.5,
            'silence_duration': 1.2,
            'audio_input_mode': LaunchConfiguration('stt_audio_input_mode'),
            'topics.wake_word_pub': _topic(dori_ns, '/stt/wake_word_detected'),
            'topics.result_pub': _topic(dori_ns, '/stt/result'),
            'topics.tts_speaking_sub': _topic(dori_ns, '/tts/speaking'),
            # Dashboard mic path is fixed to canonical STT input for both Robot/Sim profiles.
            'topics.audio_input_sub': _topic(dori_ns, '/stt/audio_input'),
        }],
    )

    llm_node = Node(
        package='llm_pkg',
        executable='llm_node',
        name='llm_node',
        output='screen',
        parameters=[{
            'knowledge_file': LaunchConfiguration('knowledge_file'),
            'rag_index_dir': LaunchConfiguration('rag_index_dir'),
            'use_external_llm': LaunchConfiguration('use_external_llm'),
            'model_name': LaunchConfiguration('llm_model'),
            'rag_top_k': LaunchConfiguration('rag_top_k'),
            'topics.query_sub': _topic(dori_ns, '/llm/query'),
            'topics.response_pub': _topic(dori_ns, '/llm/response'),
            'actions.navigate': _topic(dori_ns, '/nav/navigate_to'),
        }],
    )

    tts_node = Node(
        package='tts_pkg',
        executable='tts_node',
        name='tts_node',
        output='screen',
        parameters=[{
            'tts_engine': LaunchConfiguration('tts_engine'),
            'language': LaunchConfiguration('tts_language'),
            'speech_rate': 150,
            'volume': 0.9,
            'topics.speaking_pub': _topic(dori_ns, '/tts/speaking'),
            'topics.done_pub': _topic(dori_ns, '/tts/done'),
            'topics.llm_response_sub': _topic(dori_ns, '/llm/response'),
            'topics.tts_text_sub': _topic(dori_ns, '/tts/text'),
            'topics.audio_cue_sub': _topic(dori_ns, '/hri/audio_cue'),
            'sfx.base_path': LaunchConfiguration('sfx_base_path'),
            'playback_mode': LaunchConfiguration('tts_playback_mode'),
        }],
    )

    return LaunchDescription([
        *args,
        stt_node,
        llm_node,
        tts_node,
    ])

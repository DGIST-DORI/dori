"""
Top-level assembly launch for DORI.

This launch only assembles subsystem launch files:
  - perception.launch.py   (camera/vision)
  - interaction.launch.py  (state machine/coordinator)
  - voice.launch.py        (stt/llm/tts)
  - (optional) navigation.launch.py
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.logging import get_logger
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration

try:
    from dori_llm.paths import is_repo_root
except Exception:
    def is_repo_root(parent):
        has_readme = (parent / 'README.md').exists()
        has_ros2_src = (parent / 'ros2_ws' / 'src').is_dir()
        has_git = (parent / '.git').exists()
        return has_readme and (has_ros2_src or has_git)


def _resolve_path(share_relative: str, pkg_name: str, data_relative: str) -> str:
    """Resolve an asset path from installed share first, then repository root."""
    import pathlib

    try:
        share_path = pathlib.Path(get_package_share_directory(pkg_name)) / share_relative
        if share_path.exists():
            return str(share_path)
    except Exception:
        pass

    this_file = pathlib.Path(__file__).resolve()
    for parent in this_file.parents:
        if is_repo_root(parent):
            candidate = parent / data_relative
            if candidate.exists():
                return str(candidate)
            break

    return ''


def generate_launch_description():
    bringup_dir = get_package_share_directory('bringup')

    knowledge_file_default = _resolve_path(
        share_relative='config/campus_knowledge.json',
        pkg_name='dori_llm',
        data_relative='data/campus/indexed/campus_knowledge.json',
    )
    rag_index_dir_default = _resolve_path(
        share_relative='indexed',
        pkg_name='dori_llm',
        data_relative='data/campus/indexed',
    )
    wake_word_model_default = _resolve_path(
        share_relative='models/doridori_ko_linux_v4_0_0.ppn',
        pkg_name='stt_pkg',
        data_relative='ros2_ws/src/stt_pkg/models/doridori_ko_linux_v4_0_0.ppn',
    )

    args = [
        # Perception module boundary args
        DeclareLaunchArgument('person_model', default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_model', default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_db', default_value='landmark_db.json'),
        DeclareLaunchArgument('device', default_value='cuda'),
        DeclareLaunchArgument('visualize', default_value='false'),
        DeclareLaunchArgument('enable_landmark', default_value='true'),
        DeclareLaunchArgument('enable_gesture', default_value='true'),
        DeclareLaunchArgument('enable_expression', default_value='true'),
        DeclareLaunchArgument('camera_fps', default_value='15'),
        DeclareLaunchArgument('camera_width', default_value='640'),
        DeclareLaunchArgument('camera_height', default_value='480'),

        # Interaction module boundary args
        DeclareLaunchArgument('idle_timeout_sec', default_value='10.0'),
        DeclareLaunchArgument(
            'greeting_text',
            default_value='안녕하세요! 저는 캠퍼스 안내 로봇 도리입니다. 어디로 안내해드릴까요?',
        ),

        # Voice module boundary args
        DeclareLaunchArgument('use_external_llm', default_value='false'),
        DeclareLaunchArgument('knowledge_file', default_value=knowledge_file_default),
        DeclareLaunchArgument('rag_index_dir', default_value=rag_index_dir_default),
        DeclareLaunchArgument('llm_model', default_value='gemini-2.5-flash'),
        DeclareLaunchArgument('rag_top_k', default_value='3'),
        DeclareLaunchArgument('whisper_model', default_value='small'),
        DeclareLaunchArgument('whisper_device', default_value='cpu'),
        DeclareLaunchArgument('wake_word', default_value='porcupine'),
        DeclareLaunchArgument('wake_word_paths', default_value=wake_word_model_default),
        DeclareLaunchArgument('tts_engine', default_value='gtts'),
        DeclareLaunchArgument('tts_language', default_value='ko'),
        DeclareLaunchArgument('namespace', default_value='/dori'),

        # Optional subsystem toggles
        DeclareLaunchArgument('enable_navigation', default_value='true'),
    ]

    perception_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_dir, 'launch', 'perception.launch.py')
        ),
        launch_arguments={
            'person_model': LaunchConfiguration('person_model'),
            'landmark_model': LaunchConfiguration('landmark_model'),
            'landmark_db': LaunchConfiguration('landmark_db'),
            'device': LaunchConfiguration('device'),
            'visualize': LaunchConfiguration('visualize'),
            'enable_landmark': LaunchConfiguration('enable_landmark'),
            'enable_gesture': LaunchConfiguration('enable_gesture'),
            'enable_expression': LaunchConfiguration('enable_expression'),
            'camera_fps': LaunchConfiguration('camera_fps'),
            'camera_width': LaunchConfiguration('camera_width'),
            'camera_height': LaunchConfiguration('camera_height'),
            'namespace': LaunchConfiguration('namespace'),
        }.items(),
    )

    interaction_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_dir, 'launch', 'interaction.launch.py')
        ),
        launch_arguments={
            'idle_timeout_sec': LaunchConfiguration('idle_timeout_sec'),
            'greeting_text': LaunchConfiguration('greeting_text'),
            'namespace': LaunchConfiguration('namespace'),
        }.items(),
    )

    voice_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_dir, 'launch', 'voice.launch.py')
        ),
        launch_arguments={
            'use_external_llm': LaunchConfiguration('use_external_llm'),
            'knowledge_file': LaunchConfiguration('knowledge_file'),
            'rag_index_dir': LaunchConfiguration('rag_index_dir'),
            'llm_model': LaunchConfiguration('llm_model'),
            'rag_top_k': LaunchConfiguration('rag_top_k'),
            'whisper_model': LaunchConfiguration('whisper_model'),
            'whisper_device': LaunchConfiguration('whisper_device'),
            'wake_word': LaunchConfiguration('wake_word'),
            'wake_word_paths': LaunchConfiguration('wake_word_paths'),
            'tts_engine': LaunchConfiguration('tts_engine'),
            'tts_language': LaunchConfiguration('tts_language'),
            'namespace': LaunchConfiguration('namespace'),
        }.items(),
    )

    launch_list = [
        *args,
        perception_launch,
        interaction_launch,
        voice_launch,
    ]

    try:
        nav_pkg_dir = get_package_share_directory('dori_navigation')
        launch_list.append(
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(nav_pkg_dir, 'launch', 'navigation.launch.py')
                ),
                condition=IfCondition(LaunchConfiguration('enable_navigation')),
            )
        )
    except Exception as exc:
        get_logger().warning(
            f"dori_navigation not available; skipping navigation.launch.py: {exc}"
        )

    return LaunchDescription(launch_list)

from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    
    bringup_dir = get_package_share_directory('campus_robot_bringup')
    
    # Launch arguments
    use_external_llm_arg = DeclareLaunchArgument(
        'use_external_llm',
        default_value='false',
        description='Use external LLM API ()' # TODO
    )
    
    whisper_model_arg = DeclareLaunchArgument(
        'whisper_model',
        default_value='small',
        description='Whisper model size (tiny/base/small/medium/large)'
    )
    
    wake_word_arg = DeclareLaunchArgument(
        'wake_word',
        default_value='porcupine', # TODO
        description='Wake word for voice activation'
    )
    
    tts_engine_arg = DeclareLaunchArgument(
        'tts_engine',
        default_value='gtts',
        description='TTS engine (gtts/pyttsx3)'
    )
    
    tts_language_arg = DeclareLaunchArgument(
        'tts_language',
        default_value='ko',
        description='TTS language (ko/en)'
    )
    
    # Include voice interface launch
    voice_interface_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(bringup_dir, 'launch', 'voice_interface.launch.py')
        ),
        launch_arguments={
            'use_external_llm': LaunchConfiguration('use_external_llm'),
            'whisper_model': LaunchConfiguration('whisper_model'),
            'wake_word': LaunchConfiguration('wake_word'),
            'tts_engine': LaunchConfiguration('tts_engine'),
            'tts_language': LaunchConfiguration('tts_language'),
        }.items()
    )
    
    # TODO: Navigation launch
    # navigation_launch = IncludeLaunchDescription(...)
    
    return LaunchDescription([
        # Arguments
        use_external_llm_arg,
        whisper_model_arg,
        wake_word_arg,
        tts_engine_arg,
        tts_language_arg,
        
        # Launch files
        voice_interface_launch,
        # navigation_launch,
    ])

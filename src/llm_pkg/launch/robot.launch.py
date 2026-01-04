from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
import os

def generate_launch_description():

    # Package directories
    try:
        stt_pkg_dir = get_package_share_directory('stt_pkg')
    except:
        stt_pkg_dir = None
        
    try:
        llm_pkg_dir = get_package_share_directory('llm_pkg')
    except:
        llm_pkg_dir = None
    
    try:
        tts_pkg_dir = get_package_share_directory('tts_pkg')
    except:
        tts_pkg_dir = None
    
    # Configuration file path
    knowledge_file_default = os.path.join(
        llm_pkg_dir, 'config', 'campus_knowledge.json'
    )
    
    # Launch arguments
    use_external_llm_arg = DeclareLaunchArgument(
        'use_external_llm',
        default_value='false',
        description='Use external LLM API ()' # TODO
    )
    
    knowledge_file_arg = DeclareLaunchArgument(
        'knowledge_file',
        default_value=knowledge_file_default,
        description='Path to campus knowledge JSON file'
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

    # STT Node
    stt_node = Node(
        package='stt_pkg',
        executable='stt_node',
        name='stt_node',
        output='screen',
        parameters=[{
            'wake_word': LaunchConfiguration('wake_word'),
            'whisper_model': LaunchConfiguration('whisper_model'),
            'whisper_device': 'cpu',  # or 'cuda' for GPU
            'vad_threshold': 0.5,
            'silence_duration': 1.2
        }],
        remappings=[
            ('/stt/text', '/stt/text'),
            ('/robot/speaking', '/robot/speaking')
        ]
    )
    
    # LLM Node
    llm_node = Node(
        package='llm_pkg',
        executable='llm_node',
        name='llm_node',
        output='screen',
        parameters=[{
            'knowledge_file': LaunchConfiguration('knowledge_file'),
            'use_external_llm': LaunchConfiguration('use_external_llm'),
            'model_name': 'gpt-3.5-turbo',
            'confidence_threshold': 0.4
        }],
        remappings=[
            ('/stt/text', '/stt/text'),
            ('/llm/response', '/llm/response'),
            ('/navigation/destination', '/navigation/destination'),
            ('/robot/speaking', '/robot/speaking')
        ]
    )
    
    # TTS Node
    tts_node = Node(
        package='tts_pkg',
        executable='tts_node',
        name='tts_node',
        output='screen',
        parameters=[{
            'tts_engine': LaunchConfiguration('tts_engine'),
            'language': LaunchConfiguration('tts_language'),
            'speech_rate': 150,
            'volume': 0.9
        }],
        remappings=[
            ('/llm/response', '/llm/response'),
            ('/robot/speaking', '/robot/speaking')
        ]
    )
    
    return LaunchDescription([
        # Arguments
        use_external_llm_arg,
        knowledge_file_arg,
        whisper_model_arg,
        wake_word_arg,
        tts_engine_arg,
        tts_language_arg,
        
        # Nodes
        stt_node,
        llm_node,
        tts_node
    ])

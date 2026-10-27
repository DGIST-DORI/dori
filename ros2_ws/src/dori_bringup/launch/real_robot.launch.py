"""Single-owner hardware, LiDAR, Nav2, HRI and web deployment profile."""
from pathlib import Path
import sys
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction, RegisterEventHandler, EmitEvent
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def include(package, filename, arguments):
    return IncludeLaunchDescription(PythonLaunchDescriptionSource(str(
        Path(get_package_share_directory(package))/'launch'/filename)), launch_arguments=arguments.items())


def setup(context):
    value = lambda n: LaunchConfiguration(n).perform(context)
    nav_share = Path(get_package_share_directory('robot_navigation'))
    sys.path.insert(0, str(nav_share/'scripts'))
    from navigation_contract import validate_map
    validate_map(value('map'))
    if value('namespace') != '/dori':
        raise ValueError('Physical robot uses /dori and global hardware topics; isolate robots by ROS_DOMAIN_ID')
    if value('named_goals_file') and not Path(value('named_goals_file')).is_file():
        raise ValueError('named_goals_file does not exist')
    def failed(event, _context):
        name = event.action.process_details.get('name', '')
        if event.returncode == 0 and ('spawner' in name or 'rviz' in name):
            return []
        return [EmitEvent(event=Shutdown(reason=f'{name} exited ({event.returncode}); stopping robot session'))]
    actions = [RegisterEventHandler(OnProcessExit(on_exit=failed)),
        include('dori_hardware', 'real_hardware.launch.py', {'use_joystick': value('use_joystick')}),
        include('sllidar_ros2', 'sllidar_c1_launch.py', {'serial_port': value('lidar_port'),
            'serial_baudrate': '460800', 'frame_id': 'laser', 'scan_mode': 'Standard'}),
        include('robot_mapping', 'lidar_odometry.launch.py', {
            'laser_'+axis: value('laser_'+axis) for axis in ('x','y','z','roll','pitch','yaw')}),
        include('robot_navigation', 'real_nav2.launch.py', {'map': value('map'),
            'named_goals_file': value('named_goals_file'), 'publish_laser_tf': 'false', 'rviz': value('rviz')}),
        Node(package='robot_navigation', executable='web_viewer.py', name='dori_web_viewer',
             arguments=['--mode','navigation','--goals-file',value('named_goals_file'),
                        '--host',value('web_host'),'--port','8080','--user-port','7070'], output='screen'),
    ]
    if value('enable_hri') == 'true':
        actions += [include('dori_bringup','voice.launch.py',{k:value(k) for k in (
            'namespace','enable_stt','stt_audio_input_mode','wake_word','whisper_model','whisper_device',
            'tts_playback_mode','tts_engine','use_external_llm','llm_model','knowledge_file','rag_index_dir')}),
            include('dori_bringup','interaction.launch.py',{k:value(k) for k in (
                'namespace','require_user_tracking','require_mic_return','tree_xml_file')})]
    if value('enable_perception') == 'true':
        actions.append(include('dori_bringup','perception.launch.py',{'namespace':value('namespace'),
            'device':value('perception_device'), 'enable_gesture':value('enable_gesture'),
            'enable_expression':value('enable_expression'), 'enable_landmark':value('enable_landmark'),
            **{k:value(k) for k in ('front_serial','rear_serial','enable_rear_camera',
                'hand_model_path','face_model_path','person_model','landmark_model','use_cpp_depth_camera')}}))
    if value('enable_dashboard') == 'true':
        actions.append(include('dori_dashboard','dashboard.launch.py',{}))
    return actions


def generate_launch_description():
    defaults = dict(namespace='/dori', named_goals_file='', use_joystick='false', rviz='false',
        lidar_port='/dev/slamtec_c1', enable_hri='true', enable_stt='true',
        stt_audio_input_mode='microphone', wake_word='hey_mycroft', whisper_model='small', whisper_device='cpu',
        tts_playback_mode='local_only', tts_engine='gtts', use_external_llm='false', llm_model='gemini-2.5-flash',
        knowledge_file='', rag_index_dir='', enable_perception='false', perception_device='cpu',
        enable_gesture='false', enable_expression='false', enable_landmark='false',
        front_serial='', rear_serial='', enable_rear_camera='false', use_cpp_depth_camera='true',
        hand_model_path='', face_model_path='', person_model='yolov8n.pt', landmark_model='yolov8n.pt',
        require_user_tracking='false', require_mic_return='false', tree_xml_file='',
        enable_dashboard='true', web_host='0.0.0.0')
    defaults.update({'laser_'+a: '3.141592653589793' if a=='yaw' else '0.0'
                     for a in ('x','y','z','roll','pitch','yaw')})
    return LaunchDescription([DeclareLaunchArgument('map')]+
        [DeclareLaunchArgument(k, default_value=v) for k,v in defaults.items()]+[OpaqueFunction(function=setup)])

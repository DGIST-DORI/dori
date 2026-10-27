"""Select a complete physical robot or a desktop HRI session, with one owner per node."""
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def setup(context):
    value = lambda n: LaunchConfiguration(n).perform(context)
    share = Path(get_package_share_directory('dori_bringup'))/'launch'
    def include(filename, params):
        return IncludeLaunchDescription(PythonLaunchDescriptionSource(str(share/filename)), launch_arguments=params.items())
    if value('dori_mode') == 'real':
        return [include('real_robot.launch.py', {'map':value('real_map'),
            'named_goals_file':value('real_named_goals_file'), 'use_joystick':value('real_use_joystick'),
            **{k:value(k) for k in ('namespace','enable_stt','enable_dashboard','enable_perception',
                                   'tts_playback_mode','wake_word','whisper_model','require_user_tracking')}})]
    if value('dori_mode') not in ('sim', 'desktop'):
        raise ValueError('dori_mode must be real, desktop or sim (desktop alias)')
    actions = [include('voice.launch.py',{k:value(k) for k in (
        'namespace','enable_stt','tts_playback_mode','wake_word','whisper_model')}),
        include('interaction.launch.py', {'namespace':value('namespace')})]
    if value('enable_perception') == 'true':
        actions.append(include('perception.launch.py',{'namespace':value('namespace')}))
    if value('enable_dashboard') == 'true':
        dashboard = Path(get_package_share_directory('dori_dashboard'))/'launch/dashboard.launch.py'
        actions.append(IncludeLaunchDescription(PythonLaunchDescriptionSource(str(dashboard))))
    return actions


def generate_launch_description():
    defaults = dict(dori_mode='desktop', namespace='/dori', real_map='', real_named_goals_file='',
        real_use_joystick='false', enable_stt='true', enable_dashboard='false', enable_perception='false',
        tts_playback_mode='local_only', wake_word='hey_mycroft', whisper_model='small', require_user_tracking='false')
    return LaunchDescription([DeclareLaunchArgument(k, default_value=v) for k,v in defaults.items()] +
                             [OpaqueFunction(function=setup)])

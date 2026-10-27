"""2D mapping with the shared LiDAR odometry frame as the external reference."""
import os
import tempfile
import time
from pathlib import Path
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _render_cartographer_config(context):
    root = Path(__file__).resolve().parents[1]
    value = lambda key: LaunchConfiguration(key).perform(context)
    use_odom = value('use_odometry').lower() == 'true'
    external = use_odom or value('external_odom_tf').lower() == 'true'
    replacements = {
        '__TRACKING_FRAME__': value('base_frame'), '__USE_IMU__': 'false',
        '__PUBLISHED_FRAME__': value('odom_frame' if external else 'base_frame'),
        '__PROVIDE_ODOM_FRAME__': str(not external).lower(),
        '__USE_ODOMETRY__': str(use_odom).lower(),
    }
    for key in ['map_frame', 'base_frame', 'odom_frame', 'min_range', 'max_range',
                'missing_data_ray_length', 'submap_range_data']:
        replacements['__'+key.upper()+'__'] = value(key)
    replacements['__NUM_SUBDIVISIONS__'] = value('num_subdivisions_per_laser_scan')
    text = (root/'config/cartographer_2d_lidar.lua.in').read_text()
    for key, replacement in replacements.items():
        text = text.replace(key, replacement)
    directory = Path(tempfile.gettempdir())/'lidar_only_slam'
    directory.mkdir(exist_ok=True)
    config = directory/f'cartographer_2d_lidar_{os.getpid()}_{time.time_ns()}.lua'
    config.write_text(text)
    sim = {'use_sim_time': value('use_sim_time').lower() == 'true'}
    extrinsic = []
    for axis in ['x', 'y', 'z', 'roll', 'pitch', 'yaw']:
        extrinsic += ['--'+axis, value('laser_'+axis)]
    return [
        Node(package='sllidar_ros2', executable='sllidar_node', name='sllidar_node',
             parameters=[dict(channel_type='serial', serial_port=value('serial_port'),
                 serial_baudrate=int(value('serial_baudrate')), frame_id=value('laser_frame'),
                 inverted=value('lidar_inverted').lower()=='true',
                 angle_compensate=value('angle_compensate').lower()=='true', scan_mode=value('scan_mode'))],
             remappings=[('scan', value('scan_topic'))], output='screen',
             condition=IfCondition(LaunchConfiguration('start_lidar_driver'))),
        Node(package='tf2_ros', executable='static_transform_publisher', name='base_to_laser_tf',
             arguments=extrinsic+['--frame-id', value('base_frame'), '--child-frame-id', value('laser_frame')],
             parameters=[sim], condition=IfCondition(LaunchConfiguration('publish_laser_tf'))),
        Node(package='cartographer_ros', executable='cartographer_node', name='cartographer_node',
             arguments=['-configuration_directory', str(directory), '-configuration_basename', config.name],
             parameters=[sim], remappings=[('scan', value('scan_topic')), ('odom', value('odom_topic'))], output='screen'),
        Node(package='cartographer_ros', executable='cartographer_occupancy_grid_node',
             name='cartographer_occupancy_grid_node', parameters=[sim, {'resolution': float(value('map_resolution'))}], output='screen'),
        Node(package='rviz2', executable='rviz2', name='rviz2', arguments=['-d', value('rviz_config')],
             parameters=[sim], condition=IfCondition(LaunchConfiguration('rviz'))),
    ]


def generate_launch_description():
    root = Path(__file__).resolve().parents[1]
    defaults = dict(use_sim_time='false', use_odometry='true', external_odom_tf='true',
        odom_topic='/odom', scan_topic='/scan', start_lidar_driver='false',
        serial_port='/dev/slamtec_c1', serial_baudrate='460800', scan_mode='Standard',
        lidar_inverted='false', angle_compensate='true', map_frame='map', odom_frame='odom',
        base_frame='base_link', laser_frame='laser', publish_laser_tf='false',
        laser_x='0.0', laser_y='0.0', laser_z='0.0', laser_roll='0.0', laser_pitch='0.0',
        laser_yaw='3.141592653589793', rviz='false', rviz_config=str(root/'config/lidar_only_mapping.rviz'),
        map_resolution='0.05', min_range='0.10', max_range='16.0', missing_data_ray_length='16.5',
        submap_range_data='35', num_subdivisions_per_laser_scan='1')
    return LaunchDescription([DeclareLaunchArgument(k, default_value=v) for k, v in defaults.items()]
                             + [OpaqueFunction(function=_render_cartographer_config)])

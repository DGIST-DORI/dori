"""One shared odometry + laser extrinsic source for mapping and navigation."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch_ros.actions import Node
from launch.substitutions import LaunchConfiguration
from launch_ros.parameter_descriptions import ParameterValue
from ament_index_python.packages import get_package_share_directory
from pathlib import Path


def generate_launch_description():
    root = Path(get_package_share_directory('dori_mapping'))
    args = [DeclareLaunchArgument('use_sim_time', default_value='false'),
            DeclareLaunchArgument('params_file', default_value=str(root/'config/lidar_odometry.yaml'))]
    axes = ['x', 'y', 'z', 'roll', 'pitch', 'yaw']
    args += [DeclareLaunchArgument('laser_'+a, default_value='3.141592653589793' if a=='yaw' else '0.0') for a in axes]
    extrinsic = []
    for axis in axes:
        extrinsic += ['--'+axis, LaunchConfiguration('laser_'+axis)]
    return LaunchDescription(args + [
        Node(package='tf2_ros', executable='static_transform_publisher', name='base_to_laser_tf',
             arguments=extrinsic+['--frame-id', 'base_link', '--child-frame-id', 'laser']),
        Node(package='dori_mapping', executable='lidar_odometry_node.py', output='screen',
             parameters=[LaunchConfiguration('params_file'),
                         {'use_sim_time': ParameterValue(LaunchConfiguration('use_sim_time'), value_type=bool)}])])

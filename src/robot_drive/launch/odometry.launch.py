from launch_ros.parameter_descriptions import ParameterValue
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from pathlib import Path


def generate_launch_description():
    config = str(Path(get_package_share_directory('robot_drive')) / 'config/odometry.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=config),
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('publish_tf', default_value='true'),
        DeclareLaunchArgument('odom_scale', default_value='1.0'),
        Node(package='robot_drive', executable='wheel_odometry_node', output='screen',
             parameters=[LaunchConfiguration('params_file'), str(Path(get_package_share_directory('robot_drive')) / 'config/kinematics.yaml'), {
                 'use_sim_time': LaunchConfiguration('use_sim_time'),
                 'publish_tf': LaunchConfiguration('publish_tf'),
                 'odom_scale': ParameterValue(LaunchConfiguration('odom_scale'), value_type=float),
             }]),
    ])

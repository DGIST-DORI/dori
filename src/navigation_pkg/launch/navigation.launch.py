from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    
    # Launch arguments
    max_speed_arg = DeclareLaunchArgument(
        'max_speed',
        default_value='0.5',
        description='Maximum linear speed (m/s)'
    )
    
    max_angular_speed_arg = DeclareLaunchArgument(
        'max_angular_speed',
        default_value='1.0',
        description='Maximum angular speed (rad/s)'
    )
    
    goal_tolerance_arg = DeclareLaunchArgument(
        'goal_tolerance',
        default_value='0.2',
        description='Goal tolerance distance (m)'
    )
    
    obstacle_distance_arg = DeclareLaunchArgument(
        'obstacle_distance',
        default_value='0.5',
        description='Obstacle detection distance (m)'
    )
    
    # Navigator Node
    navigator_node = Node(
        package='navigation_pkg',
        executable='navigator_node',
        name='navigator_node',
        output='screen',
        parameters=[{
            'max_speed': LaunchConfiguration('max_speed'),
            'max_angular_speed': LaunchConfiguration('max_angular_speed'),
            'goal_tolerance': LaunchConfiguration('goal_tolerance'),
            'obstacle_distance': LaunchConfiguration('obstacle_distance'),
            'control_frequency': 20.0
        }],
        remappings=[
            ('/navigation/destination', '/navigation/destination'),
            ('/cmd_vel', '/cmd_vel'),
            ('/odom', '/odom'),
            ('/scan', '/scan'),
            ('/map', '/map')
        ]
    )
    
    return LaunchDescription([
        # Arguments
        max_speed_arg,
        max_angular_speed_arg,
        goal_tolerance_arg,
        obstacle_distance_arg,
        
        # Nodes
        navigator_node
    ])

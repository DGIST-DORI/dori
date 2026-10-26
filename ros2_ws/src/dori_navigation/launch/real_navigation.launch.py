"""Launch the DORI/Nav2 action boundary for a real robot profile."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('namespace', default_value='/dori'),
        DeclareLaunchArgument('nav2_action_name', default_value='/dori/internal/navigate_to_pose'),
        DeclareLaunchArgument('named_goals_file', default_value=''),
        Node(
            package='dori_navigation',
            executable='nav2_adapter',
            name='nav2_adapter',
            output='screen',
            parameters=[{
                'action_name': [LaunchConfiguration('namespace'), '/nav/navigate_to'],
                'nav2_action_name': LaunchConfiguration('nav2_action_name'),
                'required_frame': 'map',
            }],
        ),
        Node(
            package='dori_navigation',
            executable='named_goal_adapter',
            name='named_goal_adapter',
            output='screen',
            parameters=[{
                'goals_file': LaunchConfiguration('named_goals_file'),
                'goal_topic': [LaunchConfiguration('namespace'), '/internal/named_goal'],
                'action_name': [LaunchConfiguration('namespace'), '/nav/navigate_to'],
            }],
        ),
    ])

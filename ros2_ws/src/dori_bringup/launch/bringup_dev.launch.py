"""Desktop or physical robot with the integrated dashboard enabled."""
from pathlib import Path
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('enable_dashboard', default_value='true'),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(str(
            Path(get_package_share_directory('dori_bringup'))/'launch/bringup.launch.py')),
            launch_arguments={'enable_dashboard':LaunchConfiguration('enable_dashboard')}.items())])

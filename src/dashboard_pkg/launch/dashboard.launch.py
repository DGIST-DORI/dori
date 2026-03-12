from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    pkg_dir = get_package_share_directory('dashboard_pkg')
    web_dir = os.path.join(pkg_dir, 'web')

    if not os.path.isdir(web_dir):
        raise FileNotFoundError(
            'dashboard_pkg web assets not found. Expected directory: '
            f"'{web_dir}'. Build the frontend (web/dist) before installing and launching dashboard_pkg."
        )

    return LaunchDescription([
        # rosbridge WebSocket server node
        Node(
            package='rosbridge_server',
            executable='rosbridge_websocket',
            name='rosbridge_websocket',
            parameters=[{
                'port': 9090,
            }]
        ),

        # React web serving by simple HTTP server
        ExecuteProcess(
            cmd=['python3', '-m', 'http.server', '3000'],
            cwd=web_dir,
            output='screen'
        )
    ])

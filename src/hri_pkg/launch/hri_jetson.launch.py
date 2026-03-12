"""
- used FP16 TensorRT model
- lower res/FPS
- disabled viz

how to use:
  ros2 launch hri_pkg hri_jetson.launch.py
  ros2 launch hri_pkg hri_jetson.launch.py person_model:=best_person.engine landmark_model:=best_landmark.engine
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    args = [
        DeclareLaunchArgument('person_model', default_value='yolov8n.pt',
                              description='Person detection model (.pt or .engine)'),
        DeclareLaunchArgument('landmark_model', default_value='yolov8n.pt',
                              description='Landmark detection model (.pt or .engine)'),
        DeclareLaunchArgument('landmark_db', default_value='landmark_db.json'),
        DeclareLaunchArgument('enable_landmark', default_value='true'),
        DeclareLaunchArgument('visualize', default_value='false'),
    ]

    person_model   = LaunchConfiguration('person_model')
    landmark_model = LaunchConfiguration('landmark_model')
    landmark_db    = LaunchConfiguration('landmark_db')
    enable_landmark = LaunchConfiguration('enable_landmark')
    visualize      = LaunchConfiguration('visualize')

    depth_camera_node = Node(
        package='hri_pkg',
        executable='depth_camera_node',
        name='depth_camera_node',
        output='screen',
        parameters=[{
            'width': 640,
            'height': 480,
            'fps': 30,
            'enable_depth': True,
            'enable_color': True,
            'align_depth_to_color': True,
        }],
    )

    person_detection_node = Node(
        package='hri_pkg',
        executable='person_detection_node',
        name='person_detection_node',
        output='screen',
        parameters=[{
            'model_path': person_model,
            'confidence_threshold': 0.5,
            'device': 'cuda',
            'visualize': visualize,
            'interaction_distance_m': 2.0,
            'use_depth': True,
        }],
    )

    landmark_detection_node = Node(
        package='hri_pkg',
        executable='landmark_detection_node',
        name='landmark_detection_node',
        output='screen',
        parameters=[{
            'model_path': landmark_model,
            'confidence_threshold': 0.45,
            'device': 'cuda',
            'visualize': visualize,
            'landmark_db_path': landmark_db,
            'max_detection_distance_m': 8.0,
            'localization_confidence_threshold': 0.6,
        }],
        condition=IfCondition(enable_landmark),
    )

    log_start = LogInfo(msg=[
        '\nHRI started\n',
        '   person_model: ', person_model, '\n',
        '   landmark_model: ', landmark_model, '\n',
    ])

    return LaunchDescription([
        *args,
        log_start,
        depth_camera_node,
        person_detection_node,
        landmark_detection_node,
    ])
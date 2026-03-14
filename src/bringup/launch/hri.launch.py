"""
Camera input + HRI perception pipeline.
Starts RealSense nodes and all HRI perception nodes.

Nodes started:
  depth_camera_node           (hri_pkg) × 2  - front / rear cameras
  person_detection_node    (hri_pkg)
  landmark_detection_node  (hri_pkg)
  gesture_recognition_node (hri_pkg)
  facial_expression_node   (hri_pkg)

Note: hri_manager_node is started in voice_interface.launch.py
      because it bridges perception ↔ voice interface.
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    try:
        hri_pkg_dir = get_package_share_directory('hri_pkg')
        landmark_db_default = os.path.join(hri_pkg_dir, 'config', 'landmark_db.json')
    except Exception:
        landmark_db_default = 'landmark_db.json'

    # Arguments
    args = [
        DeclareLaunchArgument('person_model',
            default_value='yolov8n.pt',
            description='YOLOv8 model for person detection (.pt or TensorRT .engine)'),
        DeclareLaunchArgument('landmark_model',
            default_value='yolov8n.pt',
            description='YOLOv8 model for landmark detection'),
        DeclareLaunchArgument('landmark_db',
            default_value=landmark_db_default,
            description='Path to landmark_db.json'),
        DeclareLaunchArgument('device',
            default_value='cuda',
            description='Inference device: cuda or cpu'),
        DeclareLaunchArgument('visualize',
            default_value='false',
            description='Publish annotated images (disable on Jetson to save resources)'),
        DeclareLaunchArgument('enable_landmark',   default_value='true'),
        DeclareLaunchArgument('enable_gesture',    default_value='true'),
        DeclareLaunchArgument('enable_expression', default_value='true'),

        # Camera resolution / FPS
        # NOTE: Two RealSense cameras on USB 3.0 — keep FPS ≤ 15 to avoid bandwidth issues
        DeclareLaunchArgument('camera_fps',    default_value='15'),
        DeclareLaunchArgument('camera_width',  default_value='640'),
        DeclareLaunchArgument('camera_height', default_value='480'),
    ]

    device        = LaunchConfiguration('device')
    visualize     = LaunchConfiguration('visualize')
    person_model  = LaunchConfiguration('person_model')
    landmark_model= LaunchConfiguration('landmark_model')
    landmark_db   = LaunchConfiguration('landmark_db')
    fps           = LaunchConfiguration('camera_fps')
    width         = LaunchConfiguration('camera_width')
    height        = LaunchConfiguration('camera_height')

    # Camera common parameters
    camera_params = {
        'width':                width,
        'height':               height,
        'fps':                  fps,
        'enable_depth':         True,
        'align_depth_to_color': True,
    }

    # RealSense nodes
    # Front camera: primary camera for HRI (person detection, landmarks)
    # Rear camera: secondary (obstacle avoidance, wider coverage)
    # Each camera publishes on its own namespace.
    depth_camera_front = Node(
        package='hri_pkg',
        executable='depth_camera_node',
        name='depth_camera_front',
        namespace='dori/camera/front',
        output='screen',
        parameters=[{
            **camera_params,
            'serial_number': '',   # set to camera serial if two cameras conflict
        }],
        remappings=[
            # Remap to unified /dori/camera/ namespace used by perception nodes
            ('color/image_raw',   '/dori/camera/color/image_raw'),
            ('depth/image_raw',   '/dori/camera/depth/image_raw'),
            ('color/camera_info', '/dori/camera/color/camera_info'),
            ('depth/camera_info', '/dori/camera/depth/camera_info'),
            ('depth_scale',       '/dori/camera/depth_scale'),
        ],
    )

    depth_camera_rear = Node(
        package='hri_pkg',
        executable='depth_camera_node',
        name='depth_camera_rear',
        namespace='dori/camera/rear',
        output='screen',
        parameters=[{
            **camera_params,
            'serial_number': '',   # TODO: set rear camera serial number
        }],
        # Rear camera uses its own namespace — SLAM team subscribes directly
        remappings=[
            ('color/image_raw',   '/dori/camera/rear/color/image_raw'),
            ('depth/image_raw',   '/dori/camera/rear/depth/image_raw'),
            ('color/camera_info', '/dori/camera/rear/color/camera_info'),
            ('depth/camera_info', '/dori/camera/rear/depth/camera_info'),
            ('depth_scale',       '/dori/camera/rear/depth_scale'),
        ],
    )

    # Perception nodes
    person_detection_node = Node(
        package='hri_pkg',
        executable='person_detection_node',
        name='person_detection_node',
        output='screen',
        parameters=[{
            'model_path':             person_model,
            'confidence_threshold':   0.5,
            'device':                 device,
            'visualize':              visualize,
            'use_depth':              True,
            'interaction_distance_m': 2.0,
            'lost_timeout_sec':       5.0,
        }],
    )

    landmark_detection_node = Node(
        package='hri_pkg',
        executable='landmark_detection_node',
        name='landmark_detection_node',
        output='screen',
        parameters=[{
            'model_path':      landmark_model,
            'device':          device,
            'visualize':       visualize,
            'landmark_db_path': landmark_db,
        }],
        condition=IfCondition(LaunchConfiguration('enable_landmark')),
    )

    gesture_recognition_node = Node(
        package='hri_pkg',
        executable='gesture_recognition_node',
        name='gesture_recognition_node',
        output='screen',
        parameters=[{
            'visualize':               visualize,
            'active_only_on_trigger':  True,
        }],
        condition=IfCondition(LaunchConfiguration('enable_gesture')),
    )

    facial_expression_node = Node(
        package='hri_pkg',
        executable='facial_expression_node',
        name='facial_expression_node',
        output='screen',
        parameters=[{
            'visualize':               visualize,
            'active_only_on_trigger':  True,
        }],
        condition=IfCondition(LaunchConfiguration('enable_expression')),
    )

    return LaunchDescription([
        *args,
        depth_camera_front,
        depth_camera_rear,
        person_detection_node,
        landmark_detection_node,
        gesture_recognition_node,
        facial_expression_node,
    ])

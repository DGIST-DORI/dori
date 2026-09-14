"""
Perception stack launch (camera/vision only).

Nodes started:
  depth_camera_node           (dori_perception or dori_perception_camera) x 2 - front / rear cameras
  person_detection_node       (dori_perception)
  landmark_detection_node     (dori_perception)
  gesture_recognition_node    (dori_perception)
  facial_expression_node      (dori_perception)
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def _topic(ns, suffix: str):
    return [ns, suffix]


def generate_launch_description():
    dori_ns = LaunchConfiguration('namespace')

    try:
        dori_perception_dir = get_package_share_directory('dori_perception')
        landmark_db_default = os.path.join(dori_perception_dir, 'config', 'landmark_db.json')
    except Exception:
        landmark_db_default = 'landmark_db.json'

    args = [
        DeclareLaunchArgument('person_model', default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_model', default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_db', default_value=landmark_db_default),
        DeclareLaunchArgument('device', default_value='cuda'),
        DeclareLaunchArgument('visualize', default_value='false'),
        DeclareLaunchArgument('enable_landmark', default_value='true'),
        DeclareLaunchArgument('enable_gesture', default_value='true'),
        DeclareLaunchArgument('enable_expression', default_value='true'),
        DeclareLaunchArgument('camera_fps', default_value='15'),
        DeclareLaunchArgument('camera_width', default_value='640'),
        DeclareLaunchArgument('camera_height', default_value='480'),
        DeclareLaunchArgument('use_cpp_depth_camera', default_value='true'),
        DeclareLaunchArgument('namespace', default_value='/dori'),
    ]

    camera_params = {
        'width': LaunchConfiguration('camera_width'),
        'height': LaunchConfiguration('camera_height'),
        'fps': LaunchConfiguration('camera_fps'),
        'enable_depth': True,
        'align_depth_to_color': True,
    }

    depth_camera_front_py = Node(
        package='dori_perception',
        executable='depth_camera_node',
        name='depth_camera_front',
        namespace='dori/camera/front',
        output='screen',
        parameters=[{**camera_params, 'serial_number': ''}],
        condition=UnlessCondition(LaunchConfiguration('use_cpp_depth_camera')),
        remappings=[
            ('color/image_raw', _topic(dori_ns, '/camera/front/color/image_raw')),
            ('depth/image_raw', _topic(dori_ns, '/camera/front/depth/image_raw')),
            ('depth/image_colormap', _topic(dori_ns, '/camera/front/depth/image_colormap')),
            ('color/camera_info', _topic(dori_ns, '/camera/front/color/camera_info')),
            ('depth/camera_info', _topic(dori_ns, '/camera/front/depth/camera_info')),
            ('depth/scale', _topic(dori_ns, '/camera/front/depth/scale')),
        ],
    )

    depth_camera_rear_py = Node(
        package='dori_perception',
        executable='depth_camera_node',
        name='depth_camera_rear',
        namespace='dori/camera/rear',
        output='screen',
        parameters=[{**camera_params, 'serial_number': ''}],
        condition=UnlessCondition(LaunchConfiguration('use_cpp_depth_camera')),
        remappings=[
            ('color/image_raw', _topic(dori_ns, '/camera/rear/color/image_raw')),
            ('depth/image_raw', _topic(dori_ns, '/camera/rear/depth/image_raw')),
            ('depth/image_colormap', _topic(dori_ns, '/camera/rear/depth/image_colormap')),
            ('color/camera_info', _topic(dori_ns, '/camera/rear/color/camera_info')),
            ('depth/camera_info', _topic(dori_ns, '/camera/rear/depth/camera_info')),
            ('depth/scale', _topic(dori_ns, '/camera/rear/depth/scale')),
        ],
    )

    depth_camera_front_cpp = Node(
        package='dori_perception_camera',
        executable='depth_camera_node',
        name='depth_camera_front',
        namespace='dori/camera/front',
        output='screen',
        parameters=[{**camera_params, 'serial_number': ''}],
        condition=IfCondition(LaunchConfiguration('use_cpp_depth_camera')),
        remappings=[
            ('color/image_raw', _topic(dori_ns, '/camera/front/color/image_raw')),
            ('depth/image_raw', _topic(dori_ns, '/camera/front/depth/image_raw')),
            ('color/camera_info', _topic(dori_ns, '/camera/front/color/camera_info')),
            ('depth/camera_info', _topic(dori_ns, '/camera/front/depth/camera_info')),
            ('depth/scale', _topic(dori_ns, '/camera/front/depth/scale')),
        ],
    )

    depth_camera_rear_cpp = Node(
        package='dori_perception_camera',
        executable='depth_camera_node',
        name='depth_camera_rear',
        namespace='dori/camera/rear',
        output='screen',
        parameters=[{**camera_params, 'serial_number': ''}],
        condition=IfCondition(LaunchConfiguration('use_cpp_depth_camera')),
        remappings=[
            ('color/image_raw', _topic(dori_ns, '/camera/rear/color/image_raw')),
            ('depth/image_raw', _topic(dori_ns, '/camera/rear/depth/image_raw')),
            ('color/camera_info', _topic(dori_ns, '/camera/rear/color/camera_info')),
            ('depth/camera_info', _topic(dori_ns, '/camera/rear/depth/camera_info')),
            ('depth/scale', _topic(dori_ns, '/camera/rear/depth/scale')),
        ],
    )


    person_detection_node = Node(
        package='dori_perception',
        executable='person_detection_node',
        name='person_detection_node',
        output='screen',
        parameters=[{
            'model_path': LaunchConfiguration('person_model'),
            'confidence_threshold': 0.5,
            'device': LaunchConfiguration('device'),
            'visualize': LaunchConfiguration('visualize'),
            'use_depth': True,
            'interaction_distance_m': 2.0,
            'lost_timeout_sec': 5.0,
            'topics.color_image_sub': _topic(dori_ns, '/camera/front/color/image_raw'),
            'topics.depth_image_sub': _topic(dori_ns, '/camera/front/depth/image_raw'),
            'topics.depth_scale_sub': _topic(dori_ns, '/camera/front/depth/scale'),
            'services.follow_mode_service': _topic(dori_ns, '/hri/set_follow_mode'),
            'topics.persons_pub': _topic(dori_ns, '/hri/persons'),
            'topics.interaction_trigger_pub': _topic(dori_ns, '/hri/interaction_trigger'),
            'topics.tracking_state_pub': _topic(dori_ns, '/hri/tracking_state'),
            'topics.follow_offset_pub': _topic(dori_ns, '/follow/target_offset'),
            'topics.annotated_pub': _topic(dori_ns, '/hri/annotated_image'),
        }],
    )

    landmark_detection_node = Node(
        package='dori_perception',
        executable='landmark_detection_node',
        name='landmark_detection_node',
        output='screen',
        parameters=[{
            'model_path': LaunchConfiguration('landmark_model'),
            'device': LaunchConfiguration('device'),
            'visualize': LaunchConfiguration('visualize'),
            'landmark_db_path': LaunchConfiguration('landmark_db'),
            'topics.color_image_sub': _topic(dori_ns, '/camera/front/color/image_raw'),
            'topics.depth_image_sub': _topic(dori_ns, '/camera/front/depth/image_raw'),
            'topics.color_camera_info_sub': _topic(dori_ns, '/camera/front/color/camera_info'),
            'topics.detections_pub': _topic(dori_ns, '/landmark/detections'),
            'topics.localization_pub': _topic(dori_ns, '/landmark/localization'),
            'topics.context_pub': _topic(dori_ns, '/landmark/context'),
            'topics.annotated_pub': _topic(dori_ns, '/hri/annotated_landmark'),
        }],
        condition=IfCondition(LaunchConfiguration('enable_landmark')),
    )

    gesture_recognition_node = Node(
        package='dori_perception',
        executable='gesture_recognition_node',
        name='gesture_recognition_node',
        output='screen',
        parameters=[{
            'visualize': LaunchConfiguration('visualize'),
            'active_only_on_trigger': True,
            'topics.color_image_sub': _topic(dori_ns, '/camera/front/color/image_raw'),
            'topics.interaction_trigger_sub': _topic(dori_ns, '/hri/interaction_trigger'),
            'topics.gesture_pub': _topic(dori_ns, '/hri/gesture'),
            'topics.gesture_command_pub': _topic(dori_ns, '/hri/gesture_command'),
            'topics.wake_word_pub': _topic(dori_ns, '/stt/wake_word_detected'),
            'topics.annotated_pub': _topic(dori_ns, '/hri/annotated_gesture'),
        }],
        condition=IfCondition(LaunchConfiguration('enable_gesture')),
    )

    facial_expression_node = Node(
        package='dori_perception',
        executable='facial_expression_node',
        name='facial_expression_node',
        output='screen',
        parameters=[{
            'visualize': LaunchConfiguration('visualize'),
            'active_only_on_trigger': True,
            'topics.color_image_sub': _topic(dori_ns, '/camera/front/color/image_raw'),
            'topics.interaction_trigger_sub': _topic(dori_ns, '/hri/interaction_trigger'),
            'topics.expression_pub': _topic(dori_ns, '/hri/expression'),
            'topics.expression_command_pub': _topic(dori_ns, '/hri/expression_command'),
            'topics.annotated_pub': _topic(dori_ns, '/hri/annotated_expression'),
        }],
        condition=IfCondition(LaunchConfiguration('enable_expression')),
    )

    return LaunchDescription([
        *args,
        depth_camera_front_py,
        depth_camera_rear_py,
        depth_camera_front_cpp,
        depth_camera_rear_cpp,
        person_detection_node,
        landmark_detection_node,
        gesture_recognition_node,
        facial_expression_node,
    ])

"""
Single RealSense + all HRI perception nodes.
Use this for standalone HRI development without the full bringup stack.

For actual robot operation, use:
  ros2 launch bringup robot.launch.py

Usage:
  ros2 launch hri_pkg hri.launch.py
  ros2 launch hri_pkg hri.launch.py debug:=true
  ros2 launch hri_pkg hri.launch.py visualize:=true device:=cpu
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():

    args = [
        DeclareLaunchArgument('person_model',      default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_model',    default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_db',       default_value='landmark_db.json'),
        DeclareLaunchArgument('device',            default_value='cuda'),
        DeclareLaunchArgument('visualize',         default_value='true'),
        DeclareLaunchArgument('enable_landmark',   default_value='true'),
        DeclareLaunchArgument('enable_gesture',    default_value='true'),
        DeclareLaunchArgument('enable_expression', default_value='true'),
        DeclareLaunchArgument('fps',               default_value='15'),
        DeclareLaunchArgument('width',             default_value='640'),
        DeclareLaunchArgument('height',            default_value='480'),
        DeclareLaunchArgument('debug',             default_value='false'),
    ]

    device        = LaunchConfiguration('device')
    visualize     = LaunchConfiguration('visualize')
    debug         = LaunchConfiguration('debug')

    depth_camera_node = Node(
        package='hri_pkg', executable='depth_camera_node', name='depth_camera_node',
        output='screen',
        parameters=[{
            'width':                LaunchConfiguration('width'),
            'height':               LaunchConfiguration('height'),
            'fps':                  LaunchConfiguration('fps'),
            'enable_depth':         True,
            'align_depth_to_color': True,
        }],
    )

    person_detection_node = Node(
        package='hri_pkg', executable='person_detection_node',
        name='person_detection_node', output='screen',
        parameters=[{
            'model_path':           LaunchConfiguration('person_model'),
            'confidence_threshold': 0.5,
            'device':               device,
            'visualize':            visualize,
            'use_depth':            True,
        }],
    )

    landmark_detection_node = Node(
        package='hri_pkg', executable='landmark_detection_node',
        name='landmark_detection_node', output='screen',
        parameters=[{
            'model_path':      LaunchConfiguration('landmark_model'),
            'device':          device,
            'visualize':       visualize,
            'landmark_db_path': LaunchConfiguration('landmark_db'),
        }],
        condition=IfCondition(LaunchConfiguration('enable_landmark')),
    )

    gesture_recognition_node = Node(
        package='hri_pkg', executable='gesture_recognition_node',
        name='gesture_recognition_node', output='screen',
        parameters=[{'visualize': visualize, 'active_only_on_trigger': True}],
        condition=IfCondition(LaunchConfiguration('enable_gesture')),
    )

    facial_expression_node = Node(
        package='hri_pkg', executable='facial_expression_node',
        name='facial_expression_node', output='screen',
        parameters=[{'visualize': visualize, 'active_only_on_trigger': True}],
        condition=IfCondition(LaunchConfiguration('enable_expression')),
    )

    hri_manager_node = Node(
        package='hri_pkg', executable='hri_manager_node',
        name='hri_manager_node', output='screen',
        parameters=[{'idle_timeout_sec': 10.0}],
    )

    # Debug: rqt image viewers
    rqt_person = Node(
        package='rqt_image_view', executable='rqt_image_view',
        name='rqt_person', arguments=['/dori/hri/annotated_image'],
        condition=IfCondition(debug),
    )
    rqt_gesture = Node(
        package='rqt_image_view', executable='rqt_image_view',
        name='rqt_gesture', arguments=['/dori/hri/annotated_gesture'],
        condition=IfCondition(debug),
    )
    rqt_expression = Node(
        package='rqt_image_view', executable='rqt_image_view',
        name='rqt_expression', arguments=['/dori/hri/annotated_expression'],
        condition=IfCondition(debug),
    )

    log_start = LogInfo(msg=[
        '\n==============================\n'
        ' HRI dev launch\n',
        '  device: ', device, '\n',
        '  visualize: ', visualize, '\n',
        '==============================',
    ])

    return LaunchDescription([
        *args,
        log_start,
        depth_camera_node,
        person_detection_node,
        landmark_detection_node,
        gesture_recognition_node,
        facial_expression_node,
        hri_manager_node,
        rqt_person,
        rqt_gesture,
        rqt_expression,
    ])

"""
how to use:
  ros2 launch hri_pkg hri.launch.py
  ros2 launch hri_pkg hri.launch.py use_realsense:=false
  ros2 launch hri_pkg hri.launch.py landmark_model:=runs/landmark/best.pt debug:=true
  ros2 launch hri_pkg hri.launch.py visualize:=false  # Jetson 성능 절약
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():

    args = [
        DeclareLaunchArgument('use_realsense',    default_value='true'),
        DeclareLaunchArgument('camera_index',     default_value='0'),
        DeclareLaunchArgument('width',            default_value='640'),
        DeclareLaunchArgument('height',           default_value='480'),
        DeclareLaunchArgument('fps',              default_value='30'),
        DeclareLaunchArgument('person_model',     default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_model',   default_value='yolov8n.pt'),
        DeclareLaunchArgument('landmark_db',      default_value='landmark_db.json'),
        DeclareLaunchArgument('device',           default_value='cuda'),
        DeclareLaunchArgument('visualize',        default_value='true'),
        DeclareLaunchArgument('enable_landmark',  default_value='true'),
        DeclareLaunchArgument('enable_gesture',   default_value='true'),
        DeclareLaunchArgument('enable_expression',default_value='true'),
        DeclareLaunchArgument('debug',            default_value='false'),
    ]

    use_realsense    = LaunchConfiguration('use_realsense')
    camera_index     = LaunchConfiguration('camera_index')
    width            = LaunchConfiguration('width')
    height           = LaunchConfiguration('height')
    fps              = LaunchConfiguration('fps')
    person_model     = LaunchConfiguration('person_model')
    landmark_model   = LaunchConfiguration('landmark_model')
    landmark_db      = LaunchConfiguration('landmark_db')
    device           = LaunchConfiguration('device')
    visualize        = LaunchConfiguration('visualize')
    enable_landmark  = LaunchConfiguration('enable_landmark')
    enable_gesture   = LaunchConfiguration('enable_gesture')
    enable_expression= LaunchConfiguration('enable_expression')
    debug            = LaunchConfiguration('debug')

    # Node

    realsense_node = Node(
        package='hri_pkg', executable='realsense_node', name='realsense_node',
        output='screen',
        parameters=[{'width': width, 'height': height, 'fps': fps,
                     'enable_depth': True, 'align_depth_to_color': True}],
        condition=IfCondition(use_realsense),
    )

    camera_node = Node(
        package='hri_pkg', executable='camera_node', name='camera_node',
        output='screen',
        parameters=[{'camera_index': camera_index, 'frame_width': width,
                     'frame_height': height, 'fps': fps, 'publish_rate': fps}],
        condition=UnlessCondition(use_realsense),
        remappings=[('/cube/camera/image_raw', '/cube/camera/color/image_raw')],
    )

    person_detection_node = Node(
        package='hri_pkg', executable='person_detection_node',
        name='person_detection_node', output='screen',
        parameters=[{'model_path': person_model, 'confidence_threshold': 0.5,
                     'device': device, 'visualize': visualize,
                     'use_depth': use_realsense}],
    )

    landmark_detection_node = Node(
        package='hri_pkg', executable='landmark_detection_node',
        name='landmark_detection_node', output='screen',
        parameters=[{'model_path': landmark_model, 'device': device,
                     'visualize': visualize, 'landmark_db_path': landmark_db}],
        condition=IfCondition(enable_landmark),
    )

    gesture_recognition_node = Node(
        package='hri_pkg', executable='gesture_recognition_node',
        name='gesture_recognition_node', output='screen',
        parameters=[{'visualize': visualize, 'active_only_on_trigger': True}],
        condition=IfCondition(enable_gesture),
    )

    facial_expression_node = Node(
        package='hri_pkg', executable='facial_expression_node',
        name='facial_expression_node', output='screen',
        parameters=[{'visualize': visualize, 'active_only_on_trigger': True}],
        condition=IfCondition(enable_expression),
    )

    hri_manager_node = Node(
        package='hri_pkg', executable='hri_manager_node',
        name='hri_manager_node', output='screen',
        parameters=[{'idle_timeout_sec': 10.0}],
    )

    # rqt_image_view for debugging
    rqt_person = Node(
        package='rqt_image_view', executable='rqt_image_view',
        name='rqt_person', arguments=['/cube/hri/annotated_image'],
        condition=IfCondition(debug),
    )
    rqt_gesture = Node(
        package='rqt_image_view', executable='rqt_image_view',
        name='rqt_gesture', arguments=['/cube/hri/annotated_gesture'],
        condition=IfCondition(debug),
    )

    log_start = LogInfo(msg=[
        '\n==============================\n',
        ' HRI Package started\n',
        '  RealSense: ', use_realsense, '\n',
        '  Device: ', device, '\n',
        '  Visualize: ', visualize, '\n',
        '==============================',
    ])

    return LaunchDescription([
        *args,
        log_start,
        realsense_node,
        camera_node,
        person_detection_node,
        landmark_detection_node,
        gesture_recognition_node,
        facial_expression_node,
        hri_manager_node,
        rqt_person,
        rqt_gesture,
    ])

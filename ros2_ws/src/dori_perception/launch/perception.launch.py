"""Independent front/rear USB RGB streams and image-only perception."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _topic(ns, suffix: str):
    return [ns, suffix]


def generate_launch_description():
    dori_ns = LaunchConfiguration("namespace")

    try:
        dori_perception_dir = get_package_share_directory("dori_perception")
        landmark_db_default = os.path.join(
            dori_perception_dir, "config", "landmark_db.json"
        )
    except Exception:
        landmark_db_default = "landmark_db.json"

    args = [
        DeclareLaunchArgument("person_model", default_value="yolov8n.pt"),
        DeclareLaunchArgument("person_tracker", default_value="bytetrack.yaml"),
        DeclareLaunchArgument("person_lost_timeout_sec", default_value="5.0"),
        DeclareLaunchArgument("person_max_inference_fps", default_value="10.0"),
        DeclareLaunchArgument("perception_max_frame_age_sec", default_value="1.0"),
        DeclareLaunchArgument("landmark_model", default_value="yolov8n.pt"),
        DeclareLaunchArgument("landmark_db", default_value=landmark_db_default),
        DeclareLaunchArgument("device", default_value="cpu"),
        DeclareLaunchArgument("front_device", default_value="/dev/video0"),
        DeclareLaunchArgument("rear_device", default_value="/dev/video2"),
        DeclareLaunchArgument("front_calibration_file", default_value=""),
        DeclareLaunchArgument("rear_calibration_file", default_value=""),
        DeclareLaunchArgument("enable_rear_camera", default_value="true"),
        DeclareLaunchArgument("camera_pixel_format", default_value="MJPG"),
        DeclareLaunchArgument("hand_model_path", default_value=""),
        DeclareLaunchArgument("gesture_backend", default_value="hands", choices=["hands", "pose"]),
        DeclareLaunchArgument("pose_model_path", default_value=""),
        DeclareLaunchArgument("face_model_path", default_value=""),
        DeclareLaunchArgument("visualize", default_value="false"),
        DeclareLaunchArgument("enable_landmark", default_value="false"),
        DeclareLaunchArgument("enable_gesture", default_value="false"),
        DeclareLaunchArgument("enable_expression", default_value="false"),
        DeclareLaunchArgument("camera_fps", default_value="15"),
        DeclareLaunchArgument("camera_width", default_value="640"),
        DeclareLaunchArgument("camera_height", default_value="480"),
        DeclareLaunchArgument("namespace", default_value="/dori"),
    ]

    def camera(position):
        return Node(
            package="dori_perception_camera", executable="rgb_camera_node",
            name="camera_" + position, namespace=[dori_ns, "/camera/", position],
            output="screen",
            condition=IfCondition(LaunchConfiguration("enable_rear_camera")) if position == "rear" else None,
            parameters=[{
                "device": ParameterValue(LaunchConfiguration(position + "_device"), value_type=str),
                "calibration_file": ParameterValue(LaunchConfiguration(position + "_calibration_file"), value_type=str),
                "frame_id": "camera_" + position + "_optical_frame",
                "width": ParameterValue(LaunchConfiguration("camera_width"), value_type=int),
                "height": ParameterValue(LaunchConfiguration("camera_height"), value_type=int),
                "fps": ParameterValue(LaunchConfiguration("camera_fps"), value_type=int),
                "pixel_format": LaunchConfiguration("camera_pixel_format"),
            }],
        )

    person_detection_node = Node(
        package="dori_perception",
        executable="person_detection_node",
        name="person_detection_node",
        output="screen",
        parameters=[
            {
                "model_path": LaunchConfiguration("person_model"),
                "tracker_config": LaunchConfiguration("person_tracker"),
                "lost_timeout_sec": ParameterValue(LaunchConfiguration("person_lost_timeout_sec"), value_type=float),
                "max_inference_fps": ParameterValue(LaunchConfiguration("person_max_inference_fps"), value_type=float),
                "max_frame_age_sec": ParameterValue(LaunchConfiguration("perception_max_frame_age_sec"), value_type=float),
                "confidence_threshold": 0.5,
                "device": LaunchConfiguration("device"),
                "visualize": LaunchConfiguration("visualize"),
                "camera_id": "front",
                "topics.color_image_sub": _topic(
                    dori_ns, "/camera/front/color/image_raw"
                ),
                "services.follow_mode_service": _topic(dori_ns, "/hri/set_follow_mode"),
                "topics.persons_pub": _topic(dori_ns, "/hri/persons"),
                "topics.tracking_state_pub": _topic(dori_ns, "/hri/tracking_state"),
                "topics.annotated_pub": _topic(dori_ns, "/hri/annotated_image"),
            }
        ],
    )

    rear_person_detection_node = Node(
        package="dori_perception", executable="person_detection_node",
        name="person_detection_rear", output="screen",
        condition=IfCondition(LaunchConfiguration("enable_rear_camera")),
        parameters=[{
            "model_path": LaunchConfiguration("person_model"),
            "tracker_config": LaunchConfiguration("person_tracker"),
            "lost_timeout_sec": ParameterValue(LaunchConfiguration("person_lost_timeout_sec"), value_type=float),
            "max_inference_fps": ParameterValue(LaunchConfiguration("person_max_inference_fps"), value_type=float),
            "max_frame_age_sec": ParameterValue(LaunchConfiguration("perception_max_frame_age_sec"), value_type=float),
            "device": LaunchConfiguration("device"),
            "visualize": LaunchConfiguration("visualize"),
            "camera_id": "rear",
            "topics.color_image_sub": _topic(dori_ns, "/camera/rear/color/image_raw"),
            "topics.persons_pub": _topic(dori_ns, "/hri/rear/persons"),
            "topics.tracking_state_pub": _topic(dori_ns, "/hri/rear/tracking_state"),
            "topics.annotated_pub": _topic(dori_ns, "/hri/rear/annotated_image"),
            "services.follow_mode_service": _topic(dori_ns, "/hri/rear/set_follow_mode"),
        }],
    )

    landmark_detection_node = Node(
        package="dori_perception",
        executable="landmark_detection_node",
        name="landmark_detection_node",
        output="screen",
        parameters=[
            {
                "model_path": LaunchConfiguration("landmark_model"),
                "device": LaunchConfiguration("device"),
                "visualize": LaunchConfiguration("visualize"),
                "landmark_db_path": LaunchConfiguration("landmark_db"),
                "topics.color_image_sub": _topic(
                    dori_ns, "/camera/front/color/image_raw"
                ),
                "topics.color_camera_info_sub": _topic(
                    dori_ns, "/camera/front/color/camera_info"
                ),
                "topics.detections_pub": _topic(dori_ns, "/landmark/detections"),
                "topics.localization_pub": _topic(dori_ns, "/landmark/localization"),
                "topics.context_pub": _topic(dori_ns, "/landmark/context"),
                "topics.annotated_pub": _topic(dori_ns, "/hri/annotated_landmark"),
            }
        ],
        condition=IfCondition(LaunchConfiguration("enable_landmark")),
    )

    gesture_recognition_node = Node(
        package="dori_perception",
        executable="gesture_recognition_node",
        name="gesture_recognition_node",
        output="screen",
        parameters=[
            {
                "visualize": LaunchConfiguration("visualize"),
                "hand_model_path": LaunchConfiguration("hand_model_path"),
                "gesture_backend": LaunchConfiguration("gesture_backend"),
                "pose_model_path": LaunchConfiguration("pose_model_path"),
                "max_frame_age_sec": ParameterValue(LaunchConfiguration("perception_max_frame_age_sec"), value_type=float),
                "active_only_on_trigger": True,
                "topics.color_image_sub": _topic(
                    dori_ns, "/camera/front/color/image_raw"
                ),
                "topics.interaction_trigger_sub": _topic(
                    dori_ns, "/hri/interaction_trigger"
                ),
                "topics.gesture_pub": _topic(dori_ns, "/hri/gesture"),
                "topics.gesture_command_pub": _topic(dori_ns, "/hri/gesture_command"),
                "topics.wake_word_pub": _topic(dori_ns, "/stt/wake_word_detected"),
                "topics.annotated_pub": _topic(dori_ns, "/hri/annotated_gesture"),
            }
        ],
        condition=IfCondition(LaunchConfiguration("enable_gesture")),
    )

    facial_expression_node = Node(
        package="dori_perception",
        executable="facial_expression_node",
        name="facial_expression_node",
        output="screen",
        parameters=[
            {
                "visualize": LaunchConfiguration("visualize"),
                "face_model_path": LaunchConfiguration("face_model_path"),
                "active_only_on_trigger": True,
                "topics.color_image_sub": _topic(
                    dori_ns, "/camera/front/color/image_raw"
                ),
                "topics.interaction_trigger_sub": _topic(
                    dori_ns, "/hri/interaction_trigger"
                ),
                "topics.expression_pub": _topic(dori_ns, "/hri/expression"),
                "topics.expression_command_pub": _topic(
                    dori_ns, "/hri/expression_command"
                ),
                "topics.annotated_pub": _topic(dori_ns, "/hri/annotated_expression"),
            }
        ],
        condition=IfCondition(LaunchConfiguration("enable_expression")),
    )

    return LaunchDescription(
        [
            *args,
            camera("front"),
            camera("rear"),
            person_detection_node,
            rear_person_detection_node,
            landmark_detection_node,
            gesture_recognition_node,
            facial_expression_node,
        ]
    )

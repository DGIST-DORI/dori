"""Validated launch configuration; CLI > profile YAML > common YAML > defaults."""
import math
from pathlib import Path

import yaml
from ament_index_python.packages import get_package_share_directory
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from dori_hardware.startup_checks import (
    CAN_INTERFACE, CAN_WAIT_TIMEOUT, DXL_PORT, DXL_BAUDRATE, IMU_PORT, LIDAR_PORT,
)


DEFAULTS = dict(
    namespace="/dori", visitor_mode="true", visitor_stt="azure",
    enable_hri="true", enable_dashboard="true", enable_stt="auto",
    stt_audio_input_mode="auto", whisper_model="", whisper_device="cpu",
    tts_playback_mode="local_only", tts_engine="gcp", tts_language="ko",
    use_external_llm="true", llm_model="gemini-3.5-flash-lite",
    knowledge_file="", rag_index_dir="", rag_top_k="3",
    require_user_tracking="false", require_mic_return="false", tree_xml_file="",
    enable_perception="auto", perception_device="cpu",
    enable_gesture="false", enable_expression="false", enable_landmark="false",
    front_serial="", rear_serial="", enable_rear_camera="false",
    use_cpp_depth_camera="true", hand_model_path="", face_model_path="",
    person_model="yolov8n.pt", landmark_model="yolov8n.pt",
    map="", named_goals_file="", use_joystick="false", rviz="false",
    can_interface=CAN_INTERFACE, can_wait_timeout=CAN_WAIT_TIMEOUT,
    dxl_port=DXL_PORT, dxl_baudrate=DXL_BAUDRATE, imu_port=IMU_PORT, lidar_port=LIDAR_PORT,
    web_host="0.0.0.0", sigterm_timeout="15.0", startup_timeout="120.0",
    **{"laser_" + axis: "3.141592653589793" if axis == "yaw" else "0.0"
       for axis in ("x", "y", "z", "roll", "pitch", "yaw")},
)
CHOICES = {
    key: ["true", "false"] for key, value in DEFAULTS.items() if value in ("true", "false")
}
CHOICES.update(
    enable_stt=["auto", "true", "false"], enable_perception=["auto", "true", "false"],
    visitor_stt=["azure", "whisper"], stt_audio_input_mode=["auto", "microphone", "topic"],
    tts_playback_mode=["local_only", "publish_only", "local_and_publish"],
)
PATHS = {"map", "named_goals_file", "knowledge_file", "rag_index_dir", "tree_xml_file",
         "hand_model_path", "face_model_path"}
MODELS = {"person_model", "landmark_model", "whisper_model"}


def repo_root():
    share = Path(get_package_share_directory("dori_bringup")).resolve()
    for candidate in (share, *share.parents):
        if (candidate / "requirements-runtime.txt").is_file() and (candidate / "ros2_ws/src").is_dir():
            return candidate
    raise RuntimeError("Cannot locate the DORI checkout from the installed bringup package")


def read_config(filename, mode):
    path = Path(filename).expanduser().resolve(strict=True)
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or set(data) - {"common", "robot", "desktop"}:
        raise ValueError("config_file must contain only common, robot and desktop mappings")
    sections = {}
    for section, values in data.items():
        if not isinstance(values, dict) or set(values) - DEFAULTS.keys():
            raise ValueError(f"Invalid or unknown launch options in config_file section {section}")
        parsed = {}
        for key, value in values.items():
            if isinstance(value, bool):
                value = str(value).lower()
            elif isinstance(value, (str, int, float)) and not (
                    isinstance(value, float) and not math.isfinite(value)):
                value = str(value)
            else:
                raise ValueError(f"config_file {section}.{key} must be a finite scalar")
            if key in CHOICES and value not in CHOICES[key]:
                raise ValueError(f"Invalid config_file {section}.{key}: {value}")
            if value and (key in PATHS or key in MODELS):
                value = value.replace("${DORI_ROOT}", str(repo_root()))
                if "${" in value:
                    raise ValueError(f"Only ${{DORI_ROOT}} is supported in config_file paths: {key}")
                if key in PATHS or "/" in value or value.startswith("."):
                    model_path = Path(value).expanduser()
                    value = str((path.parent / model_path).resolve())
            parsed[key] = value
        sections[section] = parsed
    return {**sections.get("common", {}), **sections.get(mode, {})}


def load_config(context):
    filename = LaunchConfiguration("config_file").perform(context)
    if filename:
        mode = LaunchConfiguration("dori_mode").perform(context)
        for key, value in read_config(filename, mode).items():
            context.launch_configurations.setdefault(key, value)
    return []


def arguments(mode="robot", *, fixed=False):
    # The loader runs before defaults, so explicitly supplied CLI values win.
    return [
        DeclareLaunchArgument("dori_mode", default_value=mode,
                              choices=[mode] if fixed else ["robot", "desktop"]),
        DeclareLaunchArgument("config_file", default_value="",
                              description="Deployment YAML; explicit launch arguments take precedence"),
        OpaqueFunction(function=load_config),
        *[DeclareLaunchArgument(
            key, default_value=(EnvironmentVariable("DORI_VISITOR_STT", default_value=value)
                                if key == "visitor_stt" else value), choices=CHOICES.get(key))
          for key, value in DEFAULTS.items()],
    ]

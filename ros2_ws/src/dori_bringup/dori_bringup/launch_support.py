"""Common service composition and voice/perception policy for both profiles."""
import math
from pathlib import Path
import subprocess

from ament_index_python.packages import get_package_share_directory
from launch.actions import GroupAction, IncludeLaunchDescription, SetEnvironmentVariable
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from .configuration import repo_root


def include(package, filename, params):
    return GroupAction(scoped=True, actions=[IncludeLaunchDescription(
        PythonLaunchDescriptionSource(str(Path(get_package_share_directory(package)) / "launch" / filename)),
        launch_arguments=params.items(),
    )])


def check_visitor(context, root, provider, model):
    """Check with the gateway's Python, even when ros2 itself uses system Python."""
    python = root / ".venv/bin/python"
    if provider == "azure":
        code = (
            "import azure.cognitiveservices.speech\n"
            "from dori_dashboard.azure_speech import load_config\n"
            "load_config()\n"
        )
        help_text = "Run scripts/build.sh and configure Azure F0 in .state/voice/azure.env (or DORI_AZURE_ENV_FILE)."
    else:
        if not (Path(model) / "model.bin").is_file():
            raise RuntimeError("Prepare visitor Whisper first: scripts/prepare_voice.sh --topic-only")
        code = "import faster_whisper\n"
        help_text = "Prepare visitor Whisper first: scripts/prepare_voice.sh --topic-only"
    try:
        subprocess.run(
            [str(python), "-c", code],
            env={**context.environment, "DORI_WS": str(root)},
            check=True, timeout=15, capture_output=True,
        )
    except (OSError, subprocess.SubprocessError):
        # Do not expose provider errors or credentials in the launch log.
        raise RuntimeError(help_text) from None


def prepare(context):
    value = lambda key: LaunchConfiguration(key).perform(context)
    mode = value("dori_mode")
    root = repo_root()
    visitor = value("visitor_mode") == "true"
    provider = value("visitor_stt")
    if value("enable_perception") == "auto":
        context.launch_configurations["enable_perception"] = "true" if mode == "robot" else "false"
    if mode == "robot":
        if not value("map"):
            raise ValueError("Robot mode requires map:=/path/to/map.yaml or a config_file with map")
        if value("enable_perception") != "true":
            raise ValueError("Robot mode requires front camera and person detection (enable_perception:=true)")
    timeout = float(value("startup_timeout"))
    if not math.isfinite(timeout) or not 1 <= timeout <= 600:
        raise ValueError("startup_timeout must be finite and between 1 and 600 seconds")
    if value("enable_stt") == "auto":
        context.launch_configurations["enable_stt"] = "false" if visitor and provider == "azure" else "true"
    if value("stt_audio_input_mode") == "auto":
        context.launch_configurations["stt_audio_input_mode"] = "topic" if visitor else "microphone"
    if not value("whisper_model"):
        context.launch_configurations["whisper_model"] = str(root / ".state/voice/whisper-small") if visitor else "small"
    if visitor:
        if value("stt_audio_input_mode") != "topic":
            raise ValueError("Visitor mode requires stt_audio_input_mode:=topic")
        if provider == "whisper" and value("enable_stt") != "true":
            raise ValueError("Visitor Whisper requires enable_stt:=true")
        if value("enable_dashboard") == "true":
            check_visitor(context, root, provider, value("whisper_model"))
    return [
        SetEnvironmentVariable("DORI_VISITOR_STT", provider),
        SetEnvironmentVariable("DORI_SESSION_ROOT", str(root)),
    ]


def services(context, *, robot=False):
    value = lambda key: LaunchConfiguration(key).perform(context)
    params = lambda keys: {key: value(key) for key in keys}
    actions = []
    if value("enable_hri") == "true":
        actions += [
            include("dori_hri", "voice.launch.py", params((
                "namespace", "enable_stt", "stt_audio_input_mode", "whisper_model", "whisper_device",
                "tts_playback_mode", "tts_engine", "tts_language", "use_external_llm", "llm_model",
                "knowledge_file", "rag_index_dir", "rag_top_k",
            ))),
            include("dori_bt", "interaction.launch.py", params((
                "namespace", "visitor_mode", "require_user_tracking", "require_mic_return", "tree_xml_file",
            ))),
        ]
    if value("enable_perception") == "true":
        actions.append(include("dori_perception", "perception.launch.py", {
            "device": value("perception_device"),
            **params(("namespace", "enable_gesture", "enable_expression", "enable_landmark",
                      "front_serial", "rear_serial", "enable_rear_camera", "use_cpp_depth_camera",
                      "hand_model_path", "face_model_path", "person_model", "landmark_model")),
        }))
    if value("enable_dashboard") == "true":
        actions.append(include("dori_dashboard", "dashboard.launch.py", {
            "enable_navigation_viewer": "false" if robot else "true",
        }))
    return actions

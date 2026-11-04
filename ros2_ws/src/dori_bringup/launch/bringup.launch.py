"""Visitor app and dashboard by default; opt into local voice or physical hardware."""

from pathlib import Path
import subprocess
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    OpaqueFunction,
    SetEnvironmentVariable,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration


def repo_root():
    share = Path(get_package_share_directory("dori_bringup")).resolve()
    for candidate in (share, *share.parents):
        if (candidate / "requirements-runtime.txt").is_file() and (candidate / "ros2_ws/src").is_dir():
            return candidate
    raise RuntimeError("Cannot locate the DORI checkout from the installed bringup package")


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


def setup(context):
    value = lambda n: LaunchConfiguration(n).perform(context)
    share = Path(get_package_share_directory("dori_bringup")) / "launch"
    visitor = value("visitor_mode") == "true"
    provider = value("visitor_stt")
    root = repo_root()
    if value("enable_stt") == "auto":
        context.launch_configurations["enable_stt"] = "false" if visitor and provider == "azure" else "true"
    if value("stt_audio_input_mode") == "auto":
        context.launch_configurations["stt_audio_input_mode"] = "topic" if visitor else "microphone"
    if not value("whisper_model"):
        context.launch_configurations["whisper_model"] = (
            str(root / ".state/voice/whisper-small") if visitor else "small"
        )
    if visitor:
        if value("stt_audio_input_mode") != "topic":
            raise ValueError("Visitor mode requires stt_audio_input_mode:=topic")
        if provider == "whisper" and value("enable_stt") != "true":
            raise ValueError("Visitor Whisper requires enable_stt:=true")
        if value("enable_dashboard") == "true":
            check_visitor(context, root, provider, value("whisper_model"))
    environment = [SetEnvironmentVariable("DORI_VISITOR_STT", provider)]

    def include(filename, params):
        return IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(share / filename)),
            launch_arguments=params.items(),
        )

    if value("dori_mode") == "real":
        return environment + [
            include(
                "hardware.launch.py",
                {
                    "map": value("real_map"),
                    "named_goals_file": value("real_named_goals_file"),
                    "use_joystick": value("real_use_joystick"),
                    **{
                        k: value(k)
                        for k in (
                            "namespace",
                            "visitor_mode",
                            "stt_audio_input_mode",
                            "enable_stt",
                            "enable_dashboard",
                            "enable_perception",
                            "tts_playback_mode",
                            "tts_engine",
                            "whisper_model",
                            "use_external_llm",
                            "llm_model",
                            "require_user_tracking",
                        )
                    },
                },
            )
        ]
    if value("dori_mode") not in ("sim", "desktop"):
        raise ValueError("dori_mode must be real, desktop or sim (desktop alias)")
    actions = [
        include(
            "voice.launch.py",
            {
                k: value(k)
                for k in (
                    "namespace",
                    "stt_audio_input_mode",
                    "enable_stt",
                    "tts_playback_mode",
                    "tts_engine",
                    "whisper_model",
                    "use_external_llm",
                    "llm_model",
                )
            },
        ),
        include("interaction.launch.py", {"namespace": value("namespace"), "visitor_mode": value("visitor_mode")}),
    ]
    if value("enable_perception") == "true":
        actions.append(
            include("perception.launch.py", {"namespace": value("namespace")})
        )
    if value("enable_dashboard") == "true":
        dashboard = (
            Path(get_package_share_directory("dori_dashboard"))
            / "launch/dashboard.launch.py"
        )
        actions.append(
            IncludeLaunchDescription(PythonLaunchDescriptionSource(str(dashboard)))
        )
    return environment + actions


def generate_launch_description():
    defaults = dict(
        dori_mode="desktop",
        namespace="/dori",
        visitor_mode="true",
        visitor_stt=EnvironmentVariable("DORI_VISITOR_STT", default_value="azure"),
        stt_audio_input_mode="auto",
        real_map="",
        real_named_goals_file="",
        real_use_joystick="false",
        enable_stt="auto",
        enable_dashboard="true",
        enable_perception="false",
        tts_playback_mode="local_only",
        tts_engine="gcp",
        whisper_model="",
        use_external_llm="true",
        llm_model="gemini-3.5-flash-lite",
        require_user_tracking="false",
    )
    choices = {
        "dori_mode": ["desktop", "sim", "real"],
        "visitor_mode": ["true", "false"],
        "visitor_stt": ["azure", "whisper"],
        "enable_stt": ["auto", "true", "false"],
        "use_external_llm": ["true", "false"],
        "stt_audio_input_mode": ["auto", "microphone", "topic"],
    }
    return LaunchDescription(
        [DeclareLaunchArgument(k, default_value=v, choices=choices.get(k)) for k, v in defaults.items()]
        + [OpaqueFunction(function=setup)]
    )

"""Default app launch, explicit robot voice, and provider checks without hardware."""
import importlib.util
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock, patch

import pytest
from launch import LaunchContext
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def bringup(monkeypatch, tmp_path):
    monkeypatch.delenv("DORI_VISITOR_STT", raising=False)
    monkeypatch.setenv("ROS_LOG_DIR", str(tmp_path / "ros-logs"))
    path = ROOT / "ros2_ws/src/dori_bringup/launch/bringup.launch.py"
    spec = importlib.util.spec_from_file_location("bringup_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "get_package_share_directory",
                        lambda name: str(ROOT / "ros2_ws/src" / name))
    # Humble's LaunchContext.environment is os.environ, not a private mapping.
    with patch.dict(os.environ):
        yield module


def describe(module, **overrides):
    context = LaunchContext()
    context.launch_configurations.update(overrides)
    for action in module.generate_launch_description().entities:
        if isinstance(action, DeclareLaunchArgument):
            action.execute(context)
    actions = module.setup(context)
    includes = {}
    for action in actions:
        if isinstance(action, SetEnvironmentVariable):
            action.execute(context)
        elif isinstance(action, IncludeLaunchDescription):
            action.launch_description_source.get_launch_description(context)
            path = action.launch_description_source.location
            includes[Path(path).name] = dict(action.launch_arguments)
    return context, includes


def test_default_starts_app_gateway_and_voice_without_local_stt(bringup, monkeypatch):
    check = Mock()
    monkeypatch.setattr(bringup, "check_visitor", check)
    context, includes = describe(bringup)
    assert set(includes) == {"voice.launch.py", "interaction.launch.py", "dashboard.launch.py"}
    assert includes["voice.launch.py"]["enable_stt"] == "false"
    assert includes["voice.launch.py"]["use_external_llm"] == "true"
    assert includes["voice.launch.py"]["llm_model"] == "gemini-3.5-flash-lite"
    assert includes["voice.launch.py"]["stt_audio_input_mode"] == "topic"
    assert includes["interaction.launch.py"]["visitor_mode"] == "true"
    assert context.environment["DORI_VISITOR_STT"] == "azure"
    assert context.environment["DORI_SESSION_ROOT"] == str(ROOT)
    check.assert_called_once_with(context, ROOT, "azure", str(ROOT / ".state/voice/whisper-small"))


def test_robot_microphone_is_an_explicit_opt_in(bringup, monkeypatch):
    check = Mock()
    monkeypatch.setattr(bringup, "check_visitor", check)
    _, includes = describe(bringup, visitor_mode="false")
    assert includes["voice.launch.py"]["enable_stt"] == "true"
    assert includes["voice.launch.py"]["stt_audio_input_mode"] == "microphone"
    assert includes["interaction.launch.py"]["visitor_mode"] == "false"
    assert "dashboard.launch.py" in includes
    check.assert_not_called()


@pytest.mark.parametrize("from_env", [False, True])
def test_whisper_selects_matching_gateway_and_topic_stt(bringup, monkeypatch, from_env):
    check = Mock()
    monkeypatch.setattr(bringup, "check_visitor", check)
    if from_env:
        monkeypatch.setenv("DORI_VISITOR_STT", "whisper")
    context, includes = describe(bringup, **({} if from_env else {"visitor_stt": "whisper"}))
    assert context.environment["DORI_VISITOR_STT"] == "whisper"
    assert includes["voice.launch.py"]["enable_stt"] == "true"
    assert includes["voice.launch.py"]["stt_audio_input_mode"] == "topic"
    model = includes["voice.launch.py"]["whisper_model"]
    assert model == str(ROOT / ".state/voice/whisper-small")
    check.assert_called_once_with(context, ROOT, "whisper", model)


def test_provider_argument_overrides_environment(bringup, monkeypatch):
    monkeypatch.setenv("DORI_VISITOR_STT", "whisper")
    monkeypatch.setattr(bringup, "check_visitor", Mock())
    context, includes = describe(bringup, visitor_stt="azure")
    assert context.environment["DORI_VISITOR_STT"] == "azure"
    assert includes["voice.launch.py"]["enable_stt"] == "false"


def test_voice_without_gateway_needs_no_cloud_credentials(bringup, monkeypatch):
    check = Mock()
    monkeypatch.setattr(bringup, "check_visitor", check)
    _, includes = describe(bringup, enable_dashboard="false")
    assert set(includes) == {"voice.launch.py", "interaction.launch.py"}
    check.assert_not_called()


@pytest.mark.parametrize("visitor,enable_stt,mode", [
    ("true", "false", "topic"), ("false", "true", "microphone"),
])
def test_hardware_requires_explicit_mode_and_receives_voice_profile(
        bringup, monkeypatch, visitor, enable_stt, mode):
    monkeypatch.setattr(bringup, "check_visitor", Mock())
    _, includes = describe(bringup, dori_mode="real", visitor_mode=visitor,
                           real_map="/maps/campus.yaml")
    assert set(includes) == {"hardware.launch.py"}
    assert includes["hardware.launch.py"]["map"] == "/maps/campus.yaml"
    assert includes["hardware.launch.py"]["visitor_mode"] == visitor
    assert includes["hardware.launch.py"]["enable_stt"] == enable_stt
    assert includes["hardware.launch.py"]["stt_audio_input_mode"] == mode
    assert includes["hardware.launch.py"]["enable_dashboard"] == "true"


def test_real_device_overrides_reach_hardware_launch(bringup, monkeypatch):
    monkeypatch.setattr(bringup, "check_visitor", Mock())
    ports = dict(can_interface="can7", can_wait_timeout="2.5", dxl_port="/dev/dxl", imu_port="/dev/imu", lidar_port="/dev/lidar")
    _, includes = describe(bringup, dori_mode="real", **{"real_" + k: v for k, v in ports.items()})
    for key, value in ports.items():
        assert includes["hardware.launch.py"][key] == value


@pytest.mark.parametrize("overrides,match", [
    ({"stt_audio_input_mode": "microphone"}, "requires stt_audio_input_mode"),
    ({"visitor_stt": "whisper", "enable_stt": "false"}, "requires enable_stt"),
    ({"visitor_stt": "invalid"}, "invalid"),
])
def test_invalid_visitor_profile_fails_before_starting_services(bringup, overrides, match):
    with pytest.raises((ValueError, RuntimeError), match=match):
        describe(bringup, **overrides)


def test_preflight_uses_gateway_python_and_checkout_root(bringup, monkeypatch):
    run = Mock()
    monkeypatch.setattr(bringup.subprocess, "run", run)
    context = LaunchContext()
    context.environment["DORI_WS"] = "/wrong/root"
    bringup.check_visitor(context, ROOT, "azure", "unused")
    args, kwargs = run.call_args
    assert args[0][0] == str(ROOT / ".venv/bin/python")
    assert "load_config()" in args[0][-1]
    assert kwargs["env"]["DORI_WS"] == str(ROOT)
    assert kwargs["capture_output"] and kwargs["check"]
    assert kwargs["timeout"] == 15


def test_preflight_reports_setup_action_without_provider_secrets(bringup, monkeypatch):
    run = Mock(side_effect=subprocess.CalledProcessError(1, ["python"], stderr="private-key"))
    monkeypatch.setattr(bringup.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="scripts/build.sh") as error:
        bringup.check_visitor(LaunchContext(), ROOT, "azure", "unused")
    assert "private-key" not in str(error.value)


def test_whisper_preflight_rejects_missing_model(bringup, tmp_path):
    with pytest.raises(RuntimeError, match="prepare_voice.sh --topic-only"):
        bringup.check_visitor(LaunchContext(), ROOT, "whisper", str(tmp_path))


@pytest.mark.parametrize("mode,child", [("desktop", "voice.launch.py"), ("real", "hardware.launch.py")])
@pytest.mark.parametrize("enabled", ["true", "false"])
def test_llm_settings_are_forwarded_to_desktop_and_hardware(bringup, monkeypatch, mode, child, enabled):
    monkeypatch.setattr(bringup, "check_visitor", Mock())
    _, includes = describe(bringup, dori_mode=mode, use_external_llm=enabled, llm_model="gemini-test")
    assert includes[child]["use_external_llm"] == enabled
    assert includes[child]["llm_model"] == "gemini-test"

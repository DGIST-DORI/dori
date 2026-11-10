"""Default robot profile, explicit desktop mode, and voice provider checks."""
import importlib.util
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock, patch

import pytest
from launch import LaunchContext
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, SetEnvironmentVariable, GroupAction
from dori_bringup import configuration, launch_support

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def bringup(monkeypatch, tmp_path):
    monkeypatch.delenv("DORI_VISITOR_STT", raising=False)
    monkeypatch.setenv("ROS_LOG_DIR", str(tmp_path / "ros-logs"))
    module = launch_support
    monkeypatch.setattr(module, "get_package_share_directory",
                        lambda name: str(ROOT / "ros2_ws/src" / name))
    monkeypatch.setattr(configuration, "get_package_share_directory",
                        lambda name: str(ROOT / "ros2_ws/src" / name))
    # Humble's LaunchContext.environment is os.environ, not a private mapping.
    with patch.dict(os.environ):
        yield module


def describe(module, **overrides):
    context = LaunchContext()
    context.launch_configurations.update(overrides)
    for action in configuration.arguments():
        action.execute(context)
    actions = module.prepare(context)
    if context.launch_configurations["dori_mode"] == "robot":
        spec = importlib.util.spec_from_file_location("entry_under_test", ROOT / "ros2_ws/src/dori_bringup/launch/bringup.launch.py")
        entry = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(entry)
        actions += entry.setup(context)
    else:
        actions += module.services(context)
    includes = {}
    for action in actions:
        if isinstance(action, GroupAction):
            action = next(child for child in action.get_sub_entities() if isinstance(child, IncludeLaunchDescription))
        if isinstance(action, SetEnvironmentVariable):
            action.execute(context)
        elif isinstance(action, IncludeLaunchDescription):
            action.launch_description_source.get_launch_description(context)
            path = action.launch_description_source.location
            includes[Path(path).name] = dict(action.launch_arguments)
    return context, includes


def test_default_selects_robot_with_visitor_voice(bringup, monkeypatch):
    check = Mock()
    monkeypatch.setattr(bringup, "check_visitor", check)
    context, includes = describe(bringup, map="/maps/campus.yaml")
    assert context.launch_configurations["dori_mode"] == "robot"
    assert set(includes) == {"robot.launch.py"}
    hardware = includes["robot.launch.py"]
    assert hardware["map"] == "/maps/campus.yaml"
    assert hardware["visitor_mode"] == "true"
    assert hardware["enable_dashboard"] == "true"
    assert hardware["enable_stt"] == "false"
    assert hardware["stt_audio_input_mode"] == "topic"
    assert hardware["use_external_llm"] == "true"
    assert hardware["llm_model"] == "gemini-3.5-flash-lite"
    check.assert_called_once_with(context, ROOT, "azure", str(ROOT / ".state/voice/whisper-small"))


@pytest.mark.parametrize("overrides", [{}, {"dori_mode": "robot"}])
def test_robot_requires_map_before_provider_preflight(bringup, monkeypatch, overrides):
    check = Mock()
    monkeypatch.setattr(bringup, "check_visitor", check)
    with pytest.raises(ValueError, match="Robot mode requires map:="):
        describe(bringup, **overrides)
    check.assert_not_called()


@pytest.mark.parametrize("mode", ["sim", "real", "hardware"])
def test_retired_modes_are_rejected_before_provider_preflight(bringup, monkeypatch, mode):
    check = Mock()
    monkeypatch.setattr(bringup, "check_visitor", check)
    with pytest.raises(RuntimeError, match="dori_mode"):
        describe(bringup, dori_mode=mode)
    check.assert_not_called()


def test_desktop_starts_app_gateway_and_voice_without_local_stt(bringup, monkeypatch):
    check = Mock()
    monkeypatch.setattr(bringup, "check_visitor", check)
    context, includes = describe(bringup, dori_mode="desktop")
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
    _, includes = describe(bringup, dori_mode="desktop", visitor_mode="false")
    assert includes["voice.launch.py"]["enable_stt"] == "true"
    assert includes["voice.launch.py"]["stt_audio_input_mode"] == "microphone"
    assert includes["interaction.launch.py"]["visitor_mode"] == "false"
    assert "dashboard.launch.py" in includes
    check.assert_not_called()


@pytest.mark.parametrize("from_env", [False, True])
@pytest.mark.parametrize("mode,child", [("desktop", "voice.launch.py"), ("robot", "robot.launch.py")])
def test_whisper_selects_matching_gateway_and_topic_stt(bringup, monkeypatch, from_env, mode, child):
    check = Mock()
    monkeypatch.setattr(bringup, "check_visitor", check)
    if from_env:
        monkeypatch.setenv("DORI_VISITOR_STT", "whisper")
    context, includes = describe(bringup, dori_mode=mode, map="/maps/campus.yaml",
                                 **({} if from_env else {"visitor_stt": "whisper"}))
    assert context.environment["DORI_VISITOR_STT"] == "whisper"
    assert includes[child]["enable_stt"] == "true"
    assert includes[child]["stt_audio_input_mode"] == "topic"
    model = includes[child]["whisper_model"]
    assert model == str(ROOT / ".state/voice/whisper-small")
    check.assert_called_once_with(context, ROOT, "whisper", model)


def test_provider_argument_overrides_environment(bringup, monkeypatch):
    monkeypatch.setenv("DORI_VISITOR_STT", "whisper")
    monkeypatch.setattr(bringup, "check_visitor", Mock())
    context, includes = describe(bringup, dori_mode="desktop", visitor_stt="azure")
    assert context.environment["DORI_VISITOR_STT"] == "azure"
    assert includes["voice.launch.py"]["enable_stt"] == "false"


def test_voice_without_gateway_needs_no_cloud_credentials(bringup, monkeypatch):
    check = Mock()
    monkeypatch.setattr(bringup, "check_visitor", check)
    _, includes = describe(bringup, dori_mode="desktop", enable_dashboard="false")
    assert set(includes) == {"voice.launch.py", "interaction.launch.py"}
    check.assert_not_called()


@pytest.mark.parametrize("visitor,enable_stt,mode", [
    ("true", "false", "topic"), ("false", "true", "microphone"),
])
def test_robot_receives_voice_profile(
        bringup, monkeypatch, visitor, enable_stt, mode):
    monkeypatch.setattr(bringup, "check_visitor", Mock())
    _, includes = describe(bringup, dori_mode="robot", visitor_mode=visitor,
                           map="/maps/campus.yaml")
    assert set(includes) == {"robot.launch.py"}
    assert includes["robot.launch.py"]["map"] == "/maps/campus.yaml"
    assert includes["robot.launch.py"]["visitor_mode"] == visitor
    assert includes["robot.launch.py"]["enable_stt"] == enable_stt
    assert includes["robot.launch.py"]["stt_audio_input_mode"] == mode
    assert includes["robot.launch.py"]["enable_dashboard"] == "true"


def test_navigation_and_device_overrides_reach_robot_launch(bringup, monkeypatch):
    monkeypatch.setattr(bringup, "check_visitor", Mock())
    overrides = dict(map="/maps/campus.yaml", named_goals_file="/maps/goals.json", use_joystick="true",
                     can_interface="can7", can_wait_timeout="2.5", dxl_port="/dev/dxl",
                     dxl_baudrate="115200", imu_port="/dev/imu", lidar_port="/dev/lidar")
    _, includes = describe(bringup, **overrides)
    for key, value in overrides.items():
        assert includes["robot.launch.py"][key] == value


@pytest.mark.parametrize("overrides,match", [
    ({"stt_audio_input_mode": "microphone"}, "requires stt_audio_input_mode"),
    ({"visitor_stt": "whisper", "enable_stt": "false"}, "requires enable_stt"),
    ({"visitor_stt": "invalid"}, "invalid"),
])
def test_invalid_visitor_profile_fails_before_starting_services(bringup, overrides, match):
    with pytest.raises((ValueError, RuntimeError), match=match):
        describe(bringup, dori_mode="desktop", **overrides)


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


@pytest.mark.parametrize("mode,child", [("desktop", "voice.launch.py"), ("robot", "robot.launch.py")])
@pytest.mark.parametrize("enabled", ["true", "false"])
def test_llm_settings_are_forwarded_to_desktop_and_robot(bringup, monkeypatch, mode, child, enabled):
    monkeypatch.setattr(bringup, "check_visitor", Mock())
    _, includes = describe(bringup, dori_mode=mode, map="/maps/campus.yaml",
                           use_external_llm=enabled, llm_model="gemini-test")
    assert includes[child]["use_external_llm"] == enabled
    assert includes[child]["llm_model"] == "gemini-test"


@pytest.mark.parametrize("mode", ["robot", "desktop"])
def test_perception_uses_same_optional_feature_defaults(bringup, monkeypatch, mode):
    monkeypatch.setattr(bringup, "check_visitor", Mock())
    context, _ = describe(bringup, dori_mode=mode, map="/maps/campus.yaml", enable_perception="true")
    actions = bringup.services(context, robot=mode == "robot")
    includes = [next(child for child in action.get_sub_entities() if isinstance(child, IncludeLaunchDescription))
                for action in actions]
    for action in includes:
        action.launch_description_source.get_launch_description(context)
    perception = next(action for action in includes if "perception.launch.py" in str(action.launch_description_source.location))
    params = dict(perception.launch_arguments)
    assert params["enable_gesture"] == params["enable_expression"] == params["enable_landmark"] == "false"


def test_robot_cannot_disable_required_front_perception(bringup, monkeypatch):
    check = Mock()
    monkeypatch.setattr(bringup, "check_visitor", check)
    with pytest.raises(ValueError, match="requires front camera"):
        describe(bringup, map="/maps/campus.yaml", enable_perception="false")
    check.assert_not_called()

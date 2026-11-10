"""Deployment configuration precedence and file resolution through real launch actions."""
from pathlib import Path

import pytest
from launch import LaunchContext
from dori_bringup.configuration import arguments, read_config, repo_root


def resolve(**overrides):
    context = LaunchContext()
    context.launch_configurations.update(overrides)
    for action in arguments():
        action.execute(context)
    return context.launch_configurations


def test_cli_profile_common_and_defaults_have_explicit_precedence(tmp_path):
    config = tmp_path / "robot.yaml"
    config.write_text("""common:
  llm_model: common-model
  enable_gesture: true
  named_goals_file: goals.json
robot:
  llm_model: robot-model
  map: maps/site.yaml
desktop:
  llm_model: desktop-model
""")
    values = resolve(config_file=str(config), llm_model="cli-model")
    assert values["llm_model"] == "cli-model"
    assert values["enable_gesture"] == "true"
    assert values["enable_expression"] == "false"
    assert values["map"] == str(tmp_path / "maps/site.yaml")
    assert values["named_goals_file"] == str(tmp_path / "goals.json")
    assert resolve(config_file=str(config))["llm_model"] == "robot-model"
    desktop = resolve(config_file=str(config), dori_mode="desktop")
    assert desktop["llm_model"] == "desktop-model" and desktop["map"] == ""


@pytest.mark.parametrize("content", [
    "[]", "common: []", "common: {enable_dashboard: perhaps}",
    "robot: {real_map: old.yaml}", "common: {map: null}",
    "robot: {startup_timeout: .nan}", "unknown: {}",
    "robot: {map: '${UNKNOWN}/map.yaml'}",
])
def test_invalid_config_fails_before_any_process_is_constructed(tmp_path, content):
    config = tmp_path / "bad.yaml"
    config.write_text(content)
    with pytest.raises(ValueError):
        resolve(config_file=str(config))


def test_checkout_placeholder_and_model_ids_are_resolved_without_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DORI_ROOT", "/wrong/checkout")
    config = tmp_path / "robot.yaml"
    config.write_text("""robot:
  map: ${DORI_ROOT}/maps/site.yaml
  person_model: yolov8n.pt
  landmark_model: ./models/landmark.pt
""")
    values = read_config(config, "robot")
    assert values["map"] == str(repo_root() / "maps/site.yaml")
    assert values["person_model"] == "yolov8n.pt"
    assert values["landmark_model"] == str(tmp_path / "models/landmark.pt")


def test_missing_config_is_not_silently_ignored(tmp_path):
    with pytest.raises(FileNotFoundError):
        resolve(config_file=str(tmp_path / "missing.yaml"))


def test_shipped_example_resolves_existing_map():
    root = repo_root()
    config = root / "ros2_ws/src/dori_bringup/config/robot.example.yaml"
    values = read_config(config, "robot")
    assert Path(values["map"]).is_file()
    assert values["enable_gesture"] == "false"

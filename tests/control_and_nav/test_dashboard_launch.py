"""Expand dashboard launch and packaging metadata without executing processes."""
import importlib.util
from pathlib import Path
import runpy
from unittest.mock import Mock

import pytest
from launch import LaunchContext
from launch.utilities import normalize_to_list_of_substitutions, perform_substitutions
from launch_ros.actions import Node
from launch_ros.utilities import evaluate_parameters
import setuptools

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'ros2_ws/src/dori_dashboard'


def load_launch(monkeypatch):
    spec = importlib.util.spec_from_file_location('dashboard_review_launch', PACKAGE / 'launch/dashboard.launch.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'get_package_share_directory', lambda _: str(PACKAGE))
    return module


def command(context, action):
    return [perform_substitutions(context, normalize_to_list_of_substitutions(part)) for part in action.cmd]


@pytest.fixture(autouse=True)
def isolate_ros_logs(monkeypatch, tmp_path):
    monkeypatch.setenv('ROS_LOG_DIR', str(tmp_path / 'ros-log'))


def test_launch_injects_same_secret_and_rejects_missing_or_short_one(monkeypatch):
    module = load_launch(monkeypatch)
    context = LaunchContext()
    context.launch_configurations['dashboard_url'] = ''
    for token in ('', 'default-internal-secret'):
        monkeypatch.setenv('DORI_INTERNAL_TOKEN', token)
        with pytest.raises(RuntimeError):
            module._make_server_actions(context)
    monkeypatch.setenv('DORI_INTERNAL_TOKEN', 'test-only-internal-secret-at-least-32')
    actions = module._make_server_actions(context)
    commands = [command(context, action) for action in actions]
    assert [Path(cmd[1]).name for cmd in commands] == ['backend_api.py', 'bridge_api.py']
    if (ROOT / '.venv/bin/python').is_file():
        assert all(cmd[0] == str(ROOT / '.venv/bin/python') for cmd in commands)
    for action in actions:
        env = {perform_substitutions(context, key): perform_substitutions(context, value)
               for key, value in action.process_description.additional_env}
        assert env['DORI_INTERNAL_TOKEN'] == 'test-only-internal-secret-at-least-32'


def test_tunnel_only_exposes_dashboard_and_rosbridge_binds_loopback(monkeypatch, tmp_path):
    module = load_launch(monkeypatch)
    monkeypatch.setattr(module.shutil, 'which', lambda _: '/usr/bin/cloudflared')
    context = LaunchContext()
    context.launch_configurations['tunnel'] = 'true'
    actions = module._make_tunnel_actions(context)
    assert len(actions) == 1
    cmd = ' '.join(command(context, actions[0]))
    assert 'localhost:3000' in cmd
    assert '9090' not in cmd
    (tmp_path / 'web').mkdir()
    monkeypatch.setattr(module, 'get_package_share_directory', lambda _: str(tmp_path))
    description = module.generate_launch_description()
    bridge = next(action for action in description.entities
                  if isinstance(action, Node) and
                  perform_substitutions(context, normalize_to_list_of_substitutions(action.node_package)) == 'rosbridge_server')
    assert {'port': 9090, 'address': '127.0.0.1'} in evaluate_parameters(context, bridge._Node__parameters)


def test_installed_scripts_include_bridge_and_shared_modules(monkeypatch):
    setup = Mock()
    monkeypatch.setattr(setuptools, 'setup', setup)
    monkeypatch.chdir(PACKAGE)
    runpy.run_path(str(PACKAGE / 'setup.py'))
    files = dict(setup.call_args.kwargs['data_files'])['share/dori_dashboard/scripts']
    assert {'backend_api.py', 'bridge_api.py', 'control_contract.py', 'internal_auth.py'} <= {Path(path).name for path in files}
    assert all(Path(path).is_file() for path in files)
    assert 'PyJWT[crypto]>=2.10.1,<3' in setup.call_args.kwargs['install_requires']

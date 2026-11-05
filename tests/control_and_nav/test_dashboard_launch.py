"""Expand dashboard launch and packaging metadata without executing processes."""
import importlib.util
from pathlib import Path
import runpy
from unittest.mock import Mock
from unittest.mock import patch

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
        assert env['DORI_WS'] == str(ROOT)


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
    assert {'backend_api.py', 'bridge_api.py', 'control_contract.py', 'internal_auth.py',
            'access_config.py'} <= {Path(path).name for path in files}
    assert all(Path(path).is_file() for path in files)
    assert 'PyJWT[crypto]>=2.10.1,<3' in setup.call_args.kwargs['install_requires']


def test_standalone_dashboard_labels_all_descendants_for_shutdown(monkeypatch, tmp_path):
    import os
    from launch.actions import SetEnvironmentVariable

    module = load_launch(monkeypatch)
    (tmp_path / 'web').mkdir()
    monkeypatch.setattr(module, 'get_package_share_directory', lambda _: str(tmp_path))
    monkeypatch.setattr(module, '_resolve_repo_root', lambda _: str(ROOT))
    description = module.generate_launch_description()
    marker = description.entities[0]
    assert isinstance(marker, SetEnvironmentVariable)
    with patch.dict(os.environ):
        context = LaunchContext()
        marker.execute(context)
        assert context.environment['DORI_SESSION_ROOT'] == str(ROOT)


def test_navigation_viewer_starts_by_default_on_loopback(monkeypatch, tmp_path):
    from launch.actions import DeclareLaunchArgument
    from xml.etree import ElementTree

    module = load_launch(monkeypatch)
    context = LaunchContext()
    (tmp_path / 'web').mkdir()
    monkeypatch.setattr(module, 'get_package_share_directory', lambda _: str(tmp_path))
    description = module.generate_launch_description()
    for action in description.entities:
        if isinstance(action, DeclareLaunchArgument):
            action.execute(context)
    assert context.launch_configurations['enable_navigation_viewer'] == 'true'
    monkeypatch.setattr(module, 'get_package_share_directory', lambda _: str(PACKAGE))
    node_factory = Mock(wraps=Node)
    monkeypatch.setattr(module, 'Node', node_factory)
    actions = module._make_navigation_viewer_actions(context)
    assert len(actions) == 1
    config = node_factory.call_args.kwargs
    assert config['package'] == 'dori_navigation'
    assert config['executable'] == 'web_viewer.py'
    options = dict(zip(config['arguments'][::2], config['arguments'][1::2]))
    assert options == {
        '--host': '127.0.0.1', '--port': '8080', '--user-port': '0',
        '--mode': 'auto', '--goals-file': str(ROOT / 'maps/web_goals.json'),
    }
    assert config['respawn'] is True
    assert config['respawn_delay'] == 2.0
    assert config['additional_env']['DORI_WS'] == str(ROOT)
    manifest = ElementTree.parse(PACKAGE / 'package.xml').getroot()
    assert 'dori_navigation' in [entry.text for entry in manifest.findall('exec_depend')]


def test_external_viewer_disables_dashboard_owner(monkeypatch):
    module = load_launch(monkeypatch)
    context = LaunchContext()
    context.launch_configurations['enable_navigation_viewer'] = 'false'
    node_factory = Mock()
    monkeypatch.setattr(module, 'Node', node_factory)
    assert module._make_navigation_viewer_actions(context) == []
    node_factory.assert_not_called()


def test_hardware_launch_keeps_exactly_one_viewer(monkeypatch):
    from launch.actions import DeclareLaunchArgument

    path = ROOT / 'ros2_ws/src/dori_bringup/launch/hardware.launch.py'
    spec = importlib.util.spec_from_file_location('hardware_viewer_ownership', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'get_package_share_directory',
                        lambda name: str(ROOT / 'ros2_ws/src' / name))
    context = LaunchContext()
    context.launch_configurations['map'] = str(ROOT / 'maps/live_navigation_20261023_1938.yaml')
    for action in module.generate_launch_description().entities:
        if isinstance(action, DeclareLaunchArgument):
            action.execute(context)
    includes = Mock(wraps=module.include)
    monkeypatch.setattr(module, 'include', includes)
    actions = module.setup(context)
    includes.assert_any_call('dori_dashboard', 'dashboard.launch.py',
                             {'enable_navigation_viewer': 'false'})
    viewers = [action for action in actions if isinstance(action, Node)
               and perform_substitutions(context, normalize_to_list_of_substitutions(
                   action.node_executable)) == 'web_viewer.py']
    assert len(viewers) == 1

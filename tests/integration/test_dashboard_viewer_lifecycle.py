"""Start only the dashboard's viewer in an isolated ROS domain; never hardware."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def test_viewer_starts_respawns_and_stops_with_launch(tmp_path):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    pid_file = tmp_path / 'viewer-pids'
    bootstrap = tmp_path / 'launch_viewer.py'
    bootstrap.write_text('''
import importlib.util
from pathlib import Path
import sys
from launch import LaunchContext, LaunchDescription, LaunchService
from launch.actions import RegisterEventHandler
from launch.event_handlers import OnProcessStart
from launch_ros.actions import Node

root, port, pid_file, goals = sys.argv[1:]
path = Path(root) / 'ros2_ws/src/dori_dashboard/launch/dashboard.launch.py'
spec = importlib.util.spec_from_file_location('viewer_launch', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.get_package_share_directory = lambda name: str(Path(root) / 'ros2_ws/src' / name)
def isolated_node(**kwargs):
    arguments = kwargs['arguments']
    arguments[arguments.index('--port') + 1] = port
    arguments[arguments.index('--goals-file') + 1] = goals
    return Node(**kwargs)
module.Node = isolated_node
context = LaunchContext()
context.launch_configurations['enable_navigation_viewer'] = 'true'
viewer, = module._make_navigation_viewer_actions(context)
def started(event, context):
    with open(pid_file, 'a') as output:
        output.write(str(event.pid) + '\\n')
service = LaunchService()
service.include_launch_description(LaunchDescription([
    RegisterEventHandler(OnProcessStart(target_action=viewer, on_start=started)), viewer,
]))
sys.exit(service.run())
''')
    env = dict(os.environ, ROS_DOMAIN_ID='198', ROS_LOCALHOST_ONLY='1',
               ROS_LOG_DIR=str(tmp_path / 'ros-logs'))
    # Avoid host-specific DDS discovery profiles in this isolated test.
    for key in ('FASTRTPS_DEFAULT_PROFILES_FILE', 'FASTDDS_DEFAULT_PROFILES_FILE', 'CYCLONEDDS_URI'):
        env.pop(key, None)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f'http://127.0.0.1:{port}/api/state'

    def wait_state(previous=None):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            assert process.poll() is None, log_file.read_text()
            try:
                with opener.open(url, timeout=.5) as response:
                    state = json.load(response)
                if state.get('instance_id') and state['instance_id'] != previous:
                    return state
            except (OSError, urllib.error.URLError, ValueError):
                pass
            time.sleep(.1)
        raise AssertionError(log_file.read_text())

    log_file = tmp_path / 'launch.log'
    with log_file.open('w') as output:
        process = subprocess.Popen(
            [sys.executable, str(bootstrap), str(ROOT), str(port), str(pid_file), str(tmp_path / 'goals.json')],
            env=env, stdout=output, stderr=subprocess.STDOUT,
        )
        try:
            first = wait_state()
            assert first['control_owner'] is None
            assert first['mode'] in ('auto', 'monitor')
            first_pid = int(pid_file.read_text().splitlines()[-1])
            os.kill(first_pid, signal.SIGTERM)
            second = wait_state(first['instance_id'])
            assert second['control_owner'] is None
            pids = pid_file.read_text().splitlines()
            assert len(pids) == 2 and pids[0] != pids[1]
        finally:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        assert process.returncode == 0, log_file.read_text()
    time.sleep(2.2)  # Longer than the configured respawn delay.
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1', port)) != 0
    assert len(pid_file.read_text().splitlines()) == 2

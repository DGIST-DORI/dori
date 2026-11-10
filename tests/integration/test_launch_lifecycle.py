"""Exercise the production failure handler without constructing any hardware node."""
import importlib.util
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest
from launch import LaunchContext, LaunchDescription, LaunchService
from launch.actions import DeclareLaunchArgument, ExecuteProcess, RegisterEventHandler, TimerAction, EmitEvent
from launch.event_handlers import OnShutdown
from launch.events import Shutdown

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('name,code,expected', [
    ('critical_probe',0,'stopping robot session'),
    ('critical_probe',3,'stopping robot session'),
    ('spawner_probe',0,'test deadline'),
])
def test_process_exit_propagates_to_session_shutdown(name,code,expected,monkeypatch):
    path=ROOT/'ros2_ws/src/dori_bringup/launch/robot.launch.py'
    spec=importlib.util.spec_from_file_location('dori_launch_under_test',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'validate_devices', lambda *args, **kwargs: None)
    context=LaunchContext()
    context.launch_configurations["visitor_mode"]="false"
    context.launch_configurations['map']=str(ROOT/'maps/live_navigation_20261023_1938.yaml')
    for action in module.generate_launch_description().entities:
        if isinstance(action,DeclareLaunchArgument): action.execute(context)
    handler=module.setup(context)[0]  # Create descriptions only; never execute hardware includes.
    reasons=[]
    service=LaunchService()
    service.include_launch_description(LaunchDescription([
        handler,
        RegisterEventHandler(OnShutdown(on_shutdown=lambda event,ctx: reasons.append(event.reason))),
        ExecuteProcess(cmd=[sys.executable,'-c',f'raise SystemExit({code})'],name=name),
        TimerAction(period=.5,actions=[EmitEvent(event=Shutdown(reason='test deadline'))]),
    ]))
    service.run()
    assert any(expected in reason for reason in reasons),reasons


@pytest.mark.skipif(os.environ.get('ROS_DOMAIN_ID') != '97' or os.environ.get('ROS_LOCALHOST_ONLY') != '1',
                    reason='Requires isolated ROS domain 97 on localhost')
def test_python_node_sigint_exits_without_double_shutdown_error(tmp_path):
    log = tmp_path / 'emotion.log'
    with log.open('w') as output:
        process = subprocess.Popen(
            [sys.executable, '-c', 'from dori_hri.emotion_publisher_node import main; main()'],
            stdout=output, stderr=output,
        )
        try:
            deadline = time.monotonic() + 10
            while 'Emotion Publisher Node started' not in log.read_text():
                assert process.poll() is None, log.read_text()
                assert time.monotonic() < deadline, log.read_text()
                time.sleep(.05)
            process.send_signal(signal.SIGINT)
            assert process.wait(timeout=5) == 0, log.read_text()
            assert 'Traceback' not in log.read_text()
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

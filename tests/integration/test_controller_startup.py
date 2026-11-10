"""Production startup with real controller_manager and mock_components hardware."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import pytest
import yaml
from ament_index_python.packages import get_package_share_directory

pytestmark = pytest.mark.skipif(
    os.environ.get("ROS_DOMAIN_ID") != "97" or os.environ.get("ROS_LOCALHOST_ONLY") != "1",
    reason="Requires isolated ROS domain 97 on localhost",
)


def test_controller_setup_reaches_expected_states_without_hardware(tmp_path):
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from controller_manager_msgs.srv import ListControllers

    share = Path(get_package_share_directory("dori_hardware"))
    xml = subprocess.check_output(["xacro", str(share / "config/cubemars_mit.urdf.xacro")], text=True)
    robot = ET.fromstring(xml)
    robot.find("ros2_control/hardware/plugin").text = "mock_components/GenericSystem"
    # Only the mock plugin is ever loaded; no CAN, USB, or motor nodes exist.
    config = tmp_path / "robot.yaml"
    config.write_text(yaml.safe_dump({"controller_manager": {"ros__parameters": {
        "robot_description": ET.tostring(robot, encoding="unicode"),
    }}}))
    code = """
import sys
from launch import LaunchDescription, LaunchService
from launch_ros.actions import Node
from dori_hardware.controller_startup import controller_startup_actions
service = LaunchService()
service.include_launch_description(LaunchDescription([
    Node(package='controller_manager', executable='ros2_control_node',
         parameters=sys.argv[1:], output='screen'),
    *controller_startup_actions(),
]))
raise SystemExit(service.run())
"""
    log = tmp_path / "controllers.log"
    with log.open("w") as output:
        process = subprocess.Popen([sys.executable, "-c", code, str(config),
                                    str(share / "config/bldc_controllers.yaml")],
                                   stdout=output, stderr=output, start_new_session=True)
        context = rclpy.Context()
        rclpy.init(context=context)
        node = rclpy.create_node("test_controller_states", context=context)
        executor = SingleThreadedExecutor(context=context)
        executor.add_node(node)
        try:
            deadline = time.monotonic() + 60
            while "DORI controllers ready" not in log.read_text():
                assert process.poll() is None, log.read_text()
                assert time.monotonic() < deadline, log.read_text()
                time.sleep(.1)
            client = node.create_client(ListControllers, "/controller_manager/list_controllers")
            assert client.wait_for_service(timeout_sec=5)
            future = client.call_async(ListControllers.Request())
            executor.spin_until_future_complete(future, timeout_sec=10)
            assert future.result() is not None, log.read_text()
            assert {c.name: c.state for c in future.result().controller} == {
                "joint_state_broadcaster": "active",
                "left_bldc_drive_controller": "active",
                "right_bldc_drive_controller": "active",
                "left_bldc_effort_controller": "inactive",
                "right_bldc_effort_controller": "inactive",
                "bldc_position_controller": "inactive",
            }
            assert "already loaded" not in log.read_text()
            assert "Resource conflict" not in log.read_text()
        finally:
            executor.shutdown()
            node.destroy_node()
            rclpy.try_shutdown(context=context)
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)


@pytest.mark.parametrize("exit_code", [0, 1])
def test_initializer_failure_stops_session_without_reporting_ready(tmp_path, exit_code):
    # Substitute the initializer process; retain the actual lifecycle handler.
    script = """
import sys
from launch import LaunchDescription, LaunchService
from launch.actions import ExecuteProcess
from dori_hardware import controller_startup
controller_startup.Node = lambda **kwargs: ExecuteProcess(
    cmd=[sys.executable, '-c', 'raise SystemExit(' + sys.argv[1] + ')'], name='controller_spawner')
service = LaunchService()
service.include_launch_description(LaunchDescription(controller_startup.controller_startup_actions()))
service.run()
"""
    result = subprocess.run([sys.executable, "-c", script, str(exit_code)],
                            capture_output=True, text=True, timeout=10)
    assert ("DORI controllers ready" in result.stdout) == (exit_code == 0)

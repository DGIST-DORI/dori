"""Nav2 lifecycle activation with synthetic TF in an isolated, actuator-free graph."""
import os
from pathlib import Path
import signal
import subprocess
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get('ROS_DOMAIN_ID') != '97' or os.environ.get('ROS_LOCALHOST_ONLY') != '1',
    reason='Requires isolated ROS domain 97 on localhost',
)


def test_nav2_waits_for_localization_then_activates_without_motor_processes(tmp_path):
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from geometry_msgs.msg import TransformStamped
    from lifecycle_msgs.srv import GetState
    from tf2_ros import TransformBroadcaster

    root = Path(__file__).resolve().parents[2]
    context = rclpy.Context()
    rclpy.init(context=context)
    node = rclpy.create_node('test_localization', context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(node)
    broadcaster = TransformBroadcaster(node)
    localized = [False]
    def transforms():
        if not localized[0]:
            return
        messages = []
        for parent, child in [('map', 'odom'), ('odom', 'base_link'), ('base_link', 'laser')]:
            tf = TransformStamped()
            tf.header.stamp = node.get_clock().now().to_msg()
            tf.header.frame_id = parent
            tf.child_frame_id = child
            tf.transform.rotation.w = 1.0
            messages.append(tf)
        broadcaster.sendTransform(messages)
    node.create_timer(.1, transforms)
    log = tmp_path / 'navigation.log'
    # This entrypoint launches only navigation; no CAN/serial driver or actuator
    # exists in this ROS domain. No goal or velocity command is sent by the test.
    command = ['ros2', 'launch', 'dori_navigation', 'real_nav2.launch.py',
               'map:=' + str(root / 'maps/live_navigation_20261023_1938.yaml'),
               'sigterm_timeout:=15']
    with log.open('w') as output:
        process = subprocess.Popen(command, stdout=output, stderr=output, start_new_session=True)
        try:
            deadline = time.monotonic() + 90
            while log.read_text().count('Managed nodes are active') < 2:
                assert process.poll() is None, log.read_text()
                assert time.monotonic() < deadline, log.read_text()
                executor.spin_once(timeout_sec=.1)
            assert 'Localization ready' not in log.read_text()
            localized[0] = True
            while 'Navigation active' not in log.read_text():
                assert process.poll() is None, log.read_text()
                assert time.monotonic() < deadline, log.read_text()
                executor.spin_once(timeout_sec=.1)
            for name in ['map_server', 'amcl', 'controller_server', 'planner_server',
                         'behavior_server', 'bt_navigator', 'velocity_smoother']:
                client = node.create_client(GetState, '/' + name + '/get_state')
                assert client.wait_for_service(timeout_sec=5), name
                future = client.call_async(GetState.Request())
                executor.spin_until_future_complete(future, timeout_sec=5)
                assert future.result().current_state.label == 'active', name
            assert 'No critics defined' not in log.read_text()
            assert 'base_footprint' not in log.read_text()
        finally:
            if process.poll() is None:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=25)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
            executor.shutdown()
            node.destroy_node()
            rclpy.try_shutdown(context=context)

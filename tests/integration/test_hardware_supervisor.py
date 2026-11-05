"""Opt-in, isolated ROS test with a real supervisor and synthetic telemetry only.

Build dori_supervisor into a separate build directory, then run with
DORI_SUPERVISOR_TEST_BINARY=/path/to/mode_manager_node ROS_DOMAIN_ID=97
ROS_LOCALHOST_ONLY=1. This test never launches hardware drivers.
"""
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest

PACKAGE = Path(__file__).resolve().parents[2] / 'ros2_ws/src/dori_dashboard/dori_dashboard'
sys.path.insert(0, str(PACKAGE))


@unittest.skipUnless(os.environ.get('DORI_SUPERVISOR_TEST_BINARY')
                     and os.environ.get('ROS_DOMAIN_ID') == '97'
                     and os.environ.get('ROS_LOCALHOST_ONLY') == '1',
                     'Requires an explicitly isolated ROS test environment')
class HardwareSupervisorIntegration(unittest.TestCase):
    def test_namespace_telemetry_transform_rejection_stop_and_resume(self):
        import rclpy
        from rclpy.node import Node
        from rclpy.qos import QoSProfile, DurabilityPolicy
        from std_msgs.msg import Int32, Bool
        from sensor_msgs.msg import JointState
        from geometry_msgs.msg import Twist
        from dori_msgs.msg import CommandFeedback
        from bridge_api import BridgeNode
        from hardware_control import HardwareControlMixin, JOINTS
        from control_contract import validate_control

        class TestBridge(HardwareControlMixin, Node):
            request_stop = BridgeNode.request_stop
            control_action = BridgeNode.control_action
            _on_mode = BridgeNode._on_mode

            def _on_state(self, msg):
                BridgeNode._on_state(self, msg)
                self.received_states.append(msg.data)

            def __init__(self):
                super().__init__('hardware_dashboard_test', namespace='/dori')
                self._control_lock = threading.RLock()
                self._mode = self._action_state = None
                self._move_command = None
                self._move_deadline = 0
                self.received_states = []
                self.pub_manual = self.create_publisher(Twist, '/manual/cmd_vel', 10)
                self.pub_stop = self.create_publisher(Bool, '/emergency_stop', 10)
                self.pub_mode = self.create_publisher(Int32, '/control_mode_cmd', 10)
                self.pub_cancel = self.create_publisher(Bool, '/dori/hri/cancel', 10)
                self._init_hardware_control()
                latch = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
                self.create_subscription(Int32, '/system/control_mode', self._on_mode, latch)
                self.create_subscription(Int32, '/system/action_state', self._on_state, latch)

        rclpy.init()
        node = TestBridge()
        process = subprocess.Popen([os.environ['DORI_SUPERVISOR_TEST_BINARY']],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            def until(predicate, timeout=8):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    rclpy.spin_once(node, timeout_sec=.02)
                    if predicate():
                        return
                self.fail('Timed out waiting for isolated supervisor state')

            transforms = []
            node.create_subscription(Int32, '/transform/request', lambda msg: transforms.append(msg.data), 10)
            feedback = node.create_publisher(CommandFeedback, '/transform/command_feedback', 10)
            status = node.create_publisher(Int32, '/transform/status', 10)
            joint_pubs = {topic: node.create_publisher(JointState, topic, 10)
                          for _, _, topic in JOINTS}
            until(lambda: node.hardware_state()['supervisor_available']
                  and feedback.get_subscription_count() >= 2
                  and status.get_subscription_count() >= 2
                  and all(pub.get_subscription_count() for pub in joint_pubs.values())
                  and node.hardware_state()['transform_available'])
            self.assertEqual(node._mode, 0)
            self.assertEqual(node._action_state, 0)
            self.assertFalse(node.hardware_state()['live_enabled'])
            before = len(node.received_states)
            node.execute_control('set_live_control', {'enabled': True, 'control_epoch': node._control_epoch})
            until(lambda: len(node.received_states) > before and node.received_states[-1] == 4)
            self.assertTrue(node.hardware_state()['live_enabled'])
            node.execute_control('resume', {'control_epoch': node._control_epoch})
            until(lambda: node._action_state == 0)
            for name, _, topic in JOINTS:
                joint_pubs[topic].publish(JointState(name=[name], position=[0.0]))
            until(lambda: all(j['fresh'] for j in node.hardware_state()['joints']))
            node.execute_control(*validate_control({'action': 'transform', 'params': {'pose': 'A', 'control_epoch': node._control_epoch}}))
            until(lambda: transforms == [1] and node._action_state == 2)
            feedback.publish(CommandFeedback(accepted=False, code=211, message='Already in target pose'))
            until(lambda: node._action_state == 0)

            status.publish(Int32(data=1))
            until(lambda: node._action_state == 2)
            node.request_stop()
            until(lambda: node._action_state == 4)
            feedback.publish(CommandFeedback(accepted=False, code=211, message='Rejected while stopped'))
            for _ in range(10):
                rclpy.spin_once(node, timeout_sec=.02)
            self.assertEqual(node._action_state, 4)
            status.publish(Int32(data=2))
            until(lambda: node.hardware_state()['values'].get('transform/status', {}).get('value') == 2)
            node.execute_control('resume', {'control_epoch': node._control_epoch})
            until(lambda: node._action_state == 2)
            self.assertEqual(node._mode, 0)
            status.publish(Int32(data=3))
            until(lambda: node._action_state == 0)
            before = len(node.received_states)
            node.execute_control('set_live_control', {'enabled': False})
            until(lambda: len(node.received_states) > before and node.received_states[-1] == 4)
            self.assertFalse(node.hardware_state()['live_enabled'])
            self.assertFalse(node.execute_control('transform', {'pose': 'B'})['executed'])
            self.assertEqual(transforms, [1])
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill(); process.wait(timeout=5)
            node.destroy_node()
            rclpy.shutdown()


if __name__ == '__main__':
    unittest.main()

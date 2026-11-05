"""Hardware dashboard regressions. Publishers and telemetry are entirely mocked."""
import json
from pathlib import Path
import sys
import threading
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException

PACKAGE = Path(__file__).resolve().parents[2] / 'ros2_ws/src/dori_dashboard/dori_dashboard'
sys.path.insert(0, str(PACKAGE))
import bridge_api as bridge
from control_contract import validate_control
from hardware_control import HardwareControlMixin, JOINTS


class HardwareControlTests(unittest.TestCase):
    def setUp(self):
        self.node = SimpleNamespace(
            _control_lock=threading.RLock(), _mode=0, _action_state=0,
            _move_command=None, _move_deadline=0, pub_stop=Mock(), pub_cancel=Mock(),
            pub_mode=Mock(), pub_manual=Mock(), create_publisher=Mock(side_effect=lambda *a: Mock()),
            create_subscription=Mock(), count_publishers=Mock(return_value=1),
            count_subscribers=Mock(return_value=1),
        )
        for cls in (HardwareControlMixin, bridge.BridgeNode):
            names = (('_init_hardware_control', '_record_joints', '_record_value', '_record_feedback',
                      '_record_error', 'hardware_state', 'hardware_action', 'execute_control') if cls is HardwareControlMixin
                     else ('request_stop', 'control_action', '_control_tick', '_on_state', '_on_mode'))
            for name in names:
                setattr(self.node, name, MethodType(getattr(cls, name), self.node))
        self.node._init_hardware_control()
        for pub in (self.node.pub_stop, self.node.pub_manual, self.node.pub_mode,
                    self.node.pub_resume, self.node.pub_transform):
            pub.get_subscription_count.return_value = 1

    def feedback(self, timestamp=10):
        with patch('hardware_control.time.monotonic', return_value=timestamp):
            for name, _, topic in JOINTS:
                self.node._record_joints(topic, SimpleNamespace(name=[name], position=[.1], velocity=[], effort=[]))

    def test_hardware_topics_stay_global_under_dori_namespace(self):
        subscriptions = [call.args[1] for call in self.node.create_subscription.call_args_list]
        self.assertTrue(all(topic.startswith('/') for topic in subscriptions))
        self.assertIn('/joint_states', subscriptions)
        self.assertIn('/dxl_joint_states', subscriptions)
        self.assertIn('/motor4/joint_states', subscriptions)
        self.assertEqual([call.args[1] for call in self.node.create_publisher.call_args_list],
                         ['/emergency_go', '/manual/transform_cmd'])

    def test_telemetry_is_source_scoped_finite_and_expires(self):
        self.feedback()
        self.node._record_joints('/joint_states', SimpleNamespace(name=['motor_4_joint'], position=[9], velocity=[], effort=[]))
        with patch('hardware_control.time.monotonic', return_value=10.1):
            state = self.node.hardware_state()
        self.assertTrue(all(j['fresh'] for j in state['joints']))
        self.assertEqual(state['joints'][3]['position'], .1)
        self.assertIsNone(state['joints'][3]['effort'])
        with patch('hardware_control.time.monotonic', return_value=11):
            self.assertFalse(any(j['fresh'] for j in self.node.hardware_state()['joints']))
            self.node._record_joints('/joint_states', SimpleNamespace(name=['left_wheel_joint'],
                                    position=[float('nan')], velocity=[float('inf')], effort=[]))
            state = self.node.hardware_state()
        self.assertFalse(state['joints'][0]['fresh'])
        json.dumps(state, allow_nan=False)

    def test_transform_requires_feedback_manual_mode_and_controller(self):
        with self.assertRaises(HTTPException):
            self.node.control_action('transform', {'pose': 'B'})
        self.feedback()
        with patch('hardware_control.time.monotonic', return_value=10.1):
            self.node._mode = 1
            with self.assertRaises(HTTPException):
                self.node.control_action('transform', {'pose': 'B'})
            self.node._mode = 0
            self.node.count_subscribers.return_value = 0
            with self.assertRaises(HTTPException):
                self.node.control_action('transform', {'pose': 'B'})
            self.node.count_subscribers.return_value = 1
            self.node.control_action('transform', {'pose': 'B'})
        self.assertEqual(self.node.pub_transform.publish.call_args.args[0].data, 2)
        self.assertEqual(self.node._action_state, 2)
        self.node.pub_manual.publish.assert_not_called()

    def test_resume_is_explicit_and_waits_for_supervisor_state(self):
        with self.assertRaises(HTTPException):
            self.node.control_action('resume', {})
        self.node.request_stop()
        self.node.control_action('resume', {})
        self.assertTrue(self.node.pub_resume.publish.call_args.args[0].data)
        self.assertFalse(self.node._stop_latched)
        self.assertIsNone(self.node._action_state)
        with self.assertRaises(HTTPException):
            self.node.control_action('move', {'linear_x': .1, 'angular_z': 0.0})
        self.node._on_state(SimpleNamespace(data=0))
        self.node.control_action('move', {'linear_x': .1, 'angular_z': 0.0})
        self.node.pub_manual.publish.assert_called_once()

    def test_stop_invalidates_delayed_move_resume_transform_and_mode_requests(self):
        epoch = self.node._control_epoch
        self.node.request_stop()
        self.node._on_state(SimpleNamespace(data=0))  # Delayed pre-stop state cannot clear our latch.
        for action, params in (('move', {'linear_x': .1, 'angular_z': 0.0}), ('resume', {}),
                               ('transform', {'pose': 'B'}), ('set_mode', {'mode': 'auto'})):
            with self.subTest(action=action), self.assertRaises(HTTPException):
                self.node.control_action(action, {**params, 'control_epoch': epoch})
        with self.assertRaises(HTTPException):
            self.node.control_action('move', {'linear_x': .1, 'angular_z': 0.0})
        self.node.pub_manual.publish.assert_not_called()

    def test_second_dashboard_cannot_overwrite_active_drive(self):
        params = {'linear_x': .1, 'angular_z': 0.0, 'client_id': 'first'}
        self.node.control_action('move', params)
        with self.assertRaises(HTTPException):
            self.node.control_action('move', {**params, 'client_id': 'second'})
        self.assertEqual(self.node.hardware_state()['move_owner'], 'first')
        self.node.request_stop()
        self.assertIsNone(self.node.hardware_state()['move_owner'])

    def test_validation_rejects_invalid_postures_and_stale_request_token_shapes(self):
        for pose in (None, True, 1, [], 'C', 'A; shutdown'):
            with self.subTest(pose=pose), self.assertRaises(HTTPException):
                validate_control({'action': 'transform', 'params': {'pose': pose}})
        for epoch in (True, '', 'g' * 32, 'a' * 33):
            with self.assertRaises(HTTPException):
                validate_control({'action': 'resume', 'params': {'control_epoch': epoch}})
        self.assertEqual(validate_control({'action': 'transform', 'params': {'pose': 'b'}}), ('transform', {'pose': 'B'}))

    def test_live_switch_stops_invalidates_old_requests_and_can_disable_with_stale_state(self):
        epoch = self.node._control_epoch
        move = {'linear_x': .1, 'angular_z': 0.0, 'control_epoch': epoch}
        self.assertFalse(self.node.execute_control('move', move)['executed'])
        self.node.pub_manual.publish.assert_not_called()
        result = self.node.execute_control('set_live_control', {'enabled': True, 'control_epoch': epoch})
        self.assertTrue(result['control_state']['live_enabled'])
        self.assertEqual(result['control_state']['executor'], 'bridge')
        self.assertTrue(self.node._stop_latched)
        self.node.pub_stop.publish.assert_called_once()
        self.assertNotEqual(self.node._control_epoch, epoch)
        with self.assertRaises(HTTPException):
            self.node.execute_control('move', move)
        with self.assertRaises(HTTPException):
            self.node.execute_control('resume', {})
        move['control_epoch'] = self.node._control_epoch
        self.node.execute_control('resume', {'control_epoch': self.node._control_epoch})
        self.node._on_state(SimpleNamespace(data=0))
        self.node.execute_control('move', move)
        self.node.pub_manual.publish.assert_called_once()
        result = self.node.execute_control('set_live_control', {'enabled': False, 'control_epoch': epoch})
        self.assertFalse(result['control_state']['live_enabled'])
        self.assertEqual(result['control_state']['executor'], 'dry-run')
        self.assertIsNone(self.node._move_command)
        self.assertIsNone(self.node._move_owner)
        self.node._control_tick()
        self.assertEqual(self.node.pub_manual.publish.call_count, 1)
        with self.assertRaises(HTTPException):
            self.node.execute_control('set_live_control', {'enabled': True, 'control_epoch': epoch})

    def test_enabling_requires_connected_supervisor_and_no_competing_input(self):
        params = {'enabled': True, 'control_epoch': self.node._control_epoch}
        self.node.pub_stop.get_subscription_count.return_value = 0
        with self.assertRaises(HTTPException):
            self.node.execute_control('set_live_control', params)
        self.node.pub_stop.get_subscription_count.return_value = 1
        self.node.count_publishers.side_effect = lambda topic: 2 if topic == '/manual/cmd_vel' else 1
        with self.assertRaises(HTTPException):
            self.node.execute_control('set_live_control', params)
        self.assertFalse(self.node._live_control_enabled)
        self.node.pub_stop.publish.assert_not_called()

    def test_switch_is_global_idempotent_and_restart_returns_to_simulation(self):
        params = {'enabled': True, 'control_epoch': self.node._control_epoch, 'client_id': 'first'}
        self.node.execute_control('set_live_control', params)
        current = self.node._control_epoch
        result = self.node.execute_control('set_live_control', {**params, 'control_epoch': current, 'client_id': 'second'})
        self.assertFalse(result['changed'])
        self.assertTrue(self.node.hardware_state()['live_enabled'])
        self.node.pub_stop.publish.assert_called_once()
        self.node._init_hardware_control()
        self.assertFalse(self.node.hardware_state()['live_enabled'])
        self.assertNotEqual(self.node._control_epoch, current)

    def test_resume_rejects_competing_joystick_input(self):
        self.node.request_stop()
        self.node.count_publishers.side_effect = lambda topic: 2 if topic == '/manual/cmd_vel' else 1
        with self.assertRaises(HTTPException):
            self.node.control_action('resume', {})
        self.node.pub_resume.publish.assert_not_called()

    def test_stop_or_disable_in_simulation_invalidates_delayed_enable_without_publishing(self):
        for action, params in (('stop', {}), ('set_live_control', {'enabled': False})):
            epoch = self.node._control_epoch
            self.node.execute_control(action, params)
            with self.assertRaises(HTTPException):
                self.node.execute_control('set_live_control', {'enabled': True, 'control_epoch': epoch})
            self.assertFalse(self.node._live_control_enabled)
        self.node.pub_stop.publish.assert_not_called()


if __name__ == '__main__':
    unittest.main()

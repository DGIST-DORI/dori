"""Stationary scan consensus and cancellation of stale automatic corrections."""
from concurrent.futures import Future
import json
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock
import numpy as np
import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped,TransformStamped
from nav_msgs.msg import Odometry
from rclpy.time import Time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/robot_navigation'))
from dori_web.auto_alignment import alignment_candidate
from dori_web.bridge import WebBridge
from dori_web.map_matcher import MapMatcher
from test_map_matcher import MapSearch


class ScanConsensus(unittest.TestCase):
    def test_small_drift_is_recovered_from_three_noisy_scans(self):
        matcher,points,true=MapSearch().scene()
        rng=np.random.default_rng(42)
        scans=[points+rng.normal(0,.008,points.shape) for _ in range(3)]
        result=alignment_candidate(matcher,scans,true+np.array([.20,-.10,.04]))
        self.assertEqual(result['decision'],'correct',result)
        self.assertLess(np.linalg.norm(np.array(result['pose'])[:2]-true[:2]),.05)
        self.assertLess(result['rotation_deg'],8.)
        json.dumps(result,allow_nan=False)

    def test_already_aligned_and_large_drift_do_not_reset_pose(self):
        matcher,points,true=MapSearch().scene()
        self.assertEqual(alignment_candidate(matcher,[points]*3,true)['decision'],'aligned')
        result=alignment_candidate(matcher,[points]*3,true+np.array([.4,0.,0.]))
        self.assertEqual(result['decision'],'manual_required',result)

    def test_disagreeing_scans_and_ambiguous_corridor_are_rejected(self):
        matcher,points,true=MapSearch().scene()
        result=alignment_candidate(matcher,[points,points,points+np.array([.25,0.])],true+np.array([.1,0.,0.]))
        self.assertEqual(result['decision'],'uncertain',result)
        grid=np.zeros((100,400),dtype=int);grid[10,:]=100;grid[90,:]=100
        points=np.concatenate([np.column_stack((np.linspace(-3.,3.,150),np.full(150,y))) for y in [-1.975,2.025]])
        result=alignment_candidate(MapMatcher(grid,.05,[0.,0.,0.]),[points]*3,[5.,2.5,0.])
        self.assertEqual(result['decision'],'uncertain',result)


class AutomaticLifecycle(unittest.TestCase):
    @classmethod
    def setUpClass(cls):rclpy.init()
    @classmethod
    def tearDownClass(cls):rclpy.shutdown()
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.node=WebBridge('navigation',Path(self.directory.name)/'goals.json')
        n=self.node;self.auto=n.auto_alignment
        n.values.update(action=1,active=False,enabled=False)
        n.nav_lifecycle.problems=lambda:[]
        n.messages['odom']=Odometry();n.age=lambda _: .05
        stamp=n.get_clock().now();tf=TransformStamped();tf.header.stamp=stamp.to_msg()
        n.buffer.lookup_transform=Mock(return_value=tf);n.tf_pose=Mock(return_value=[1.,2.,.1])
        n.joints={name:dict(position=0.,stamp=stamp.nanoseconds/1e9) for name in ('left_wheel_joint','right_wheel_joint')}
        n.initial_pub=Mock();n.mode_pub=Mock();n.local_pose.reset=Mock()
        self.auto.nomotion=Mock();self.auto.nomotion.service_is_ready.return_value=False
        self.auto.task=Future();self.auto.task.set_result(dict(decision='correct',pose=[1.1,2.,.1],translation_m=.1,rotation_deg=0.,score=.85,message='test'))
        self.auto.map_version=n.map_version;self.auto.search_generation=self.auto.manual_generation
        self.auto.search_pose=[1.,2.,.1];self.auto.next_check=time.monotonic()-1
    def tearDown(self):self.node.destroy_node();self.directory.cleanup()

    def test_idle_correction_changes_only_amcl_reference(self):
        self.auto.tick()
        self.assertEqual(self.node.initial_pub.publish.call_count,1)
        self.assertEqual(self.auto.applied,0);self.assertTrue(self.auto.busy)
        self.node.mode_pub.publish.assert_not_called();self.node.local_pose.reset.call_async.assert_not_called()
        message=self.node.initial_pub.publish.call_args.args[0]
        self.assertEqual(message.header.frame_id,'map');self.assertAlmostEqual(message.pose.pose.position.x,1.1)
        message.header.stamp=Time(nanoseconds=self.auto.own_stamp+1).to_msg();self.node.local_pose.amcl=message
        self.auto.tick();self.assertEqual(self.auto.applied,0)  # AMCL can precede the rendered TF.
        self.node.tf_pose.return_value=[1.1,2.,.1]
        self.auto.tick();self.assertEqual(self.auto.applied,1);self.assertFalse(self.auto.busy)

    def test_active_navigation_or_stale_feedback_discards_result(self):
        self.node.values['active']=True;self.auto.tick();self.node.initial_pub.publish.assert_not_called()
        self.assertIsNone(self.auto.task)
        self.node.values['active']=False;self.node.age=lambda _:2.
        self.assertIsNone(self.auto.idle_pose())

    def test_manual_pose_or_map_change_invalidates_result(self):
        self.auto.initial_pose_received(PoseWithCovarianceStamped());self.auto.tick()
        self.node.initial_pub.publish.assert_not_called()
        self.assertIsNone(self.auto.task)

    def test_changed_map_and_robot_pose_discard_old_result(self):
        self.node.map_version+=1;self.auto.tick();self.node.initial_pub.publish.assert_not_called()

    def test_pending_goal_and_nan_velocity_are_not_idle(self):
        self.node.last_goal_request=time.monotonic();self.assertIsNone(self.auto.idle_pose())
        self.node.last_goal_request=-math.inf;self.node.messages['odom'].twist.twist.linear.x=float('nan')
        self.assertIsNone(self.auto.idle_pose())

    def test_idle_auto_mode_can_be_checked_without_disabling_control(self):
        self.node.values['enabled']=True;self.node.owner='test-browser'
        self.auto.tick();self.assertEqual(self.node.initial_pub.publish.call_count,1)
        self.node.mode_pub.publish.assert_not_called()

    def test_missing_wheel_feedback_is_not_stationary(self):
        self.node.joints={};self.auto.tick();self.node.initial_pub.publish.assert_not_called()

    def test_scan_velocity_noise_does_not_override_stationary_positions(self):
        self.node.messages['odom'].twist.twist.linear.x=.053
        self.node.messages['odom'].twist.twist.angular.z=-.026
        self.assertIsNotNone(self.auto.idle_pose())
        self.assertTrue(self.auto.stationary([1.,2.,.1]))
        self.assertTrue(self.auto.stationary([1.004,1.997,.102]))
        self.auto.tick();self.assertEqual(self.node.initial_pub.publish.call_count,1)

    def test_actual_wheel_or_body_movement_cancels_search(self):
        self.auto.stationary([1.,2.,.1])
        self.node.joints['left_wheel_joint']['position']=.1
        self.auto.tick();self.node.initial_pub.publish.assert_not_called()
        self.assertIsNone(self.auto.task)
        self.auto.stationary([1.,2.,.1])
        self.assertFalse(self.auto.stationary([1.04,2.,.1]))


if __name__=='__main__':unittest.main()

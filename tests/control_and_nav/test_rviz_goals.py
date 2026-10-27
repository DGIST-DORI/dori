import math,sys,unittest
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ros2_ws/src/robot_navigation/scripts'))
from geometry_msgs.msg import PoseStamped
from std_msgs.msg import Int32, Bool
from rclpy.time import Time
from rclpy.clock import ClockType
from navigation_contract import rviz_goal_point
from named_goal_bridge import NamedGoalBridge

class RvizGoals(unittest.TestCase):
    def setUp(self):
        self.n=NamedGoalBridge.__new__(NamedGoalBridge)
        self.n.points={};self.n.enabled=True;self.n.sequence=0;self.n.pending=None
        self.n.goal_handle=None;self.n.cancelling=False;self.n.sending=False
        self.n.arrival_xy=.35;self.n.arrival_yaw=math.pi
        self.n.active_arrival_xy=.35;self.n.relative_arrival_xy=.15
        self.n.relative_behavior_tree='/test/relative.xml';self.n.goal_source='web'
        self.n.retry_delay=5.;self.n.max_retries=3;self.n.retry_at=0.;self.n.retry_count=0;self.n.retry_reported=0.
        self.n.hardware_inhibited=False;self.n.active_sequence=None
        self.n.retry_pub=Mock();self.n.markers=Mock();self.n.feedback_pub=Mock()
        self.n.enabled_pub=Mock();self.n.active_pub=Mock();self.n.publish_status=Mock();self.n.client=Mock()
        self.n.get_clock=lambda:SimpleNamespace(now=lambda:SimpleNamespace(to_msg=lambda:self.pose.header.stamp))
        self.pose=PoseStamped();self.pose.header.frame_id='map';self.pose.pose.position.x=2.
        self.pose.pose.orientation.w=1.
    def test_valid_point_no_csv(self):
        self.pose.pose.orientation.z=math.sin(math.pi/4);self.pose.pose.orientation.w=math.cos(math.pi/4)
        p=rviz_goal_point(self.pose);self.assertEqual(p['x'],2.);self.assertAlmostEqual(p['yaw_deg'],90)
        self.n.on_rviz_goal(self.pose);self.n.tick()
        g=self.n.client.send_goal_async.call_args.args[0]
        self.assertEqual(g.destination.header.frame_id,'map');self.assertEqual(g.destination.pose.position.x,2.)
        self.assertAlmostEqual(g.destination.pose.orientation.z,math.sin(math.pi/4))
    def test_mode_off_and_invalid_pose_do_not_send(self):
        self.n.enabled=False;self.n.on_rviz_goal(self.pose);self.assertIsNone(self.n.pending)
        self.n.enabled=True
        for field in ('frame','nan','quaternion','height'):
            p=PoseStamped();p.header.frame_id='map';p.pose.orientation.w=1.
            if field=='frame':p.header.frame_id='odom'
            if field=='nan':p.pose.position.x=float('nan')
            if field=='quaternion':p.pose.orientation.w=0.
            if field=='height':p.pose.position.z=2.
            self.n.on_rviz_goal(p);self.assertIsNone(self.n.pending)
    def test_replacement_waits_for_old_terminal_result(self):
        old=Mock();self.n.goal_handle=old
        self.n.on_rviz_goal(self.pose);self.n.tick()
        old.cancel_goal_async.assert_called_once();self.n.client.send_goal_async.assert_not_called()
        self.pose.pose.position.x=3.;self.n.on_rviz_goal(self.pose)
        self.n.on_result(old, 'old', 0, Mock(result=lambda:SimpleNamespace(status=5)))
        self.n.tick();self.assertEqual(self.n.client.send_goal_async.call_args.args[0].destination.pose.position.x,3.)
    def test_mode_stop_invalidates_inflight_acceptance(self):
        self.n.on_rviz_goal(self.pose);seq=self.n.sequence
        self.n.on_mode(Int32(data=0));self.assertIsNone(self.n.pending)
        handle=Mock();handle.accepted=True
        self.n.on_response(seq,'rviz_goal',Mock(),Mock(result=lambda:handle))
        handle.cancel_goal_async.assert_called_once()
        self.assertTrue(all(not c.args[0].data for c in self.n.active_pub.publish.call_args_list))
    def test_false_nav2_success_is_not_reported_as_arrival(self):
        handle=Mock();self.n.goal_handle=handle;self.n.arrival_verified=lambda:False
        self.n.on_result(handle,'rviz_goal',self.n.sequence,Mock(result=lambda:SimpleNamespace(status=4)))
        self.n.publish_status.assert_any_call('arrival_unverified:rviz_goal')
        self.n.publish_status.assert_called_with('finished:rviz_goal:status=6')

    def test_approximate_heading_is_verified_without_accepting_wrong_position(self):
        self.n.active_target=self.pose
        feedback=PoseStamped();feedback.header.frame_id='map';feedback.header.stamp=Time(seconds=10.).to_msg()
        feedback.pose.position.x=2.1;feedback.pose.orientation.z=math.sin(math.radians(35)/2);feedback.pose.orientation.w=math.cos(math.radians(35)/2)
        self.n.goal_feedback=feedback;self.n.get_clock=lambda:SimpleNamespace(now=lambda:Time(seconds=10.1,clock_type=ClockType.ROS_TIME))
        self.assertTrue(self.n.arrival_verified())
        feedback.pose.position.x=2.5;self.assertFalse(self.n.arrival_verified())
        feedback.pose.position.x=2.1;feedback.pose.orientation.z=math.sin(math.radians(90)/2);feedback.pose.orientation.w=math.cos(math.radians(90)/2)
        self.assertTrue(self.n.arrival_verified())  # Saved direction does not force a loop.

    def active_goal(self):
        self.n.on_rviz_goal(self.pose);self.n.tick()
        handle=Mock();handle.accepted=True
        self.n.on_response(self.n.sequence,'rviz_goal',SimpleNamespace(destination=self.pose,precise=False),Mock(result=lambda:handle))
        return handle

    def abort(self,handle):
        self.n.on_result(handle,'rviz_goal',self.n.sequence,Mock(result=lambda:SimpleNamespace(status=6)))

    def test_aborted_goal_waits_then_retries_same_coordinate(self):
        with patch('named_goal_bridge.time.monotonic',return_value=100.) as clock:
            handle=self.active_goal();self.abort(handle)
            self.assertEqual(self.n.retry_at,105.);self.assertEqual(self.n.retry_count,1)
            self.n.tick();self.assertEqual(self.n.client.send_goal_async.call_count,1)
            clock.return_value=105.1;self.n.tick()
            self.assertEqual(self.n.client.send_goal_async.call_count,2)
            self.assertEqual(self.n.client.send_goal_async.call_args.args[0].destination.pose.position.x,2.)

    def test_stop_estop_and_hardware_cancel_pending_retry(self):
        for stop in (lambda:self.n.on_mode(Int32(data=0)),lambda:self.n.on_estop(Bool(data=True)),lambda:self.n.on_action(Int32(data=4))):
            self.setUp();self.abort(self.active_goal());stop()
            self.assertIsNone(self.n.pending);self.assertEqual(self.n.retry_at,0.)
            self.n.tick();self.assertEqual(self.n.client.send_goal_async.call_count,1)

    def test_new_goal_replaces_retry_without_inheriting_delay(self):
        self.abort(self.active_goal());self.pose.pose.position.x=3.;self.n.on_rviz_goal(self.pose)
        self.assertEqual(self.n.retry_at,0.);self.assertEqual(self.n.retry_count,0)
        self.n.tick();self.assertEqual(self.n.client.send_goal_async.call_args.args[0].destination.pose.position.x,3.)

    def test_retry_limit_and_cancellation_do_not_restart(self):
        handle=self.active_goal();self.n.retry_count=3;self.abort(handle)
        self.assertIsNone(self.n.pending)
        self.n.publish_status.assert_called_with('finished:rviz_goal:status=6')
        self.setUp();handle=self.active_goal();self.n.cancelling=True;self.abort(handle)
        self.assertIsNone(self.n.pending)

    def test_old_feedback_cannot_validate_new_goal(self):
        self.active_goal();self.n.goal_feedback=None
        self.n.on_feedback(self.n.sequence-1,Mock())
        self.assertIsNone(self.n.goal_feedback)

    def test_relative_goal_selects_precise_checker_and_retries_fixed_target(self):
        self.n.on_relative_goal(self.pose);self.n.tick()
        first=self.n.client.send_goal_async.call_args.args[0]
        self.assertEqual(first.precise,True)
        handle=Mock();handle.accepted=True
        self.n.on_response(self.n.sequence,'relative_goal',first,Mock(result=lambda:handle))
        self.assertEqual(self.n.active_arrival_xy,.15)
        self.n.on_result(handle,'relative_goal',self.n.sequence,Mock(result=lambda:SimpleNamespace(status=6)))
        self.n.retry_at=1.;self.n.tick()
        next_goal=self.n.client.send_goal_async.call_args.args[0]
        self.assertEqual(next_goal.destination.pose.position.x,first.destination.pose.position.x)
        self.assertEqual(next_goal.precise,first.precise)

    def test_goal_rejected_does_not_enable_motion(self):
        self.n.on_rviz_goal(self.pose)
        self.n.on_response(self.n.sequence,'rviz_goal',Mock(),Mock(result=lambda:SimpleNamespace(accepted=False)))
        self.assertIsNone(self.n.goal_handle)
if __name__=='__main__':unittest.main()

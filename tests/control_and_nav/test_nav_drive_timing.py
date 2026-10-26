"""Regression tests for independently delivered /odom and /tf; no hardware."""
import math,sys,unittest
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/robot_navigation/scripts'))
from nav_drive_bridge import NavDriveBridge
from nav_msgs.msg import Odometry
from geometry_msgs.msg import TransformStamped,Twist
from sensor_msgs.msg import LaserScan
from control_msgs.msg import DynamicJointState, InterfaceValue
from rclpy.time import Time
from rclpy.clock import ClockType
from tf2_ros import TransformException
import time

class TimingTests(unittest.TestCase):
 def setUp(self):
  self.n=NavDriveBridge.__new__(NavDriveBridge);self.now=100.
  self.n.get_clock=lambda:SimpleNamespace(now=lambda:Time(seconds=self.now,clock_type=ClockType.ROS_TIME))
  self.n.enabled=True;self.n.control_mode=1;self.n.scale_verified=True;self.n.params_time=time.monotonic()
  self.n.action_state=1;self.n.goal_active=True;self.n.odom=None;self.n.odom_history=deque(maxlen=20)
  self.n.odom_timeout=.25;self.n.scan_timeout=.5;self.n.cmd_timeout=.25
  self.n.cmd=Twist();self.n.cmd.linear.x=.1;self.n.cmd_time=time.monotonic()
  self.n.scan=LaserScan();self.n.scan.header.frame_id='laser';self.n.scan.range_min=.1;self.n.scan.range_max=10.;self.n.scan.ranges=[2.]
  self.stamp(self.n.scan,100.)
  self.n.hardware_feedback=DynamicJointState();self.stamp(self.n.hardware_feedback,100.)
  self.n.hardware_feedback.joint_names=['left_wheel_joint','right_wheel_joint']
  self.n.hardware_feedback.interface_values=[InterfaceValue(interface_names=['feedback_age'],values=[.001]) for _ in range(2)]
  self.available={};self.n.buffer=Mock();self.n.buffer.lookup_transform=self.lookup
 def stamp(self,m,sec):m.header.stamp=Time(seconds=sec,clock_type=ClockType.ROS_TIME).to_msg()
 def feed(self,sec,with_tf=True):
  o=Odometry();self.stamp(o,sec);o.header.frame_id='odom';o.child_frame_id='base_link';o.pose.pose.orientation.w=1.
  o.pose.pose.position.x=sec-99.
  self.n.on_odom(o)
  if with_tf:
   t=TransformStamped();t.header=o.header;t.child_frame_id='base_link';t.transform.translation.x=o.pose.pose.position.x;t.transform.rotation.w=1.
   self.available[Time.from_msg(o.header.stamp).nanoseconds]=t
  return o
 def lookup(self,parent,child,stamp):
  if parent=='odom':
   if stamp.nanoseconds not in self.available:raise TransformException('TF has not arrived yet')
   return self.available[stamp.nanoseconds]
  t=TransformStamped();self.stamp(t,self.now);t.transform.rotation.w=1.;return t
 def test_new_odom_before_tf_does_not_interrupt_valid_pair(self):
  self.feed(99.96);new=self.feed(99.98,False)
  self.assertEqual(self.n.reason(),'driving')
  self.assertAlmostEqual(self.n.paired_odom()[0].pose.pose.position.x,.96)
  self.feed(99.98);self.assertEqual(self.n.paired_odom()[0].header.stamp,new.header.stamp)
 def test_tf_outage_expires_even_with_fresh_odom(self):
  self.feed(99.70);self.feed(99.98,False)
  self.assertEqual(self.n.reason(),'waiting_for_tf')
 def test_stale_odom_still_stops(self):
  self.feed(99.7);self.assertEqual(self.n.reason(),'stale_odom')
 def test_disagreement_is_not_hidden_by_older_pair(self):
  self.feed(99.96);o=self.feed(99.98)
  self.available[Time.from_msg(o.header.stamp).nanoseconds].transform.translation.x+=.1
  self.assertEqual(self.n.reason(),'odom_tf_disagreement')
 def test_new_invalid_odom_stops_even_if_previous_pair_valid(self):
  self.feed(99.96);o=self.feed(99.98,False);o.pose.pose.position.x=math.nan
  self.assertEqual(self.n.reason(),'nonfinite_odom')
 def test_time_reversal_discards_prior_pairs(self):
  self.feed(99.98);self.feed(99.95,False)
  self.assertEqual(len(self.n.odom_history),1);self.assertEqual(self.n.reason(),'waiting_for_tf')
 def test_other_stop_gates_remain_effective(self):
  self.feed(99.98)
  self.n.action_state=5;self.assertEqual(self.n.reason(),'hardware_inhibited')
  self.n.action_state=1;self.n.cmd_time=time.monotonic()-1;self.assertEqual(self.n.reason(),'stale_nav_command')
 def test_failed_hardware_stops_despite_fresh_ros_message(self):
  self.feed(99.98)
  self.n.hardware_feedback.interface_values[0].values=[math.inf]
  self.assertEqual(self.n.reason(),'stale_hardware_feedback')
 def test_learning_uses_motor_command_before_lidar_stamp_and_response_delay(self):
  self.n.response_delay=[.15,0.]
  self.n.applied_history=deque([(99.7,.1,.2),(99.8,.3,.4),(99.9,.5,.6),(100.1,.9,1.)])
  self.assertEqual(self.n.learning_input(99.98),[.3,.6])
  self.assertTrue(all(math.isnan(x) for x in self.n.learning_input(101.)))
 def test_reverse_requires_backup_action_clear_rear_and_fresh_scan(self):
  self.feed(99.98);self.n.cmd.linear.x=-.12;self.n.backup_active=False;self.n.reverse_max=.12
  self.n.applied_time=time.monotonic();self.n.applied_v=0.
  self.assertEqual(self.n.reason(),'reverse_without_recovery')
  self.n.backup_active=True;self.n.scan.angle_min=-math.pi;self.n.scan.angle_increment=math.pi/360;self.n.scan.ranges=[3.]*720
  self.assertEqual(self.n.reason(),'driving')
  self.n.applied_v=.2;self.assertEqual(self.n.reason(),'waiting_for_reverse_stop');self.n.applied_v=0.
  self.n.scan.ranges[0]=.4;self.assertEqual(self.n.reason(),'rear_obstacle')
  self.stamp(self.n.scan,99.);self.assertEqual(self.n.reason(),'stale_scan')
if __name__=='__main__':unittest.main()

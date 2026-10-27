#!/usr/bin/env python3
"""Nav2 SI Twist -> normalized hardware input, with freshness and mode gates."""
import json
import math
import time
from collections import deque

import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from control_msgs.msg import DynamicJointState
from std_msgs.msg import Bool, Int32, String
from action_msgs.msg import GoalStatusArray, GoalStatus
from tf2_ros import Buffer, TransformListener, TransformException
from rcl_interfaces.srv import GetParameters
from navigation_contract import normalized_twist
from motion_interpreter import MotionInterpreter, AxisConfig, rolling_arc
from reverse_clearance import rear_clearance


class NavDriveBridge(Node):
    def __init__(self):
        super().__init__('nav_drive_bridge')
        self.scale_v = self.declare_parameter('max_linear_velocity', 1.72).value
        self.scale_w = self.declare_parameter('max_angular_velocity', 7.0).value
        self.wheel_radius = self.declare_parameter('wheel_radius', .234).value
        self.wheel_separation = self.declare_parameter('wheel_separation', .184).value
        self.max_v = self.declare_parameter('nav_max_linear', 0.3).value
        self.max_w = self.declare_parameter('nav_max_angular', 1.2).value
        self.reverse_max = self.declare_parameter('recovery_max_reverse_speed', .12).value
        self.backup_active = False
        self.interpreter_enabled = self.declare_parameter('motion_interpreter_enabled', True).value
        self.arc_only = self.declare_parameter('motion.arc_only', True).value
        def axis_config(name, gain, start, maximum, kp, ki, threshold, stop):
            gain = self.declare_parameter('motion.'+name+'.response_gain', gain).value
            values = [self.declare_parameter('motion.'+name+'.'+key, value).value
                      for key, value in [('start_input', start), ('max_input', maximum), ('kp', kp), ('ki', ki)]]
            startup = self.declare_parameter('motion.'+name+'.startup_rate', .12).value
            adapt = self.declare_parameter('motion.'+name+'.adapt_start', True).value
            return AxisConfig(gain, *values, threshold, stop, startup, adapt)
        self.interpreter = MotionInterpreter(self.scale_v, self.scale_w,
            axis_config('linear', self.scale_v, .18, .50, .5, .7, .025, .004),
            axis_config('angular', self.scale_w, .25, .65, .10, .15, .08, .015),
            arc_only=self.arc_only, wheel_separation=self.wheel_separation)
        self.response_delay = [self.declare_parameter('motion.'+axis+'.response_delay', 0.).value
                               for axis in ('linear','angular')]
        if not all(math.isfinite(x) and 0 <= x <= 1 for x in self.response_delay):
            raise ValueError('Response delay must be within 0..1 seconds')
        self.last_tick = time.monotonic()
        self.wheel_motion = deque(maxlen=80)
        self.encoder_v = self.encoder_w = 0.
        self.applied_v = self.applied_w = 0.
        self.applied_time = 0.
        self.applied_history = deque(maxlen=80)
        self.interpreter_status_time = 0.
        normalized_twist(0, 0, self.scale_v, self.scale_w, self.max_v, self.max_w)
        self.cmd_timeout = self.declare_parameter('cmd_timeout', 0.4).value
        self.odom_timeout = self.declare_parameter('odom_timeout', 0.5).value
        self.scan_timeout = self.declare_parameter('scan_timeout', 0.8).value
        for v in [self.cmd_timeout, self.odom_timeout, self.scan_timeout]:
            if not math.isfinite(v) or v <= 0: raise ValueError('Timeout must be positive')
        latch = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.out = self.create_publisher(Twist, '/auto/cmd_vel', 10)
        self.halt = self.create_publisher(Bool, '/navigation/halt', latch)
        self.status = self.create_publisher(String, '/navigation/drive_status', latch)
        self.motion_status = self.create_publisher(String, '/navigation/motion_interpreter', 5)
        self.mode_cmd = self.create_publisher(Int32, '/control_mode_cmd', 10)
        self.nav_mode = self.create_publisher(Int32, '/NAVIGATION_MODE', 10)
        self.authority_time = 0.
        self.create_subscription(Bool, "/navigation/authority_heartbeat", self.on_authority, 10)
        self.enabled = False; self.control_mode = None; self.action_state = None
        self.goal_active = False; self.cmd = None; self.cmd_time = 0
        self.odom = None; self.scan = None; self.last_reason = None; self.last_halt = None
        self.odom_history = deque(maxlen=20)
        self.hardware_feedback = None
        self.scale_verified = False; self.params_time = 0; self.params_pending = False
        self.params_future = None; self.params_requested = 0
        self.parameter_client = self.create_client(GetParameters, '/drive_controller_node/get_parameters')
        self.create_timer(1.0, self.check_scales)
        self.buffer = Buffer(); self.listener = TransformListener(self.buffer, self)
        self.create_subscription(Twist, '/nav/cmd_vel', self.on_cmd, 10)
        self.create_subscription(Int32, '/NAVIGATION_MODE', self.on_mode, 10)
        self.create_subscription(Int32, '/system/control_mode', self.on_control, latch)
        self.create_subscription(Int32, '/system/action_state', self.on_action, latch)
        self.create_subscription(Bool, '/navigation/goal_active', self.on_goal, latch)
        self.create_subscription(GoalStatusArray, '/backup/_action/status', self.on_backup, latch)
        self.create_subscription(Odometry, '/odom', self.on_odom, qos_profile_sensor_data)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(DynamicJointState, '/dynamic_joint_states', self.on_feedback, qos_profile_sensor_data)
        self.create_subscription(DynamicJointState, '/drive/wheel_control', self.on_applied, qos_profile_sensor_data)
        self.create_subscription(Bool, '/emergency_stop', self.on_estop, 10)
        self.create_timer(0.05, self.tick)

    def on_authority(self, msg):
        self.authority_time = time.monotonic() if msg.data else 0.

    def on_cmd(self, msg):
        values = [msg.linear.x, msg.linear.y, msg.linear.z, msg.angular.x, msg.angular.y, msg.angular.z]
        if not all(math.isfinite(v) for v in values) or any(abs(v)>1e-9 for v in values[1:5]):
            self.cmd = None
            return
        if self.enabled and self.control_mode == 1 and self.goal_active:
            self.cmd = msg; self.cmd_time = time.monotonic()

    def on_mode(self, msg):
        if msg.data not in (0, 1): return
        was_enabled = self.enabled
        self.enabled = msg.data == 1
        if not self.enabled or not was_enabled: self.cmd = None
        if self.enabled and not was_enabled:
            self.mode_cmd.publish(Int32(data=1))
        self.tick()

    def on_control(self, msg):
        previous = self.control_mode
        self.control_mode = msg.data
        if msg.data != 1:
            self.cmd = None
            if previous == 1 and self.enabled:
                self.enabled = False
                self.nav_mode.publish(Int32(data=0))

    def on_action(self, msg):
        self.action_state = msg.data
        if msg.data >= 2: self.cmd = None

    def on_goal(self, msg):
        self.goal_active = msg.data
        if not msg.data: self.cmd = None

    def on_backup(self, msg):
        self.backup_active = any(s.status == GoalStatus.STATUS_EXECUTING for s in msg.status_list)

    def on_estop(self, msg):
        if msg.data:
            self.enabled = False; self.cmd = None
            self.nav_mode.publish(Int32(data=0))
            self.tick()

    def on_odom(self, msg):
        if self.odom is not None and Time.from_msg(msg.header.stamp) < Time.from_msg(self.odom.header.stamp):
            self.odom_history.clear()
        self.odom = msg
        self.odom_history.append(msg)
    def on_scan(self, msg): self.scan = msg
    def on_feedback(self, msg):
        self.hardware_feedback = msg
        try:
            positions = []
            for name in ('left_wheel_joint', 'right_wheel_joint'):
                values = msg.interface_values[msg.joint_names.index(name)]
                positions.append(values.values[values.interface_names.index('position')])
            stamp = Time.from_msg(msg.header.stamp).nanoseconds/1e9
            if not all(math.isfinite(x) for x in positions): return
            if self.wheel_motion and stamp <= self.wheel_motion[-1][0]: self.wheel_motion.clear()
            self.wheel_motion.append((stamp, *positions))
            while len(self.wheel_motion)>1 and stamp-self.wheel_motion[1][0] >= .3: self.wheel_motion.popleft()
            old = self.wheel_motion[0]; interval = stamp-old[0]
            if interval >= .15:
                left = math.remainder(positions[0]-old[1], 8*math.pi)/interval
                right = math.remainder(positions[1]-old[2], 8*math.pi)/interval
                self.encoder_v = self.wheel_radius*(left+right)/2
                self.encoder_w = self.wheel_radius*(right-left)/self.wheel_separation
        except (ValueError, IndexError):
            self.encoder_v = self.encoder_w = 0.


    def on_applied(self, msg):
        try:
            targets=[]
            for name in ('left_wheel_joint','right_wheel_joint'):
                values=msg.interface_values[msg.joint_names.index(name)]
                targets.append(values.values[values.interface_names.index('target_velocity')])
            if not all(math.isfinite(x) for x in targets): return
            left,right=targets
            self.applied_v=self.wheel_radius*(left+right)/2/self.scale_v
            self.applied_w=self.wheel_radius*(right-left)/self.wheel_separation/self.scale_w
            self.applied_time=time.monotonic()
            stamp=Time.from_msg(msg.header.stamp).nanoseconds/1e9
            if self.applied_history and stamp<=self.applied_history[-1][0]:self.applied_history.clear()
            self.applied_history.append((stamp,self.applied_v,self.applied_w))
        except (ValueError,IndexError):
            pass

    def learning_input(self, stamp):
        result=[]
        for axis,delay in enumerate(self.response_delay):
            target=stamp-delay
            item=next((x for x in reversed(self.applied_history) if x[0]<=target),None)
            result.append(item[axis+1] if item and target-item[0]<.3 else math.nan)
        return result

    def feedback_valid(self):
        msg = self.hardware_feedback
        if not self.fresh(msg, .25): return False
        for name in ('left_wheel_joint', 'right_wheel_joint'):
            try:
                values = msg.interface_values[msg.joint_names.index(name)]
                age = values.values[values.interface_names.index('feedback_age')]
                if not math.isfinite(age) or not 0 <= age <= .2: return False
            except (ValueError, IndexError):
                return False
        return True

    def check_scales(self):
        if self.params_pending:
            if time.monotonic()-self.params_requested < 2: return
            self.parameter_client.remove_pending_request(self.params_future)
            self.params_future.cancel()
            self.params_pending = False
        if not self.parameter_client.service_is_ready(): return
        request = GetParameters.Request(); request.names = ['max_linear_velocity', 'max_angular_velocity']
        self.params_pending = True
        future = self.parameter_client.call_async(request)
        self.params_future = future; self.params_requested = time.monotonic()
        def complete(result):
            if result is not self.params_future: return
            self.params_pending = False
            try:
                values = result.result().values
                self.scale_verified = len(values) == 2 and all(
                    v.type == 3 and math.isclose(v.double_value, expected, rel_tol=1e-8)
                    for v, expected in zip(values, [self.scale_v, self.scale_w]))
                self.params_time = time.monotonic()
            except Exception:
                self.scale_verified = False
        future.add_done_callback(complete)

    def fresh(self, msg, timeout, future_tolerance=0.05):
        if msg is None: return False
        age = (self.get_clock().now() - Time.from_msg(msg.header.stamp)).nanoseconds / 1e9
        return -future_tolerance <= age <= timeout

    def paired_odom(self):
        # /odom and /tf are separate DDS streams. The newest odometry message can
        # arrive one callback before its TF. Keep using the newest complete pair
        # within the SAME freshness bound; never extrapolate or restamp a pose.
        for odom in reversed(self.odom_history):
            if not self.fresh(odom, self.odom_timeout): continue
            if odom.header.frame_id != 'odom' or odom.child_frame_id != 'base_link': continue
            try:
                tf = self.buffer.lookup_transform('odom', 'base_link', Time.from_msg(odom.header.stamp))
            except TransformException:
                continue
            return odom, tf
        return None

    def reason(self):
        if not self.enabled: return 'disabled'
        if time.monotonic()-self.authority_time > .5: return 'authority_stale'
        if self.control_mode != 1: return 'waiting_for_hardware_auto_mode'
        if not self.scale_verified or time.monotonic()-self.params_time > 3: return 'hardware_scale_unverified'
        if self.action_state not in (0, 1): return 'hardware_inhibited'
        if not self.goal_active: return 'no_active_goal'
        if not self.feedback_valid(): return 'stale_hardware_feedback'
        if not self.fresh(self.odom, self.odom_timeout): return 'stale_odom'
        if self.odom.header.frame_id != 'odom' or self.odom.child_frame_id != 'base_link': return 'invalid_odom_frames'
        p, q = self.odom.pose.pose.position, self.odom.pose.pose.orientation
        if not all(math.isfinite(v) for v in [p.x,p.y,p.z,q.x,q.y,q.z,q.w]): return 'nonfinite_odom'
        if not self.fresh(self.scan, self.scan_timeout): return 'stale_scan'
        if self.scan.header.frame_id != 'laser': return 'invalid_scan_frame'
        if not any(math.isfinite(x) and self.scan.range_min <= x <= self.scan.range_max for x in self.scan.ranges): return 'empty_scan'
        try:
            pair = self.paired_odom()
            if pair is None: return 'waiting_for_tf'
            odom, tf = pair
            p, q = odom.pose.pose.position, odom.pose.pose.orientation
            t, r = tf.transform.translation, tf.transform.rotation
            if not all(math.isfinite(v) for v in [p.x,p.y,p.z,q.x,q.y,q.z,q.w,t.x,t.y,t.z,r.x,r.y,r.z,r.w]): return 'nonfinite_odom'
            if math.hypot(p.x-t.x, p.y-t.y) > 0.01 or abs(abs(q.x*r.x+q.y*r.y+q.z*r.z+q.w*r.w)-1)>1e-4:
                return 'odom_tf_disagreement'
            localization = self.buffer.lookup_transform('map', 'odom', Time())
            # AMCL intentionally stamps this TF ahead by transform_tolerance (1s).
            if not self.fresh(localization, 1.5, future_tolerance=1.1): return 'stale_localization'
            self.buffer.lookup_transform('base_link', 'laser', Time())
        except TransformException:
            return 'waiting_for_tf'
        if self.cmd is None or time.monotonic()-self.cmd_time > self.cmd_timeout: return 'stale_nav_command'
        if self.cmd.linear.x < -1e-6:
            if not self.backup_active: return 'reverse_without_recovery'
            if (self.odom.twist.twist.linear.x > .03 or
                    (time.monotonic()-self.applied_time < .3 and self.applied_v > .03)):
                return 'waiting_for_reverse_stop'
            if abs(self.cmd.angular.z) > .02: return 'waiting_for_straight_reverse'
            try:
                tf = self.buffer.lookup_transform('base_link', 'laser', Time())
                p, q = tf.transform.translation, tf.transform.rotation
                a = math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
                speed=max(self.reverse_max,abs(self.odom.twist.twist.linear.x))
                return rear_clearance(self.scan,(p.x,p.y,a),speed)
            except TransformException:
                return 'waiting_for_tf'
        return 'driving'

    def tick(self):
        reason = self.reason()
        command = Twist()
        now = time.monotonic(); dt = now-self.last_tick; self.last_tick = now
        desired_v = desired_w = 0.
        if reason == 'driving':
            normalized_v, normalized_w = normalized_twist(
                self.cmd.linear.x, self.cmd.angular.z, self.scale_v, self.scale_w, self.max_v, self.max_w)
            desired_v, desired_w = normalized_v*self.scale_v, normalized_w*self.scale_w
            if desired_v < 0:
                desired_v=max(desired_v,-self.reverse_max); desired_w=0.
                normalized_v=desired_v/self.scale_v; normalized_w=0.
            if self.interpreter_enabled:
                velocity = self.odom.twist.twist
                command.linear.x, command.angular.z = self.interpreter.update(
                    desired_v, desired_w, velocity.linear.x, velocity.angular.z,
                    self.encoder_v, self.encoder_w, dt,
                    Time.from_msg(self.odom.header.stamp).nanoseconds/1e9,
                    self.applied_v if now-self.applied_time < .3 else 0.,
                    self.applied_w if now-self.applied_time < .3 else 0.,
                    learning_input=self.learning_input(Time.from_msg(self.odom.header.stamp).nanoseconds/1e9))
            else:
                command.linear.x, command.angular.z = normalized_v, normalized_w
            if self.arc_only and not self.interpreter_enabled:
                command.linear.x, command.angular.z = rolling_arc(
                    command.linear.x, command.angular.z, self.scale_v, self.scale_w, self.wheel_separation)
        else:
            self.interpreter.reset()
        halted = reason != 'driving' or (abs(command.linear.x)<1e-6 and abs(command.angular.z)<1e-6)
        if now-self.interpreter_status_time > .2:
            self.interpreter_status_time = now
            data = self.interpreter.status()
            data.update(enabled=self.interpreter_enabled, desired=[desired_v,desired_w], encoder=[self.encoder_v,self.encoder_w],
                        applied=[self.applied_v,self.applied_w], recovering=self.backup_active)
            self.motion_status.publish(String(data=json.dumps(data, allow_nan=False)))
        if halted != self.last_halt:
            self.halt.publish(Bool(data=halted))
            self.last_halt = halted
        if self.control_mode == 1:
            self.out.publish(command)
        if reason != self.last_reason:
            self.get_logger().info('Drive gate: '+reason)
            self.status.publish(String(data=reason)); self.last_reason = reason


def main():
    rclpy.init(); node = NavDriveBridge()
    try: rclpy.spin(node)
    except KeyboardInterrupt: pass
    finally:
        if rclpy.ok():
            node.enabled=False; node.tick()
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()


if __name__ == '__main__': main()

#!/usr/bin/env python3
"""Nav2 SI Twist -> normalized hardware input, with freshness and mode gates."""
import math
import time

import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, Int32, String
from tf2_ros import Buffer, TransformListener, TransformException
from rcl_interfaces.srv import GetParameters
from navigation_contract import normalized_twist


class NavDriveBridge(Node):
    def __init__(self):
        super().__init__('nav_drive_bridge')
        self.scale_v = self.declare_parameter('max_linear_velocity', 1.72).value
        self.scale_w = self.declare_parameter('max_angular_velocity', 7.0).value
        self.max_v = self.declare_parameter('nav_max_linear', 0.3).value
        self.max_w = self.declare_parameter('nav_max_angular', 0.8).value
        normalized_twist(0, 0, self.scale_v, self.scale_w, self.max_v, self.max_w)
        self.cmd_timeout = self.declare_parameter('cmd_timeout', 0.25).value
        self.odom_timeout = self.declare_parameter('odom_timeout', 0.25).value
        self.scan_timeout = self.declare_parameter('scan_timeout', 0.5).value
        for v in [self.cmd_timeout, self.odom_timeout, self.scan_timeout]:
            if not math.isfinite(v) or v <= 0: raise ValueError('Timeout must be positive')
        latch = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.out = self.create_publisher(Twist, '/auto/cmd_vel', 10)
        self.halt = self.create_publisher(Bool, '/navigation/halt', latch)
        self.status = self.create_publisher(String, '/navigation/drive_status', latch)
        self.mode_cmd = self.create_publisher(Int32, '/control_mode_cmd', 10)
        self.nav_mode = self.create_publisher(Int32, '/NAVIGATION_MODE', 10)
        self.enabled = False; self.control_mode = None; self.action_state = None
        self.goal_active = False; self.cmd = None; self.cmd_time = 0
        self.odom = None; self.scan = None; self.last_reason = None
        self.scale_verified = False; self.params_time = 0; self.params_pending = False
        self.parameter_client = self.create_client(GetParameters, '/drive_controller_node/get_parameters')
        self.create_timer(1.0, self.check_scales)
        self.buffer = Buffer(); self.listener = TransformListener(self.buffer, self)
        self.create_subscription(Twist, '/nav/cmd_vel', self.on_cmd, 10)
        self.create_subscription(Int32, '/NAVIGATION_MODE', self.on_mode, 10)
        self.create_subscription(Int32, '/system/control_mode', self.on_control, latch)
        self.create_subscription(Int32, '/system/action_state', self.on_action, latch)
        self.create_subscription(Bool, '/navigation/goal_active', self.on_goal, latch)
        self.create_subscription(Odometry, '/odom', self.on_odom, qos_profile_sensor_data)
        self.create_subscription(LaserScan, '/scan', self.on_scan, qos_profile_sensor_data)
        self.create_subscription(Bool, '/emergency_stop', self.on_estop, 10)
        self.create_timer(0.02, self.tick)

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

    def on_estop(self, msg):
        if msg.data:
            self.enabled = False; self.cmd = None
            self.nav_mode.publish(Int32(data=0))
            self.tick()

    def on_odom(self, msg): self.odom = msg
    def on_scan(self, msg): self.scan = msg

    def check_scales(self):
        if self.params_pending or not self.parameter_client.service_is_ready(): return
        request = GetParameters.Request(); request.names = ['max_linear_velocity', 'max_angular_velocity']
        self.params_pending = True
        future = self.parameter_client.call_async(request)
        def complete(result):
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

    def reason(self):
        if not self.enabled: return 'disabled'
        if self.control_mode != 1: return 'waiting_for_hardware_auto_mode'
        if not self.scale_verified or time.monotonic()-self.params_time > 3: return 'hardware_scale_unverified'
        if self.action_state not in (0, 1): return 'hardware_inhibited'
        if not self.goal_active: return 'no_active_goal'
        if not self.fresh(self.odom, self.odom_timeout): return 'stale_odom'
        if self.odom.header.frame_id != 'odom' or self.odom.child_frame_id != 'base_link': return 'invalid_odom_frames'
        if not self.fresh(self.scan, self.scan_timeout): return 'stale_scan'
        if self.scan.header.frame_id != 'laser': return 'invalid_scan_frame'
        if not any(math.isfinite(x) and self.scan.range_min <= x <= self.scan.range_max for x in self.scan.ranges): return 'empty_scan'
        try:
            tf = self.buffer.lookup_transform('odom', 'base_link', Time.from_msg(self.odom.header.stamp))
            p, q = self.odom.pose.pose.position, self.odom.pose.pose.orientation
            t, r = tf.transform.translation, tf.transform.rotation
            if not all(math.isfinite(v) for v in [p.x,p.y,q.x,q.y,q.z,q.w]): return 'nonfinite_odom'
            if math.hypot(p.x-t.x, p.y-t.y) > 0.01 or abs(abs(q.x*r.x+q.y*r.y+q.z*r.z+q.w*r.w)-1)>1e-4:
                return 'odom_tf_disagreement'
            localization = self.buffer.lookup_transform('map', 'odom', Time())
            # AMCL intentionally stamps this TF ahead by transform_tolerance (1s).
            if not self.fresh(localization, 1.5, future_tolerance=1.1): return 'stale_localization'
            self.buffer.lookup_transform('base_link', 'laser', Time())
        except TransformException:
            return 'waiting_for_tf'
        if self.cmd is None or time.monotonic()-self.cmd_time > self.cmd_timeout: return 'stale_nav_command'
        return 'driving'

    def tick(self):
        reason = self.reason()
        command = Twist()
        if reason == 'driving':
            command.linear.x, command.angular.z = normalized_twist(
                self.cmd.linear.x, self.cmd.angular.z, self.scale_v, self.scale_w, self.max_v, self.max_w)
        self.halt.publish(Bool(data=reason != 'driving'))
        if self.control_mode == 1:
            self.out.publish(command)
        if reason != self.last_reason:
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

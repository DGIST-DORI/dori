#!/usr/bin/env python3
"""Serialize named goals, cancellation and mode changes into Nav2 actions."""
import math
import time
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.qos import QoSProfile, DurabilityPolicy
from nav2_msgs.action import NavigateToPose
from std_msgs.msg import String, Bool, Int32
from visualization_msgs.msg import Marker, MarkerArray
from navigation_contract import load_points_csv


class NamedGoalBridge(Node):
    def __init__(self):
        super().__init__('named_goal_bridge')
        self.points_file = self.declare_parameter('points_file', '').value
        self.points = load_points_csv(self.points_file)
        self.goal_topic = self.declare_parameter('goal_topic', '/named_goal').value
        status_topic = self.declare_parameter('status_topic', '/named_goal_status').value
        action_name = self.declare_parameter('action_name', '/navigate_to_pose').value
        latch = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.status = self.create_publisher(String, status_topic, latch)
        self.active_pub = self.create_publisher(Bool, '/navigation/goal_active', latch)
        self.markers = self.create_publisher(MarkerArray, '/named_goal_marker', latch)
        self.client = ActionClient(self, NavigateToPose, action_name)
        self.enabled = False; self.sequence = 0; self.pending = None
        self.goal_handle = None; self.sending = False; self.cancelling = False
        self.pending_since = 0
        self.create_subscription(String, self.goal_topic, self.on_goal, 10)
        self.create_subscription(Int32, '/NAVIGATION_MODE', self.on_mode, 10)
        self.create_subscription(Bool, '/emergency_stop', self.on_estop, 10)
        self.create_subscription(Int32, '/system/action_state', self.on_action, latch)
        self.create_timer(0.05, self.tick)
        self.active_pub.publish(Bool(data=False))
        self.publish_status('ready:mode=0')

    def publish_status(self, text):
        self.status.publish(String(data=text)); self.get_logger().info(text)

    def stop(self):
        self.sequence += 1; self.pending = None
        self.active_pub.publish(Bool(data=False))
        self.cancel_current()

    def on_mode(self, msg):
        if msg.data not in (0, 1): return
        self.enabled = msg.data == 1
        if not self.enabled:
            self.stop(); self.publish_status('cancel_requested:mode_off')

    def on_estop(self, msg):
        if msg.data:
            self.enabled = False; self.stop()

    def on_action(self, msg):
        if msg.data >= 2:
            self.stop(); self.publish_status('cancel_requested:hardware_inhibited')

    def on_goal(self, msg):
        key = msg.data.strip()
        if key == 'cancel': self.stop(); return
        if key == 'list': self.publish_status('list:'+','.join(self.points)); return
        if key == 'reload':
            try: self.points = load_points_csv(self.points_file)
            except (OSError, ValueError) as exc:
                self.publish_status('reload_error:'+str(exc)); return
            self.stop(); self.publish_status('reloaded'); return
        if not self.enabled:
            self.publish_status('rejected:mode_off'); return
        if key not in self.points:
            self.publish_status('unknown:'+key); return
        self.sequence += 1
        self.pending = (self.sequence, key)
        self.pending_since = time.monotonic()
        self.active_pub.publish(Bool(data=False))
        self.cancel_current()

    def cancel_current(self):
        if self.goal_handle is None or self.cancelling: return
        self.cancelling = True
        future = self.goal_handle.cancel_goal_async()
        future.add_done_callback(self.on_cancel_response)

    def on_cancel_response(self, future):
        try:
            response = future.result()
            if not response.goals_canceling:
                self.publish_status('cancel_not_acknowledged:waiting_for_terminal_result')
        except Exception as exc:
            self.publish_status('cancel_error:'+str(exc))
        # Never start the next goal until the previous goal has a terminal result.

    def tick(self):
        if not self.enabled or self.pending is None or self.goal_handle is not None or self.sending: return
        if not self.client.server_is_ready():
            if time.monotonic()-self.pending_since > 5:
                self.publish_status('server_unavailable:'+self.pending[1]); self.pending = None
            return
        sequence, key = self.pending; self.pending = None
        p = self.points[key]
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = p['x']; goal.pose.pose.position.y = p['y']
        yaw = math.radians(p['yaw_deg'])
        goal.pose.pose.orientation.z = math.sin(yaw/2)
        goal.pose.pose.orientation.w = math.cos(yaw/2)
        self.sending = True
        future = self.client.send_goal_async(goal)
        future.add_done_callback(lambda f: self.on_response(sequence, key, goal, f))
        self.publish_status('sent:'+key)

    def on_response(self, sequence, key, goal, future):
        self.sending = False
        try: handle = future.result()
        except Exception as exc:
            self.publish_status('send_error:'+str(exc)); return
        if handle is None or not handle.accepted:
            self.publish_status('rejected:'+key); return
        self.goal_handle = handle; self.cancelling = False
        result = handle.get_result_async()
        result.add_done_callback(lambda f: self.on_result(handle, key, f))
        if not self.enabled or sequence != self.sequence:
            self.cancel_current(); return
        self.active_pub.publish(Bool(data=True))
        self.publish_status('accepted:'+key)
        marker = Marker()
        marker.header = goal.pose.header; marker.ns = 'named_goal'; marker.id = 0
        marker.type = Marker.ARROW; marker.action = Marker.ADD; marker.pose = goal.pose.pose
        marker.scale.x=0.5; marker.scale.y=0.1; marker.scale.z=0.1
        marker.color.g=1.0; marker.color.a=1.0
        self.markers.publish(MarkerArray(markers=[marker]))

    def on_result(self, handle, key, future):
        if self.goal_handle is not handle: return
        self.goal_handle = None; self.cancelling = False
        self.active_pub.publish(Bool(data=False))
        try: self.publish_status(f'finished:{key}:status={future.result().status}')
        except Exception as exc: self.publish_status('result_error:'+str(exc))


def main():
    rclpy.init(); node = NamedGoalBridge()
    try: rclpy.spin(node)
    except KeyboardInterrupt: pass
    finally:
        if rclpy.ok(): node.stop()
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()


if __name__ == '__main__': main()

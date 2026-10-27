#!/usr/bin/env python3
"""Serialize named goals, cancellation and mode changes into Nav2 actions."""
import math
import json
import time
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.qos import QoSProfile, DurabilityPolicy
from dori_msgs.action import Navigate
from std_msgs.msg import String, Bool, Int32
from visualization_msgs.msg import Marker, MarkerArray
from navigation_contract import load_points_csv, rviz_goal_point
from geometry_msgs.msg import PoseStamped
from rclpy.time import Time


class NamedGoalBridge(Node):
    def __init__(self):
        super().__init__('named_goal_bridge')
        self.points_file = self.declare_parameter('points_file', '').value
        self.goal_source = self.declare_parameter('goal_source', 'web').value
        self.arrival_xy = self.declare_parameter('arrival_xy_tolerance', .35).value
        self.arrival_yaw = self.declare_parameter('arrival_yaw_tolerance', math.pi).value
        self.relative_arrival_xy = self.declare_parameter('relative_arrival_xy_tolerance', .15).value
        self.relative_behavior_tree = self.declare_parameter('relative_behavior_tree', str(Path(__file__).resolve().parents[1]/'config/navigate_relative.xml')).value
        self.active_arrival_xy = self.arrival_xy
        self.retry_delay = self.declare_parameter('retry_delay', 5.0).value
        self.max_retries = self.declare_parameter('max_retries', 3).value
        if not math.isfinite(self.retry_delay) or self.retry_delay < 1. or not 0 <= self.max_retries <= 10:
            raise ValueError('retry_delay must be >= 1 second; max_retries must be in 0..10')
        if self.goal_source not in ('named','rviz','web'):raise ValueError('Invalid goal_source')
        self.points = load_points_csv(self.points_file) if self.goal_source=='named' else {}
        self.goal_topic = self.declare_parameter('goal_topic', '/named_goal').value
        status_topic = self.declare_parameter('status_topic', '/named_goal_status').value
        action_name = self.declare_parameter('action_name', '/dori/nav/navigate_to').value
        latch = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.status = self.create_publisher(String, status_topic, latch)
        self.feedback_pub = self.create_publisher(String, '/navigation/feedback', 10)
        self.retry_pub = self.create_publisher(String, '/navigation/retry_status', latch)
        self.markers = self.create_publisher(MarkerArray, '/named_goal_marker', latch)
        self.client = ActionClient(self, Navigate, action_name)
        self.enabled = False; self.sequence = 0; self.pending = None
        self.goal_handle = None; self.sending = False; self.cancelling = False
        self.pending_since = 0
        self.goal_feedback = None
        self.active_target = None
        self.retry_at = 0.; self.retry_count = 0; self.retry_reported = 0.
        self.hardware_inhibited = False
        if self.goal_source in ('rviz','web'):
            self.create_subscription(PoseStamped, '/goal_pose', self.on_rviz_goal, 10)
            self.create_subscription(PoseStamped, '/relative_goal_pose', self.on_relative_goal, 10)
        else:
            self.create_subscription(String, self.goal_topic, self.on_goal, 10)
        self.create_subscription(Int32, '/NAVIGATION_MODE', self.on_mode, 10)
        self.create_subscription(Bool, '/emergency_stop', self.on_estop, 10)
        self.create_subscription(Int32, '/system/action_state', self.on_action, latch)
        self.create_timer(0.05, self.tick)
        self.publish_status('ready:mode=0')
        self.publish_retry('idle')

    def publish_status(self, text):
        self.status.publish(String(data=text)); self.get_logger().info(text)

    def publish_retry(self, state):
        self.retry_pub.publish(String(data=json.dumps({
            'state': state, 'attempt': self.retry_count, 'max_attempts': self.max_retries,
            'remaining_seconds': max(0., self.retry_at-time.monotonic()) if state=='waiting' else 0.,
        })))
        self.retry_reported = time.monotonic()

    def stop(self):
        self.sequence += 1; self.pending = None
        self.retry_at = 0.; self.retry_count = 0
        self.publish_retry('idle')
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
        self.hardware_inhibited = msg.data >= 2
        if msg.data >= 2:
            self.stop(); self.publish_status('cancel_requested:hardware_inhibited')

    def on_rviz_goal(self, msg):
        self.on_pose_goal(msg,'rviz_goal')

    def on_relative_goal(self, msg):
        self.on_pose_goal(msg,'relative_goal')

    def on_pose_goal(self, msg, key):
        if not self.enabled:
            self.publish_status('rejected:mode_off');return
        try: point=rviz_goal_point(msg)
        except ValueError as exc:
            self.publish_status('rejected:'+str(exc));return
        self.points[key]=point
        self.on_goal(String(data=key))

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
        if self.hardware_inhibited:
            self.publish_status('rejected:hardware_inhibited'); return
        if key not in self.points:
            self.publish_status('unknown:'+key); return
        self.sequence += 1
        self.retry_at = 0.; self.retry_count = 0
        self.publish_retry('idle')
        self.pending = (self.sequence, key)
        self.pending_since = time.monotonic()
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
        if self.retry_at:
            if time.monotonic() < self.retry_at:
                if time.monotonic()-self.retry_reported >= .5:self.publish_retry('waiting')
                return
            self.retry_at = 0.
            self.publish_retry('running')
            self.publish_status(f'retrying:{self.pending[1]}:attempt={self.retry_count}/{self.max_retries}')
        if not self.client.server_is_ready():
            if time.monotonic()-self.pending_since > 5:
                key=self.pending[1];self.pending = None
                self.publish_retry('exhausted')
                self.publish_status('server_unavailable:'+key)
                self.publish_status(f'finished:{key}:status=6')
            return
        sequence, key = self.pending; self.pending = None
        p = self.points[key]
        goal = Navigate.Goal()
        if key=='relative_goal' and self.goal_source in ('rviz','web'):
            goal.precise=True
        goal.destination.header.frame_id = 'map'
        goal.destination.header.stamp = self.get_clock().now().to_msg()
        goal.destination.pose.position.x = p['x']; goal.destination.pose.position.y = p['y']
        yaw = math.radians(p['yaw_deg'])
        goal.destination.pose.orientation.z = math.sin(yaw/2)
        goal.destination.pose.orientation.w = math.cos(yaw/2)
        self.sending = True
        self.goal_feedback = None
        future = self.client.send_goal_async(goal, feedback_callback=lambda msg: self.on_feedback(sequence,msg))
        future.add_done_callback(lambda f: self.on_response(sequence, key, goal, f))
        self.publish_status('sent:'+key)

    def on_feedback(self, sequence, message):
        if sequence != self.sequence:return
        feedback = message.feedback
        self.goal_feedback = feedback.current_pose
        self.feedback_pub.publish(String(data=json.dumps({
            'distance_remaining': feedback.distance_remaining,
            'recoveries': 0,
            'navigation_time': 0,
        })))

    def on_response(self, sequence, key, goal, future):
        self.sending = False
        try: handle = future.result()
        except Exception as exc:
            if sequence == self.sequence:
                self.publish_retry('exhausted');self.publish_status('send_error:'+str(exc))
                self.publish_status(f'finished:{key}:status=6')
            return
        if handle is None or not handle.accepted:
            if sequence == self.sequence:
                self.publish_retry('exhausted');self.publish_status('rejected:'+key)
                self.publish_status(f'finished:{key}:status=6')
            return
        self.goal_handle = handle; self.cancelling = False
        self.active_target = goal.destination
        self.active_arrival_xy = self.relative_arrival_xy if goal.precise else self.arrival_xy
        result = handle.get_result_async()
        result.add_done_callback(lambda f: self.on_result(handle, key, sequence, f))
        if not self.enabled or sequence != self.sequence:
            self.cancel_current(); return
        self.publish_status('accepted:'+key)
        marker = Marker()
        marker.header = goal.destination.header; marker.ns = 'named_goal'; marker.id = 0
        marker.type = Marker.ARROW; marker.action = Marker.ADD; marker.pose = goal.destination.pose
        marker.scale.x=0.5; marker.scale.y=0.1; marker.scale.z=0.1
        marker.color.g=1.0; marker.color.a=1.0
        self.markers.publish(MarkerArray(markers=[marker]))

    def on_result(self, handle, key, sequence, future):
        if self.goal_handle is not handle: return
        was_cancelling = self.cancelling
        self.goal_handle = None; self.cancelling = False
        # A replaced/cancelled goal must not overwrite its successor or restart.
        if sequence != self.sequence:return
        try:
            status = future.result().status
            retryable = status == 6 and not was_cancelling
            if status == 4 and not self.arrival_verified():
                self.publish_status('arrival_unverified:'+key)
                status = 6
            if retryable and self.enabled and not self.hardware_inhibited and self.retry_count < self.max_retries:
                self.retry_count += 1
                self.retry_at = time.monotonic()+self.retry_delay
                self.pending = (sequence,key); self.pending_since = self.retry_at
                self.publish_retry('waiting')
                self.publish_status(f'retry_wait:{key}:attempt={self.retry_count}/{self.max_retries}:delay={self.retry_delay:g}')
                return
            self.publish_retry('exhausted' if status==6 else 'idle')
            self.publish_status(f'finished:{key}:status={status}')
        except Exception as exc: self.publish_status('result_error:'+str(exc))


    def arrival_verified(self):
        target, pose = self.active_target, self.goal_feedback
        if target is None or pose is None or pose.header.frame_id != 'map': return False
        age = (self.get_clock().now()-Time.from_msg(pose.header.stamp)).nanoseconds/1e9
        if not -.05 <= age <= 1.0: return False
        p, q = pose.pose.position, pose.pose.orientation
        t, r = target.pose.position, target.pose.orientation
        values = [p.x,p.y,q.x,q.y,q.z,q.w,t.x,t.y,r.x,r.y,r.z,r.w]
        if not all(math.isfinite(v) for v in values): return False
        angle = lambda a: math.atan2(2*(a.w*a.z+a.x*a.y), 1-2*(a.y*a.y+a.z*a.z))
        return math.hypot(p.x-t.x,p.y-t.y) <= self.active_arrival_xy and abs(math.remainder(angle(q)-angle(r), 2*math.pi)) <= self.arrival_yaw


def main():
    rclpy.init(); node = NamedGoalBridge()
    try: rclpy.spin(node)
    except KeyboardInterrupt: pass
    finally:
        if rclpy.ok(): node.stop()
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()


if __name__ == '__main__': main()

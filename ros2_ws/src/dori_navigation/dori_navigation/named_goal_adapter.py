"""Map-scoped destination registry and named action for HRI and dashboard clients."""
import hashlib
import json
import math
from pathlib import Path
import threading
import time
import zlib

import numpy as np
import rclpy
from action_msgs.msg import GoalStatus
from dori_msgs.action import Navigate, NavigateNamed
from nav_msgs.msg import OccupancyGrid
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from std_msgs.msg import String, Int32, Bool


def registered_goals(payload, key):
    """Validate the entire active-map registry before allowing any motion."""
    if not isinstance(payload, dict) or payload.get('version') != 1 or not isinstance(payload.get('maps'), dict):
        raise ValueError('Invalid destination registry')
    goals, names = {}, set()
    entries = payload['maps'].get(key, [])
    if not isinstance(entries, list):
        raise ValueError('Destination list is required')
    for item in entries:
        if not isinstance(item, dict) or not isinstance(item.get('name'), str) or not isinstance(item.get('id'), str):
            raise ValueError('Destination name and ID must be strings')
        name, identifier = item['name'].strip(), item['id']
        if not name or not identifier or name.casefold() in names or identifier in goals:
            raise ValueError('Empty/duplicate destination name or ID')
        if not all(type(item.get(k)) in (int, float) and math.isfinite(item[k]) for k in ('x', 'y', 'yaw')):
            raise ValueError('Non-finite destination pose')
        names.add(name.casefold())
        goals[identifier] = {**item, 'name': name}
    return goals


class NamedGoalAdapter(Node):
    def __init__(self):
        super().__init__('named_goal_adapter')
        self.declare_parameter('goals_file', '')
        self.declare_parameter('action_name', '/dori/nav/navigate_to')
        self.declare_parameter('named_action_name', '/dori/nav/navigate_named')
        self._lock = threading.RLock()
        self._busy = False
        self._key = None
        self._map = None
        self._goals = {}
        self._published = None
        self._enabled = False
        self._callbacks = ReentrantCallbackGroup()
        latch = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.locations = self.create_publisher(String, '/dori/nav/locations', latch)
        self.mode = self.create_publisher(Int32, '/NAVIGATION_MODE', 10)
        self.create_subscription(OccupancyGrid, '/map', self._on_map, latch)
        self.create_subscription(Bool, '/navigation/enabled', self._on_enabled, latch)
        self.create_timer(.5, self._reload)
        self._client = ActionClient(self, Navigate, self.get_parameter('action_name').value,
                                    callback_group=self._callbacks)
        self._server = ActionServer(self, NavigateNamed, self.get_parameter('named_action_name').value,
            execute_callback=self._execute, goal_callback=self._goal,
            cancel_callback=lambda _: CancelResponse.ACCEPT, callback_group=self._callbacks)

    def _on_enabled(self, msg):
        self._enabled = msg.data

    def _on_map(self, msg):
        if (msg.header.frame_id != 'map' or not math.isfinite(msg.info.resolution) or
                msg.info.resolution <= 0 or msg.info.width*msg.info.height != len(msg.data) or not msg.data):
            with self._lock:
                self._map, self._key = None, None
            self._reload()
            return
        q, p = msg.info.origin.orientation, msg.info.origin.position
        yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
        signature = (zlib.crc32(np.asarray(msg.data, dtype=np.int8).tobytes()),
                     msg.info.width, msg.info.height, msg.info.resolution, p.x, p.y, yaw)
        with self._lock:
            self._key = hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:24]
            self._map = msg
        self._reload()

    def _reload(self):
        value = self.get_parameter('goals_file').value
        try:
            payload = json.loads(Path(value).read_text()) if value else {'version': 1, 'maps': {}}
            with self._lock:
                self._goals = registered_goals(payload, self._key)
                text = json.dumps({'map_key': self._key, 'goals': list(self._goals.values())}, ensure_ascii=False)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            with self._lock:
                self._goals = {}
            text = json.dumps({'map_key': self._key, 'goals': [], 'error': str(exc)})
        if text != self._published:
            self._published = text
            self.locations.publish(String(data=text))

    def _resolve(self, value):
        candidates = [g for g in self._goals.values()
                      if g['id'] == value or g['name'].casefold() == value.strip().casefold()]
        if len(candidates) != 1:
            return None
        goal = candidates[0]
        msg = self._map
        if msg is None or msg.header.frame_id != 'map':
            return None
        # Reject occupied, unknown and out-of-map saved poses.
        q = msg.info.origin.orientation
        yaw = math.atan2(2*q.w*q.z, 1-2*q.z*q.z)
        dx, dy = goal['x']-msg.info.origin.position.x, goal['y']-msg.info.origin.position.y
        x = math.floor((math.cos(yaw)*dx+math.sin(yaw)*dy)/msg.info.resolution)
        y = math.floor((-math.sin(yaw)*dx+math.cos(yaw)*dy)/msg.info.resolution)
        if not (0 <= x < msg.info.width and 0 <= y < msg.info.height):
            return None
        if not 0 <= msg.data[y*msg.info.width+x] < 25:
            return None
        return dict(goal)

    def _goal(self, request):
        with self._lock:
            if self._busy or self._resolve(request.destination) is None:
                return GoalResponse.REJECT
            self._busy = True
            return GoalResponse.ACCEPT

    def _execute(self, outer):
        result = NavigateNamed.Result()
        handle = None
        try:
            with self._lock:
                point = self._resolve(outer.request.destination)
            if point is None or not self._client.wait_for_server(timeout_sec=2.):
                raise RuntimeError('Destination/map changed or navigation unavailable')
            goal = Navigate.Goal()
            goal.destination.header.frame_id = 'map'
            goal.destination.header.stamp = self.get_clock().now().to_msg()
            goal.destination.pose.position.x = float(point['x'])
            goal.destination.pose.position.y = float(point['y'])
            goal.destination.pose.orientation.z = math.sin(float(point['yaw'])/2)
            goal.destination.pose.orientation.w = math.cos(float(point['yaw'])/2)
            if outer.is_cancel_requested:
                outer.canceled()
                result.code = NavigateNamed.Result.CANCELED
                return result
            # An explicit named navigation request arms the same mode as a web Go.
            self.mode.publish(Int32(data=1))
            end = time.monotonic()+2.
            while rclpy.ok() and not self._enabled and not outer.is_cancel_requested and time.monotonic()<end:
                time.sleep(.01)
            if outer.is_cancel_requested:
                self.mode.publish(Int32(data=0))
                outer.canceled()
                result.code = NavigateNamed.Result.CANCELED
                return result
            if not self._enabled:
                raise RuntimeError('Navigation authority did not acknowledge enable')
            def feedback(message):
                if outer.is_active:
                    outer.publish_feedback(NavigateNamed.Feedback(
                        distance_remaining=message.feedback.distance_remaining,
                        state=message.feedback.state))
            sent = self._client.send_goal_async(goal, feedback_callback=feedback)
            end = time.monotonic()+5.
            while rclpy.ok() and not sent.done() and time.monotonic() < end:
                time.sleep(.01)
            if not sent.done():
                def cancel_late(f):
                    late = f.result()
                    if late and late.accepted:
                        late.cancel_goal_async()
                sent.add_done_callback(cancel_late)
                raise TimeoutError('Navigation admission timed out')
            handle = sent.result()
            if not handle or not handle.accepted:
                raise RuntimeError('Navigation rejected: busy, disarmed or hardware inhibited')
            future = handle.get_result_async()
            end, cancel_at = time.monotonic()+920., None
            while rclpy.ok() and not future.done():
                if (outer.is_cancel_requested or time.monotonic() > end) and cancel_at is None:
                    handle.cancel_goal_async()
                    cancel_at = time.monotonic()
                if cancel_at and time.monotonic()-cancel_at > 7.:
                    raise TimeoutError('Navigation cancellation timed out')
                time.sleep(.01)
            if not future.done():
                raise RuntimeError('Navigation interrupted by shutdown')
            terminal = future.result()
            result.code, result.message = terminal.result.code, terminal.result.message
            if outer.is_cancel_requested:
                result.code = NavigateNamed.Result.CANCELED
                outer.canceled()
            elif terminal.status == GoalStatus.STATUS_SUCCEEDED and result.code == 0:
                outer.succeed()
            else:
                outer.abort()
        except Exception as exc:
            if rclpy.ok() and handle and handle.accepted:
                handle.cancel_goal_async()
            if rclpy.ok() and ((handle and handle.accepted) or isinstance(exc, TimeoutError)):
                self.mode.publish(Int32(data=0))
            result.code, result.message = NavigateNamed.Result.INVALID_STATE, str(exc)
            if rclpy.ok() and outer.is_active:
                outer.abort()
        finally:
            with self._lock:
                self._busy = False
        return result


def main():
    rclpy.init()
    node = NamedGoalAdapter()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown(timeout_sec=8.)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

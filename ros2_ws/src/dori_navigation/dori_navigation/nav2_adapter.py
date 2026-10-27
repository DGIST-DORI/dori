"""Single motion authority between DORI clients and the private Nav2 action."""
import math
import threading
import time
from pathlib import Path

import rclpy
from action_msgs.msg import GoalStatus
from ament_index_python.packages import get_package_share_directory
from dori_msgs.action import Navigate
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.time import Time
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import Bool, Int32


class Nav2Adapter(Node):
    def __init__(self):
        super().__init__('nav2_adapter')
        for name, value in [('action_name', '/dori/nav/navigate_to'),
                            ('nav2_action_name', '/dori/internal/navigate_to_pose'),
                            ('required_frame', 'map'), ('accept_timeout', 5.0),
                            ('cancel_timeout', 5.0), ('execution_timeout', 900.0)]:
            self.declare_parameter(name, value)
        self._lock = threading.RLock()
        self._busy = False
        self._fault = False
        self._enabled = False
        self._inhibited = True
        self._nav2_goal = None
        self._active_dori_goal = None
        self._last_pose = None
        self._cancel_requested = False
        self._callbacks = ReentrantCallbackGroup()
        latch = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self._active_pub = self.create_publisher(Bool, '/navigation/goal_active', latch)
        self._enabled_pub = self.create_publisher(Bool, '/navigation/enabled', latch)
        self._mode_pub = self.create_publisher(Int32, '/NAVIGATION_MODE', 10)
        self._heartbeat = self.create_publisher(Bool, '/navigation/authority_heartbeat', 10)
        self.create_timer(.1, lambda: self._heartbeat.publish(Bool(data=not self._fault)))
        self.create_subscription(Int32, '/NAVIGATION_MODE', self._mode, 10)
        self.create_subscription(Bool, '/emergency_stop', self._estop, 10)
        self.create_subscription(Int32, '/system/action_state', self._hardware, latch)
        self._client = ActionClient(self, NavigateToPose,
            self.get_parameter('nav2_action_name').value, callback_group=self._callbacks)
        self._server = ActionServer(self, Navigate, self.get_parameter('action_name').value,
            execute_callback=self._execute, goal_callback=self._goal,
            cancel_callback=self._cancel, callback_group=self._callbacks)
        self._active_pub.publish(Bool(data=False))
        self._enabled_pub.publish(Bool(data=False))

    def _mode(self, msg):
        if msg.data not in (0, 1):
            return
        with self._lock:
            self._enabled = msg.data == 1 and not self._fault
            self._enabled_pub.publish(Bool(data=self._enabled))
            if not self._enabled:
                self._stop()

    def _estop(self, msg):
        if msg.data:
            self._mode(Int32(data=0))
            self._mode_pub.publish(Int32(data=0))

    def _hardware(self, msg):
        with self._lock:
            self._inhibited = msg.data not in (0, 1)
            if self._inhibited:
                self._stop()

    def _stop(self):
        self._active_pub.publish(Bool(data=False))
        if self._busy:
            self._cancel_requested = True

    def _goal(self, request):
        p, q = request.destination.pose.position, request.destination.pose.orientation
        valid = (request.destination.header.frame_id == self.get_parameter('required_frame').value
                 and all(math.isfinite(v) for v in (p.x, p.y, p.z, q.x, q.y, q.z, q.w))
                 and abs(p.z) < .01 and abs(q.x) < .01 and abs(q.y) < .01
                 and abs(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w-1.) < .01)
        with self._lock:
            if not valid or self._busy or self._fault or not self._enabled or self._inhibited:
                return GoalResponse.REJECT
            # Reserve at admission, before execute callbacks can race.
            self._busy = True
            self._cancel_requested = False
            return GoalResponse.ACCEPT

    def _cancel(self, _handle):
        with self._lock:
            self._stop()
        return CancelResponse.ACCEPT

    def _wait(self, future, timeout):
        deadline = time.monotonic() + timeout
        while rclpy.ok() and not future.done() and time.monotonic() < deadline:
            time.sleep(.01)
        if not future.done():
            raise TimeoutError('Nav2 response timeout')
        return future.result()

    def _execute(self, goal_handle):
        result = Navigate.Result()
        with self._lock:
            self._active_dori_goal = goal_handle
            self._last_pose = None
        try:
            if not self._client.wait_for_server(timeout_sec=2.):
                result.code = Navigate.Result.INVALID_STATE
                result.message = 'Nav2 action server unavailable'
                goal_handle.abort()
                return result
            goal = NavigateToPose.Goal()
            goal.pose = goal_handle.request.destination
            if goal_handle.request.precise:
                goal.behavior_tree = str(Path(get_package_share_directory('dori_navigation')) /
                                         'config/navigate_relative.xml')
            sent = self._client.send_goal_async(goal,
                feedback_callback=lambda msg: self._feedback(goal_handle, msg))
            try:
                handle = self._wait(sent, self.get_parameter('accept_timeout').value)
            except TimeoutError:
                # A late acceptance must never leave an orphan moving goal.
                def cancel_late(future):
                    try:
                        late = future.result()
                        if late and late.accepted:
                            late.cancel_goal_async()
                    except Exception as exc:
                        self.get_logger().error(f'Late Nav2 cancellation failed: {exc}')
                sent.add_done_callback(cancel_late)
                raise
            if not handle or not handle.accepted:
                result.code = Navigate.Result.PLANNING_FAILED
                result.message = 'Nav2 rejected goal'
                goal_handle.abort()
                return result
            with self._lock:
                self._nav2_goal = handle
                self._active_pub.publish(Bool(data=not self._cancel_requested and self._enabled))
            pending = handle.get_result_async()
            deadline = time.monotonic()+self.get_parameter('execution_timeout').value
            cancel_at = None
            while rclpy.ok() and not pending.done():
                with self._lock:
                    stop = self._cancel_requested or goal_handle.is_cancel_requested
                if time.monotonic() > deadline:
                    stop = True
                if stop and cancel_at is None:
                    self._active_pub.publish(Bool(data=False))
                    handle.cancel_goal_async()
                    cancel_at = time.monotonic()
                if cancel_at and time.monotonic()-cancel_at > self.get_parameter('cancel_timeout').value:
                    raise TimeoutError('Nav2 did not terminate after cancellation; restart required')
                time.sleep(.01)
            if not pending.done():
                raise RuntimeError('ROS shutdown during navigation')
            terminal = pending.result().status
            with self._lock:
                stopped = self._cancel_requested or goal_handle.is_cancel_requested or cancel_at is not None
            if terminal == GoalStatus.STATUS_SUCCEEDED and not stopped and self._arrival(goal_handle):
                result.code, result.message = Navigate.Result.SUCCESS, 'Destination reached'
                goal_handle.succeed()
            elif goal_handle.is_cancel_requested:
                result.code, result.message = Navigate.Result.CANCELED, 'Navigation canceled'
                goal_handle.canceled()
            else:
                result.code = Navigate.Result.CANCELED if stopped else Navigate.Result.PLANNING_FAILED
                result.message = ('Nav2 reported success without a fresh pose inside arrival tolerance'
                    if terminal == GoalStatus.STATUS_SUCCEEDED and not stopped else
                    f'Navigation stopped (Nav2 status {terminal})')
                goal_handle.abort()
        except Exception as exc:
            with self._lock:
                self._fault = True
                self._enabled = False
            if rclpy.ok():
                self._mode_pub.publish(Int32(data=0))
                self._enabled_pub.publish(Bool(data=False))
            result.code, result.message = Navigate.Result.INVALID_STATE, str(exc)
            if rclpy.ok() and goal_handle.is_active:
                goal_handle.abort()
            self.get_logger().error(str(exc))
        finally:
            with self._lock:
                if rclpy.ok():
                    self._active_pub.publish(Bool(data=False))
                self._nav2_goal = self._active_dori_goal = None
                self._busy = False
        return result

    def _arrival(self, handle):
        with self._lock:
            pose = self._last_pose
        if pose is None or pose.header.frame_id != 'map':
            return False
        age = (self.get_clock().now()-Time.from_msg(pose.header.stamp)).nanoseconds/1e9
        target = handle.request.destination.pose.position
        tolerance = .15 if handle.request.precise else .35
        return -.05 <= age <= 1.0 and math.hypot(pose.pose.position.x-target.x,
                                               pose.pose.position.y-target.y) <= tolerance

    def _feedback(self, handle, message):
        if handle.is_active:
            with self._lock:
                if self._active_dori_goal is handle:
                    self._last_pose = message.feedback.current_pose
            feedback = Navigate.Feedback()
            feedback.distance_remaining = message.feedback.distance_remaining
            feedback.current_pose = message.feedback.current_pose
            feedback.state = 'navigating'
            feedback.status_message = 'Nav2 navigation in progress'
            handle.publish_feedback(feedback)


def main():
    rclpy.init()
    node = Nav2Adapter()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node._mode_pub.publish(Int32(data=0))
        executor.shutdown(timeout_sec=6.)
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

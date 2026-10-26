"""Expose DORI's navigation action through Nav2's NavigateToPose action."""

from __future__ import annotations

import threading
import time

import rclpy
from action_msgs.msg import GoalStatus
from dori_msgs.action import Navigate
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node


class Nav2Adapter(Node):
    """The only DORI-facing navigator; Nav2 remains the motion authority."""

    def __init__(self) -> None:
        super().__init__('nav2_adapter')
        self.declare_parameter('action_name', '/dori/nav/navigate_to')
        self.declare_parameter('nav2_action_name', '/dori/internal/navigate_to_pose')
        self.declare_parameter('required_frame', 'map')

        self._lock = threading.Lock()
        self._nav2_goal = None
        self._active_dori_goal = None
        self._callbacks = ReentrantCallbackGroup()
        self._client = ActionClient(
            self,
            NavigateToPose,
            self.get_parameter('nav2_action_name').value,
            callback_group=self._callbacks,
        )
        self._server = ActionServer(
            self,
            Navigate,
            self.get_parameter('action_name').value,
            execute_callback=self._execute,
            goal_callback=self._goal,
            cancel_callback=self._cancel,
            callback_group=self._callbacks,
        )

    def _goal(self, request: Navigate.Goal) -> GoalResponse:
        frame = request.destination.header.frame_id
        if frame != self.get_parameter('required_frame').value:
            self.get_logger().warning('Rejecting goal with frame %r', frame)
            return GoalResponse.REJECT
        with self._lock:
            return GoalResponse.REJECT if self._active_dori_goal else GoalResponse.ACCEPT

    def _cancel(self, _goal_handle) -> CancelResponse:
        with self._lock:
            nav2_goal = self._nav2_goal
        if nav2_goal is not None:
            nav2_goal.cancel_goal_async()
        return CancelResponse.ACCEPT

    def _execute(self, goal_handle):
        result = Navigate.Result()
        with self._lock:
            self._active_dori_goal = goal_handle

        try:
            if not self._client.wait_for_server(timeout_sec=5.0):
                result.code = Navigate.Result.INVALID_STATE
                result.message = 'Nav2 NavigateToPose action server is unavailable'
                goal_handle.abort()
                return result

            nav2_goal = NavigateToPose.Goal()
            nav2_goal.pose = goal_handle.request.destination
            sent = self._client.send_goal_async(nav2_goal, feedback_callback=lambda feedback: self._feedback(goal_handle, feedback))
            while rclpy.ok() and not sent.done():
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    result.code = Navigate.Result.CANCELED
                    result.message = 'Navigation canceled before Nav2 accepted the goal'
                    return result
                time.sleep(0.02)

            handle = sent.result()
            if handle is None or not handle.accepted:
                result.code = Navigate.Result.PLANNING_FAILED
                result.message = 'Nav2 rejected the navigation goal'
                goal_handle.abort()
                return result
            with self._lock:
                self._nav2_goal = handle

            nav2_result = handle.get_result_async()
            while rclpy.ok() and not nav2_result.done():
                if goal_handle.is_cancel_requested:
                    handle.cancel_goal_async()
                time.sleep(0.02)

            terminal = nav2_result.result().status
            if terminal == GoalStatus.STATUS_SUCCEEDED:
                result.code = Navigate.Result.SUCCESS
                result.message = 'Nav2 reached the destination'
                goal_handle.succeed()
            elif terminal == GoalStatus.STATUS_CANCELED or goal_handle.is_cancel_requested:
                result.code = Navigate.Result.CANCELED
                result.message = 'Navigation canceled'
                goal_handle.canceled()
            else:
                result.code = Navigate.Result.PLANNING_FAILED
                result.message = f'Nav2 ended with status {terminal}'
                goal_handle.abort()
            return result
        finally:
            with self._lock:
                self._nav2_goal = None
                self._active_dori_goal = None

    @staticmethod
    def _feedback(goal_handle, message) -> None:
        nav2_feedback = message.feedback
        feedback = Navigate.Feedback()
        feedback.distance_remaining = nav2_feedback.distance_remaining
        feedback.state = 'navigating'
        feedback.status_message = 'Nav2 is navigating to the requested destination'
        goal_handle.publish_feedback(feedback)


def main() -> None:
    rclpy.init()
    node = Nav2Adapter()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

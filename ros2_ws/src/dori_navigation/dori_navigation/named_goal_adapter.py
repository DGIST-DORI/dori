"""Resolve DORI named destinations and send them through the public action."""

from __future__ import annotations

import json
import math
from pathlib import Path

import rclpy
from dori_msgs.action import Navigate
from geometry_msgs.msg import PoseStamped
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String


class NamedGoalAdapter(Node):
    """Converts a configured location name to a DORI Navigate action goal."""

    def __init__(self) -> None:
        super().__init__('named_goal_adapter')
        self.declare_parameter('goals_file', '')
        self.declare_parameter('goal_topic', '/dori/internal/named_goal')
        self.declare_parameter('action_name', '/dori/nav/navigate_to')
        self._goals = self._load_goals(self.get_parameter('goals_file').value)
        self._client = ActionClient(self, Navigate, self.get_parameter('action_name').value)
        self.create_subscription(String, self.get_parameter('goal_topic').value, self._on_goal, 10)

    def _load_goals(self, value: str) -> dict[str, dict]:
        if not value:
            self.get_logger().warning('No named-goal file configured; named navigation is disabled')
            return {}
        try:
            payload = json.loads(Path(value).read_text())
            maps = payload.get('maps', {})
            entries = next(iter(maps.values()), [])
            goals = {entry['name']: entry for entry in entries}
            if not goals:
                raise ValueError('no goals were found')
            return goals
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            self.get_logger().error('Cannot load named goals: %s', exc)
            return {}

    def _on_goal(self, message: String) -> None:
        goal = self._goals.get(message.data.strip())
        if goal is None:
            self.get_logger().error('Unknown named destination: %s', message.data)
            return
        if not self._client.wait_for_server(timeout_sec=2.0):
            self.get_logger().error('DORI navigation action server is unavailable')
            return
        request = Navigate.Goal()
        request.destination = PoseStamped()
        request.destination.header.frame_id = 'map'
        request.destination.header.stamp = self.get_clock().now().to_msg()
        request.destination.pose.position.x = float(goal['x'])
        request.destination.pose.position.y = float(goal['y'])
        yaw = float(goal.get('yaw', 0.0))
        request.destination.pose.orientation.z = math.sin(yaw / 2.0)
        request.destination.pose.orientation.w = math.cos(yaw / 2.0)
        self._client.send_goal_async(request)


def main() -> None:
    rclpy.init()
    node = NamedGoalAdapter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

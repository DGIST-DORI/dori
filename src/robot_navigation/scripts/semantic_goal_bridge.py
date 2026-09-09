#!/usr/bin/env python3
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import rclpy
import yaml
from geometry_msgs.msg import PoseStamped, Quaternion
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String


def yaw_to_quaternion(yaw: float) -> Quaternion:
    half = yaw * 0.5
    quat = Quaternion()
    quat.z = math.sin(half)
    quat.w = math.cos(half)
    return quat


class SemanticGoalBridge(Node):
    def __init__(self) -> None:
        super().__init__("semantic_goal_bridge")

        root_dir = Path(__file__).resolve().parents[1]
        default_file = str(root_dir / "maps" / "isaac_map.semantic.yaml")

        self.declare_parameter("semantic_points_file", default_file)
        self.declare_parameter("goal_topic", "/semantic_goal")
        self.declare_parameter("status_topic", "/semantic_goal_status")
        self.declare_parameter("action_name", "navigate_to_pose")

        self.semantic_points_file = Path(
            self.get_parameter("semantic_points_file").get_parameter_value().string_value
        )
        goal_topic = self.get_parameter("goal_topic").get_parameter_value().string_value
        status_topic = self.get_parameter("status_topic").get_parameter_value().string_value
        action_name = self.get_parameter("action_name").get_parameter_value().string_value

        self.points_document = self._load_points()
        self.action_client = ActionClient(self, NavigateToPose, action_name)
        self.status_publisher = self.create_publisher(String, status_topic, 10)
        self.goal_subscription = self.create_subscription(
            String,
            goal_topic,
            self._on_goal_key,
            10,
        )

        names = ", ".join(sorted(self.points_document["points"].keys())) or "(none)"
        self.get_logger().info(
            f"Loaded semantic points from {self.semantic_points_file}: {names}"
        )

    def _load_points(self) -> dict[str, Any]:
        document = {
            "map": "isaac_map",
            "frame_id": "map",
            "points": {},
        }
        if not self.semantic_points_file.exists():
            self.get_logger().warn(
                f"Semantic points file not found: {self.semantic_points_file}"
            )
            return document

        with self.semantic_points_file.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}

        document.update({k: v for k, v in loaded.items() if k != "points"})
        document["points"] = loaded.get("points", {}) or {}
        return document

    def _publish_status(self, text: str) -> None:
        self.status_publisher.publish(String(data=text))

    def _on_goal_key(self, message: String) -> None:
        key = message.data.strip()
        if not key:
            return

        if key == "reload":
            self.points_document = self._load_points()
            names = ", ".join(sorted(self.points_document["points"].keys())) or "(none)"
            self.get_logger().info(f"Reloaded semantic points: {names}")
            self._publish_status(f"reloaded:{names}")
            return

        if key == "list":
            names = ",".join(sorted(self.points_document["points"].keys()))
            self._publish_status(f"list:{names}")
            return

        point = self.points_document["points"].get(key)
        if point is None:
            self.get_logger().warn(f"Unknown semantic goal key: {key}")
            self._publish_status(f"unknown:{key}")
            return

        if not self.action_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().error("Nav2 action server 'navigate_to_pose' is not available")
            self._publish_status(f"server_unavailable:{key}")
            return

        pose = point.get("pose", {})
        frame_id = point.get("frame_id") or self.points_document.get("frame_id", "map")

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.header.frame_id = frame_id
        goal.pose.pose.position.x = float(pose.get("x", 0.0))
        goal.pose.pose.position.y = float(pose.get("y", 0.0))
        goal.pose.pose.orientation = yaw_to_quaternion(float(pose.get("yaw", 0.0)))

        self.get_logger().info(
            f"Sending semantic goal '{key}' -> frame={frame_id}, "
            f"x={goal.pose.pose.position.x:.3f}, "
            f"y={goal.pose.pose.position.y:.3f}, "
            f"yaw={float(pose.get('yaw', 0.0)):.3f}"
        )
        self._publish_status(f"sent:{key}")

        send_future = self.action_client.send_goal_async(goal)
        send_future.add_done_callback(lambda future: self._on_goal_response(key, future))

    def _on_goal_response(self, key: str, future: Any) -> None:
        goal_handle = future.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().warn(f"Semantic goal rejected: {key}")
            self._publish_status(f"rejected:{key}")
            return

        self.get_logger().info(f"Semantic goal accepted: {key}")
        self._publish_status(f"accepted:{key}")
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(lambda future: self._on_goal_result(key, future))

    def _on_goal_result(self, key: str, future: Any) -> None:
        result = future.result()
        if result is None:
            self.get_logger().warn(f"Semantic goal result missing: {key}")
            self._publish_status(f"result_missing:{key}")
            return

        status = int(result.status)
        self.get_logger().info(f"Semantic goal finished: {key}, status={status}")
        self._publish_status(f"finished:{key}:status={status}")


def main() -> None:
    rclpy.init()
    node = SemanticGoalBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()

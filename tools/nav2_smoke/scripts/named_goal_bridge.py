#!/usr/bin/env python3
from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

import rclpy
from geometry_msgs.msg import PoseStamped, Quaternion
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String
from visualization_msgs.msg import Marker, MarkerArray


def yaw_deg_to_quaternion(yaw_deg: float) -> Quaternion:
    yaw = math.radians(yaw_deg)
    half = yaw * 0.5
    quat = Quaternion()
    quat.z = math.sin(half)
    quat.w = math.cos(half)
    return quat


def load_points_csv(points_file: Path) -> dict[str, dict[str, Any]]:
    points: dict[str, dict[str, Any]] = {}
    if not points_file.exists():
        return points

    with points_file.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            points[name] = {
                "name": name,
                "x": float(row.get("x", 0.0)),
                "y": float(row.get("y", 0.0)),
                "yaw_deg": float(row.get("yaw_deg", 0.0)),
                "frame_id": (row.get("frame_id") or "map").strip() or "map",
            }
    return points


class NamedGoalBridge(Node):
    def __init__(self) -> None:
        super().__init__("named_goal_bridge")

        root_dir = Path(__file__).resolve().parents[1]
        default_points_file = str(root_dir / "maps" / "isaac_saved_map.points.csv")

        self.declare_parameter("points_file", default_points_file)
        self.declare_parameter("goal_topic", "/named_goal")
        self.declare_parameter("status_topic", "/named_goal_status")
        self.declare_parameter("action_name", "navigate_to_pose")
        self.declare_parameter("goal_marker_topic", "/named_goal_marker")

        self.points_file = Path(self.get_parameter("points_file").get_parameter_value().string_value)
        goal_topic = self.get_parameter("goal_topic").get_parameter_value().string_value
        status_topic = self.get_parameter("status_topic").get_parameter_value().string_value
        action_name = self.get_parameter("action_name").get_parameter_value().string_value
        goal_marker_topic = self.get_parameter("goal_marker_topic").get_parameter_value().string_value

        self.points = load_points_csv(self.points_file)
        self.action_client = ActionClient(self, NavigateToPose, action_name)
        self.status_publisher = self.create_publisher(String, status_topic, 10)
        self.goal_marker_publisher = self.create_publisher(MarkerArray, goal_marker_topic, 10)
        self.goal_subscription = self.create_subscription(String, goal_topic, self.on_goal_key, 10)

        names = ", ".join(sorted(self.points.keys())) or "(none)"
        self.get_logger().info(f"Loaded named points from {self.points_file}: {names}")

    def publish_status(self, text: str) -> None:
        self.status_publisher.publish(String(data=text))

    def publish_goal_marker(self, point: dict[str, Any]) -> None:
        stamp = self.get_clock().now().to_msg()
        quaternion = yaw_deg_to_quaternion(point["yaw_deg"])

        arrow = Marker()
        arrow.header.stamp = stamp
        arrow.header.frame_id = point["frame_id"]
        arrow.ns = "named_goal"
        arrow.id = 0
        arrow.type = Marker.ARROW
        arrow.action = Marker.ADD
        arrow.pose.position.x = point["x"]
        arrow.pose.position.y = point["y"]
        arrow.pose.position.z = 0.05
        arrow.pose.orientation = quaternion
        arrow.scale.x = 0.6
        arrow.scale.y = 0.12
        arrow.scale.z = 0.12
        arrow.color.a = 1.0
        arrow.color.r = 1.0
        arrow.color.g = 0.2
        arrow.color.b = 0.0

        text = Marker()
        text.header.stamp = stamp
        text.header.frame_id = point["frame_id"]
        text.ns = "named_goal"
        text.id = 1
        text.type = Marker.TEXT_VIEW_FACING
        text.action = Marker.ADD
        text.pose.position.x = point["x"]
        text.pose.position.y = point["y"]
        text.pose.position.z = 0.45
        text.pose.orientation.w = 1.0
        text.scale.z = 0.3
        text.color.a = 1.0
        text.color.r = 1.0
        text.color.g = 1.0
        text.color.b = 0.0
        text.text = point["name"]

        self.goal_marker_publisher.publish(MarkerArray(markers=[arrow, text]))

    def on_goal_key(self, message: String) -> None:
        key = message.data.strip()
        if not key:
            return

        if key == "reload":
            self.points = load_points_csv(self.points_file)
            names = ", ".join(sorted(self.points.keys())) or "(none)"
            self.get_logger().info(f"Reloaded named points: {names}")
            self.publish_status(f"reloaded:{names}")
            return

        if key == "list":
            names = ",".join(sorted(self.points.keys()))
            self.publish_status(f"list:{names}")
            return

        point = self.points.get(key)
        if point is None:
            self.get_logger().warn(f"Unknown named goal: {key}")
            self.publish_status(f"unknown:{key}")
            return

        if not self.action_client.wait_for_server(timeout_sec=2.0):
            self.get_logger().error("Nav2 action server 'navigate_to_pose' is not available")
            self.publish_status(f"server_unavailable:{key}")
            return

        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.header.frame_id = point["frame_id"]
        goal.pose.pose.position.x = point["x"]
        goal.pose.pose.position.y = point["y"]
        goal.pose.pose.orientation = yaw_deg_to_quaternion(point["yaw_deg"])
        self.publish_goal_marker(point)

        self.get_logger().info(
            f"Sending named goal '{key}' -> frame={point['frame_id']}, "
            f"x={point['x']:.3f}, y={point['y']:.3f}, yaw_deg={point['yaw_deg']:.1f}"
        )
        self.publish_status(f"sent:{key}")

        send_future = self.action_client.send_goal_async(goal)
        send_future.add_done_callback(lambda future: self.on_goal_response(key, future))

    def on_goal_response(self, key: str, future: Any) -> None:
        goal_handle = future.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().warn(f"Named goal rejected: {key}")
            self.publish_status(f"rejected:{key}")
            return

        self.get_logger().info(f"Named goal accepted: {key}")
        self.publish_status(f"accepted:{key}")
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(lambda future: self.on_goal_result(key, future))

    def on_goal_result(self, key: str, future: Any) -> None:
        result = future.result()
        if result is None:
            self.get_logger().warn(f"Named goal result missing: {key}")
            self.publish_status(f"result_missing:{key}")
            return

        status = int(result.status)
        self.get_logger().info(f"Named goal finished: {key}, status={status}")
        self.publish_status(f"finished:{key}:status={status}")


def main() -> None:
    rclpy.init()
    node = NamedGoalBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import math
import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node


class InitialPoseFromOdom(Node):
    def __init__(self) -> None:
        super().__init__("initial_pose_from_odom")

        self.declare_parameter("odom_topic", "/nav2/odom_restamped")
        self.declare_parameter("initialpose_topic", "/initialpose")
        self.declare_parameter("frame_id", "map")
        self.declare_parameter("publish_count", 3)
        self.declare_parameter("publish_period_sec", 0.3)
        self.declare_parameter("x_offset", 0.0)
        self.declare_parameter("y_offset", 0.0)
        self.declare_parameter("yaw_offset_deg", 0.0)

        odom_topic = self.get_parameter("odom_topic").get_parameter_value().string_value
        initialpose_topic = self.get_parameter("initialpose_topic").get_parameter_value().string_value
        self._frame_id = self.get_parameter("frame_id").get_parameter_value().string_value
        self._publish_count = self.get_parameter("publish_count").get_parameter_value().integer_value
        self._publish_period_sec = (
            self.get_parameter("publish_period_sec").get_parameter_value().double_value
        )
        self._x_offset = self.get_parameter("x_offset").get_parameter_value().double_value
        self._y_offset = self.get_parameter("y_offset").get_parameter_value().double_value
        self._yaw_offset_deg = self.get_parameter("yaw_offset_deg").get_parameter_value().double_value

        self._publisher = self.create_publisher(PoseWithCovarianceStamped, initialpose_topic, 10)
        self._subscription = self.create_subscription(Odometry, odom_topic, self._on_odom, 10)
        self._published = False

        self.get_logger().info(
            f"Waiting for odometry on '{odom_topic}' to publish initial pose on "
            f"'{initialpose_topic}' in frame '{self._frame_id}'"
        )

    def _on_odom(self, message: Odometry) -> None:
        if self._published:
            return

        pose = PoseWithCovarianceStamped()
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.header.frame_id = self._frame_id
        pose.pose.pose.position.x = float(message.pose.pose.position.x) + self._x_offset
        pose.pose.pose.position.y = float(message.pose.pose.position.y) + self._y_offset
        pose.pose.pose.position.z = 0.0
        pose.pose.pose.orientation = message.pose.pose.orientation

        if abs(self._yaw_offset_deg) > 1e-6:
            q = pose.pose.pose.orientation
            current_yaw = math.atan2(
                2.0 * (q.w * q.z + q.x * q.y),
                1.0 - 2.0 * (q.y * q.y + q.z * q.z),
            )
            yaw = current_yaw + math.radians(self._yaw_offset_deg)
            q.x = 0.0
            q.y = 0.0
            q.z = math.sin(yaw * 0.5)
            q.w = math.cos(yaw * 0.5)

        pose.pose.covariance = [
            0.25, 0.0, 0.0, 0.0, 0.0, 0.0,
            0.0, 0.25, 0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
            0.0, 0.0, 0.0, 0.0, 0.0, 0.0685,
        ]

        for _ in range(max(1, int(self._publish_count))):
            pose.header.stamp = self.get_clock().now().to_msg()
            self._publisher.publish(pose)
            time.sleep(self._publish_period_sec)

        self._published = True
        self.get_logger().info(
            "Published initial pose from odometry: "
            f"x={pose.pose.pose.position.x:.3f}, "
            f"y={pose.pose.pose.position.y:.3f}, "
            f"frame={self._frame_id}"
        )
        self.create_timer(0.5, self._shutdown_once)

    def _shutdown_once(self) -> None:
        if rclpy.ok():
            rclpy.shutdown()


def main() -> None:
    rclpy.init()
    node = InitialPoseFromOdom()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()

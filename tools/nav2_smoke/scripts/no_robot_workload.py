#!/usr/bin/env python3
"""Fake odom/TF and repeated Nav2 goals for a real-LiDAR, no-robot load test."""
from __future__ import annotations

import argparse
import csv
import math
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped, TransformStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import Odometry
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from tf2_ros import TransformBroadcaster


class NoRobotWorkload(Node):
    def __init__(self, points_file: Path, start_x: float, start_y: float, start_yaw_deg: float) -> None:
        super().__init__("no_robot_nav_workload")
        with points_file.open("r", encoding="utf-8", newline="") as handle:
            self.goals = list(csv.DictReader(handle))
        if not self.goals:
            raise RuntimeError(f"No points in {points_file}")
        self.start_x, self.start_y = start_x, start_y
        self.start_yaw = math.radians(start_yaw_deg)
        self.started = time.monotonic()
        self.initial_count = self.goal_index = 0
        self.goal_pending = False

        initial_qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                                 durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.odom_pub = self.create_publisher(Odometry, "/odom", 20)
        self.initial_pub = self.create_publisher(PoseWithCovarianceStamped, "/initialpose", initial_qos)
        self.tf_pub = TransformBroadcaster(self)
        self.action = ActionClient(self, NavigateToPose, "/navigate_to_pose")
        self.create_timer(1.0 / 30.0, self._publish_odom)
        self.create_timer(1.0, self._publish_initial)
        self.create_timer(2.0, self._send_workload_goal)

    def _publish_odom(self) -> None:
        elapsed = time.monotonic() - self.started
        # Small deterministic changes cross AMCL update thresholds without representing a real robot.
        x = 0.14 * math.sin(elapsed * 0.55)
        yaw = 0.18 * math.sin(elapsed * 0.40)
        linear = 0.14 * 0.55 * math.cos(elapsed * 0.55)
        angular = 0.18 * 0.40 * math.cos(elapsed * 0.40)
        stamp = self.get_clock().now().to_msg()
        tf = TransformStamped()
        tf.header.stamp, tf.header.frame_id, tf.child_frame_id = stamp, "odom", "base_link"
        tf.transform.translation.x = x
        tf.transform.rotation.z, tf.transform.rotation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        self.tf_pub.sendTransform(tf)
        odom = Odometry()
        odom.header.stamp, odom.header.frame_id, odom.child_frame_id = stamp, "odom", "base_link"
        odom.pose.pose.position.x = x
        odom.pose.pose.orientation.z, odom.pose.pose.orientation.w = tf.transform.rotation.z, tf.transform.rotation.w
        odom.twist.twist.linear.x, odom.twist.twist.angular.z = linear, angular
        self.odom_pub.publish(odom)

    def _publish_initial(self) -> None:
        if self.initial_count >= 12:
            return
        message = PoseWithCovarianceStamped()
        message.header.stamp = (self.get_clock().now() - Duration(seconds=0.1)).to_msg()
        message.header.frame_id = "map"
        message.pose.pose.position.x, message.pose.pose.position.y = self.start_x, self.start_y
        message.pose.pose.orientation.z = math.sin(self.start_yaw / 2)
        message.pose.pose.orientation.w = math.cos(self.start_yaw / 2)
        message.pose.covariance[0], message.pose.covariance[7], message.pose.covariance[35] = 0.25, 0.25, 0.07
        self.initial_pub.publish(message)
        self.initial_count += 1

    def _send_workload_goal(self) -> None:
        if self.goal_pending or time.monotonic() - self.started < 10 or not self.action.server_is_ready():
            return
        point = self.goals[self.goal_index % len(self.goals)]
        goal = NavigateToPose.Goal()
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.header.frame_id = point.get("frame_id") or "map"
        goal.pose.pose.position.x, goal.pose.pose.position.y = float(point["x"]), float(point["y"])
        yaw = math.radians(float(point.get("yaw_deg") or 0.0))
        goal.pose.pose.orientation.z, goal.pose.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        self.goal_pending = True
        future = self.action.send_goal_async(goal)
        future.add_done_callback(self._goal_response)

    def _goal_response(self, future) -> None:
        handle = future.result()
        if handle is None or not handle.accepted:
            self.goal_pending = False
            return
        handle.get_result_async().add_done_callback(self._goal_finished)

    def _goal_finished(self, _future) -> None:
        self.goal_index += 1
        self.goal_pending = False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--points-file", required=True, type=Path)
    parser.add_argument("--start-x", type=float, default=-2.824661)
    parser.add_argument("--start-y", type=float, default=0.783190)
    parser.add_argument("--start-yaw-deg", type=float, default=0.0)
    args = parser.parse_args()
    rclpy.init()
    node = NoRobotWorkload(args.points_file, args.start_x, args.start_y, args.start_yaw_deg)
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

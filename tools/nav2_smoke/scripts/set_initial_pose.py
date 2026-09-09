#!/usr/bin/env python3
import argparse
import math
import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish an AMCL initial pose")
    parser.add_argument("x", type=float)
    parser.add_argument("y", type=float)
    parser.add_argument("yaw_deg", type=float)
    args = parser.parse_args()
    rclpy.init()
    node = Node("set_initial_pose_once")
    qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                     durability=DurabilityPolicy.TRANSIENT_LOCAL)
    publisher = node.create_publisher(PoseWithCovarianceStamped, "/initialpose", qos)
    deadline = time.monotonic() + 3.0
    while publisher.get_subscription_count() == 0 and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
    yaw = math.radians(args.yaw_deg)
    message = PoseWithCovarianceStamped()
    message.header.stamp = node.get_clock().now().to_msg()
    message.header.frame_id = "map"
    message.pose.pose.position.x, message.pose.pose.position.y = args.x, args.y
    message.pose.pose.orientation.z, message.pose.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
    message.pose.covariance[0], message.pose.covariance[7], message.pose.covariance[35] = 0.25, 0.25, 0.07
    for _ in range(3):
        publisher.publish(message)
        rclpy.spin_once(node, timeout_sec=0.2)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()

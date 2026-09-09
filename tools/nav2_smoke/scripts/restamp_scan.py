#!/usr/bin/env python3
"""Restamp the real C1 scan to the same ROS clock used by fake odom/TF."""
import argparse

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan


class ScanRestamper(Node):
    def __init__(self, input_topic: str, output_topic: str) -> None:
        super().__init__("c1_scan_restamper")
        self.publisher = self.create_publisher(LaserScan, output_topic, qos_profile_sensor_data)
        self.subscription = self.create_subscription(
            LaserScan, input_topic, self._callback, qos_profile_sensor_data
        )
        self.count = 0

    def _callback(self, message: LaserScan) -> None:
        original = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
        message.header.stamp = self.get_clock().now().to_msg()
        self.publisher.publish(message)
        self.count += 1
        if self.count == 1:
            current = message.header.stamp.sec + message.header.stamp.nanosec * 1e-9
            self.get_logger().info(
                f"First C1 scan restamped: original={original:.6f}, current={current:.6f}, "
                f"frame={message.header.frame_id}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="/scan_raw")
    parser.add_argument("--output", default="/scan")
    args = parser.parse_args()
    rclpy.init()
    node = ScanRestamper(args.input, args.output)
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

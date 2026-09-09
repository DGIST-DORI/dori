#!/usr/bin/env python3
from __future__ import annotations

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import LaserScan


class ScanRestamper(Node):
    def __init__(self) -> None:
        super().__init__("scan_restamper")

        self.declare_parameter("input_scan_topic", "/scan")
        self.declare_parameter("output_scan_topic", "/scan_restamped")

        input_topic = self.get_parameter("input_scan_topic").get_parameter_value().string_value
        output_topic = self.get_parameter("output_scan_topic").get_parameter_value().string_value

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=50,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )

        self._pub = self.create_publisher(LaserScan, output_topic, qos)
        self._sub = self.create_subscription(LaserScan, input_topic, self._handle_scan, qos)
        self._counter = 0

        self.get_logger().info(f"Restamping LaserScan from '{input_topic}' to '{output_topic}'")

    def _handle_scan(self, msg: LaserScan) -> None:
        restamped = LaserScan()
        restamped.header = msg.header
        restamped.header.stamp = self.get_clock().now().to_msg()
        restamped.angle_min = msg.angle_min
        restamped.angle_max = msg.angle_max
        restamped.angle_increment = msg.angle_increment
        restamped.time_increment = msg.time_increment
        restamped.scan_time = msg.scan_time
        restamped.range_min = msg.range_min
        restamped.range_max = msg.range_max
        restamped.ranges = msg.ranges
        restamped.intensities = msg.intensities
        self._pub.publish(restamped)

        self._counter += 1
        if self._counter == 1:
            original = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            now = restamped.header.stamp.sec + restamped.header.stamp.nanosec * 1e-9
            self.get_logger().info(
                f"First scan restamped: original={original:.3f}s new={now:.3f}s frame={msg.header.frame_id}"
            )


def main() -> None:
    rclpy.init()
    node = ScanRestamper()
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

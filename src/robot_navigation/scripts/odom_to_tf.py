#!/usr/bin/env python3
from __future__ import annotations

import rclpy
from geometry_msgs.msg import TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from tf2_ros import TransformBroadcaster


class OdomToTfBridge(Node):
    def __init__(self) -> None:
        super().__init__("odom_to_tf_bridge")

        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("output_odom_topic", "/odom_restamped")
        self.declare_parameter("restamp_to_clock", True)
        odom_topic = self.get_parameter("odom_topic").get_parameter_value().string_value
        output_odom_topic = self.get_parameter("output_odom_topic").get_parameter_value().string_value
        self._restamp_to_clock = self.get_parameter("restamp_to_clock").get_parameter_value().bool_value

        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=50,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )

        self._tf_broadcaster = TransformBroadcaster(self)
        self._odom_pub = self.create_publisher(Odometry, output_odom_topic, qos)
        self._sub = self.create_subscription(Odometry, odom_topic, self._handle_odom, qos)
        self._logged_first = False

        self.get_logger().info(
            f"Bridging odometry topic '{odom_topic}' into TF and '{output_odom_topic}' "
            f"(restamp_to_clock={self._restamp_to_clock})"
        )

    def _handle_odom(self, msg: Odometry) -> None:
        stamp = self.get_clock().now().to_msg() if self._restamp_to_clock else msg.header.stamp

        odom_msg = Odometry()
        odom_msg.header = msg.header
        odom_msg.header.stamp = stamp
        odom_msg.child_frame_id = msg.child_frame_id
        odom_msg.pose = msg.pose
        odom_msg.twist = msg.twist
        self._odom_pub.publish(odom_msg)

        transform = TransformStamped()
        transform.header = odom_msg.header
        transform.child_frame_id = msg.child_frame_id
        transform.transform.translation.x = msg.pose.pose.position.x
        transform.transform.translation.y = msg.pose.pose.position.y
        transform.transform.translation.z = msg.pose.pose.position.z
        transform.transform.rotation = msg.pose.pose.orientation
        self._tf_broadcaster.sendTransform(transform)

        if not self._logged_first:
            original = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
            new = stamp.sec + stamp.nanosec * 1e-9
            self.get_logger().info(
                f"First odom restamp: original={original:.3f}s new={new:.3f}s child={msg.child_frame_id}"
            )
            self._logged_first = True


def main() -> None:
    rclpy.init()
    node = OdomToTfBridge()
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

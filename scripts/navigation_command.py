#!/usr/bin/env python3
"""Explicit AUTO stop or a map-frame initial pose; web UI handles movement goals."""
import argparse
import math
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32
from geometry_msgs.msg import PoseWithCovarianceStamped


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('stop')
    pose = commands.add_parser('pose')
    for name in ['x', 'y', 'yaw_deg']:
        pose.add_argument(name, type=float)
    args = parser.parse_args()
    rclpy.init()
    node = Node('navigation_command')
    try:
        if args.command == 'stop':
            publisher = node.create_publisher(Int32, '/NAVIGATION_MODE', 10)
            message = Int32(data=0)
        else:
            if not all(math.isfinite(v) for v in [args.x, args.y, args.yaw_deg]):
                raise ValueError('Finite pose required')
            publisher = node.create_publisher(PoseWithCovarianceStamped, '/initialpose', 10)
            message = PoseWithCovarianceStamped()
            message.header.frame_id = 'map'
            message.pose.pose.position.x = args.x
            message.pose.pose.position.y = args.y
            angle = math.radians(args.yaw_deg)
            message.pose.pose.orientation.z = math.sin(angle/2)
            message.pose.pose.orientation.w = math.cos(angle/2)
            message.pose.covariance[0] = message.pose.covariance[7] = .25
            message.pose.covariance[35] = .0685
        deadline = time.monotonic()+8
        while not publisher.get_subscription_count() and time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.1)
        if not publisher.get_subscription_count():
            raise RuntimeError('Command subscriber not available')
        if args.command == 'pose':
            message.header.stamp = node.get_clock().now().to_msg()
        publisher.publish(message)
        deadline = time.monotonic()+.5
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.05)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

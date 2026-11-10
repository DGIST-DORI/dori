#!/usr/bin/env python3
"""Start Nav2 after localization supplies a fresh map-to-base transform."""
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.time import Time
from nav2_msgs.srv import ManageLifecycleNodes
from tf2_ros import Buffer, TransformException, TransformListener


class NavigationStartup(Node):
    def __init__(self):
        super().__init__("navigation_startup")
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.client = self.create_client(ManageLifecycleNodes,
                                         "/lifecycle_manager_navigation/manage_nodes")
        self.future = None
        self.requested_at = 0.0
        self.timer = self.create_timer(.5, self.tick)
        self.get_logger().info("Navigation waiting for initial pose (fresh map -> base_link TF)")

    def tick(self):
        if self.future is not None:
            if self.future.done():
                result = self.future.result()
                if result is None or not result.success:
                    raise RuntimeError("Nav2 lifecycle startup failed")
                self.get_logger().info("Navigation active")
                self.timer.cancel()
            elif time.monotonic() - self.requested_at > 120:
                raise RuntimeError("Nav2 lifecycle startup timed out; no repeated startup request sent")
            return
        try:
            transform = self.buffer.lookup_transform("map", "base_link", Time())
        except TransformException:
            return
        age = (self.get_clock().now().nanoseconds - Time.from_msg(transform.header.stamp).nanoseconds) / 1e9
        # AMCL permits future TF stamps for transform_tolerance (normally 1 s).
        if not -1.5 <= age <= 2.0 or not self.client.service_is_ready():
            return
        self.requested_at = time.monotonic()
        self.future = self.client.call_async(ManageLifecycleNodes.Request(command=ManageLifecycleNodes.Request.STARTUP))
        self.get_logger().info("Localization ready; starting navigation lifecycle nodes")


def main():
    rclpy.init()
    node = NavigationStartup()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RuntimeError:
        if rclpy.ok():
            raise
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()

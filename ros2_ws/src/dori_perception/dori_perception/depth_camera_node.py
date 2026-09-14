#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CameraInfo
from std_msgs.msg import Header
from cv_bridge import CvBridge
import numpy as np

try:
    import pyrealsense2 as rs
    REALSENSE_AVAILABLE = True
except ImportError:
    REALSENSE_AVAILABLE = False


class DepthCameraNode(Node):
    def __init__(self):
        super().__init__('depth_camera_node')

        # Parameters
        self.declare_parameter('width', 640)
        self.declare_parameter('height', 480)
        self.declare_parameter('fps', 30)
        self.declare_parameter('enable_depth', True)
        self.declare_parameter('enable_color', True)
        self.declare_parameter('align_depth_to_color', True)
        self.declare_parameter('depth_scale_publish', True)
        self.declare_parameter('topics.color_pub', 'color/image_raw')
        self.declare_parameter('topics.depth_pub', 'depth/image_raw')
        self.declare_parameter('topics.depth_colormap_pub', 'depth/image_colormap')
        self.declare_parameter('topics.color_info_pub', 'color/camera_info')
        self.declare_parameter('topics.depth_info_pub', 'depth/camera_info')

        self.width = self.get_parameter('width').value
        self.height = self.get_parameter('height').value
        self.fps = self.get_parameter('fps').value
        self.enable_depth = self.get_parameter('enable_depth').value
        self.enable_color = self.get_parameter('enable_color').value
        self.align_to_color = self.get_parameter('align_depth_to_color').value

        if not REALSENSE_AVAILABLE:
            self.get_logger().error('pyrealsense2 has not been found. Please install the Intel RealSense SDK and pyrealsense2 Python bindings. pip install pyrealsense2')
            return

        # Initialize RealSense pipeline
        self.pipeline = rs.pipeline()
        config = rs.config()

        if self.enable_color:
            config.enable_stream(rs.stream.color, self.width, self.height, rs.format.bgr8, self.fps)
        if self.enable_depth:
            config.enable_stream(rs.stream.depth, self.width, self.height, rs.format.z16, self.fps)

        try:
            profile = self.pipeline.start(config)
        except Exception as e:
            self.get_logger().error(f'Failed to start RealSense pipeline: {e}')
            return

        # Align depth to color if enabled
        self.align = rs.align(rs.stream.color) if self.align_to_color else None

        # depth scale (unit: meter / count)
        depth_sensor = profile.get_device().first_depth_sensor()
        self.depth_scale = depth_sensor.get_depth_scale()
        self.get_logger().info(f'Depth scale: {self.depth_scale:.6f} m/unit')

        # CvBridge
        self.bridge = CvBridge()

        color_topic = self.get_parameter('topics.color_pub').value
        depth_topic = self.get_parameter('topics.depth_pub').value
        depth_colormap_topic = self.get_parameter('topics.depth_colormap_pub').value
        color_info_topic = self.get_parameter('topics.color_info_pub').value
        depth_info_topic = self.get_parameter('topics.depth_info_pub').value

        # Publishers
        self.color_pub = self.create_publisher(Image, color_topic, 10)
        self.depth_pub = self.create_publisher(Image, depth_topic, 10)
        self.depth_colormap_pub = self.create_publisher(Image, depth_colormap_topic, 10)
        self.color_info_pub = self.create_publisher(CameraInfo, color_info_topic, 10)
        self.depth_info_pub = self.create_publisher(CameraInfo, depth_info_topic, 10)

        # Cache for intrinsics (to avoid repeated conversion)
        self._color_intrinsics = None
        self._depth_intrinsics = None
        self._profile = profile

        # main loop timer
        timer_period = 1.0 / self.fps
        self.timer = self.create_timer(timer_period, self.timer_callback)

        self.get_logger().info(
            f'Depth Camera Node started: {self.width}x{self.height} @ {self.fps}fps, '
            f'align={self.align_to_color}'
        )

    def timer_callback(self):
        try:
            frames = self.pipeline.wait_for_frames(timeout_ms=100)
        except Exception:
            self.get_logger().warn('RealSense frame acquisition timeout')
            return

        # Align depth to color if enabled
        if self.align is not None:
            frames = self.align.process(frames)

        now = self.get_clock().now().to_msg()

        # Color image publish
        if self.enable_color:
            color_frame = frames.get_color_frame()
            if color_frame:
                color_image = np.asanyarray(color_frame.get_data())  # (H, W, 3) BGR

                color_msg = self.bridge.cv2_to_imgmsg(color_image, encoding='bgr8')
                color_msg.header = Header(stamp=now, frame_id='camera_color_optical_frame')
                self.color_pub.publish(color_msg)

                # CameraInfo
                if self._color_intrinsics is None:
                    self._color_intrinsics = color_frame.profile.as_video_stream_profile().intrinsics
                self.color_info_pub.publish(
                    self._build_camera_info(self._color_intrinsics, now, 'camera_color_optical_frame')
                )

        # Depth image publish
        if self.enable_depth:
            depth_frame = frames.get_depth_frame()
            if depth_frame:
                depth_image = np.asanyarray(depth_frame.get_data())  # (H, W) uint16, unit = depth_scale m

                # raw depth (uint16, depth_scale meter)
                depth_msg = self.bridge.cv2_to_imgmsg(depth_image, encoding='16UC1')
                depth_msg.header = Header(stamp=now, frame_id='camera_depth_optical_frame')
                self.depth_pub.publish(depth_msg)

                # colormap (for visualization)
                import cv2
                depth_colormap = cv2.applyColorMap(
                    cv2.convertScaleAbs(depth_image, alpha=0.03),
                    cv2.COLORMAP_JET
                )
                colormap_msg = self.bridge.cv2_to_imgmsg(depth_colormap, encoding='bgr8')
                colormap_msg.header = Header(stamp=now, frame_id='camera_depth_optical_frame')
                self.depth_colormap_pub.publish(colormap_msg)

                if self._depth_intrinsics is None:
                    self._depth_intrinsics = depth_frame.profile.as_video_stream_profile().intrinsics
                self.depth_info_pub.publish(
                    self._build_camera_info(self._depth_intrinsics, now, 'camera_depth_optical_frame')
                )

    def _build_camera_info(self, intrinsics, stamp, frame_id: str) -> CameraInfo:
        """RealSense intrinsics -> ROS2 CameraInfo conversion"""
        info = CameraInfo()
        info.header = Header(stamp=stamp, frame_id=frame_id)
        info.width = intrinsics.width
        info.height = intrinsics.height
        info.distortion_model = 'plumb_bob'

        # D: distortion coefficients [k1, k2, p1, p2, k3]
        info.d = list(intrinsics.coeffs)

        # K: camera matrix (row-major, 3x3)
        fx, fy = intrinsics.fx, intrinsics.fy
        cx, cy = intrinsics.ppx, intrinsics.ppy
        info.k = [fx, 0.0, cx,
                  0.0, fy, cy,
                  0.0, 0.0, 1.0]

        # R: rectification matrix (identity for monocular)
        info.r = [1.0, 0.0, 0.0,
                  0.0, 1.0, 0.0,
                  0.0, 0.0, 1.0]

        # P: projection matrix (3x4)
        info.p = [fx, 0.0, cx, 0.0,
                  0.0, fy, cy, 0.0,
                  0.0, 0.0, 1.0, 0.0]
        return info

    def destroy_node(self):
        try:
            self.pipeline.stop()
            self.get_logger().info('RealSense pipeline stopped')
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = DepthCameraNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

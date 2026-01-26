#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
import cv2


class CameraNode(Node):
    def __init__(self):
        super().__init__('camera_node')
        
        # Parameters
        self.declare_parameter('camera_index', 0)
        self.declare_parameter('frame_width', 1280)
        self.declare_parameter('frame_height', 720)
        self.declare_parameter('fps', 30)
        self.declare_parameter('publish_rate', 30.0)
        
        # 
        camera_idx = self.get_parameter('camera_index').value
        width = self.get_parameter('frame_width').value
        height = self.get_parameter('frame_height').value
        fps = self.get_parameter('fps').value
        
        # Initialize camera
        self.cap = cv2.VideoCapture(camera_idx)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        
        # disable autofocus for consistent image quality
        self.cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
        
        if not self.cap.isOpened():
            self.get_logger().error('카메라를 열 수 없습니다!')
            return
        
        # Log actual camera settings
        actual_width = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        actual_height = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        actual_fps = self.cap.get(cv2.CAP_PROP_FPS)
        
        self.get_logger().info(f'카메라 초기화 완료: {actual_width}x{actual_height} @ {actual_fps}fps')
        
        # Publisher setup
        self.image_pub = self.create_publisher(Image, '/cube/camera/image_raw', 10)
        
        # CvBridge initialization
        self.bridge = CvBridge()
        
        # timer setup
        publish_rate = self.get_parameter('publish_rate').value
        timer_period = 1.0 / publish_rate
        self.timer = self.create_timer(timer_period, self.timer_callback)
        
        self.get_logger().info('Camera Node 시작됨')
    
    def timer_callback(self):
        ret, frame = self.cap.read()
        
        if ret:
            try:
                # OpenCV image to ROS Image Message
                ros_image = self.bridge.cv2_to_imgmsg(frame, encoding='bgr8')
                ros_image.header.stamp = self.get_clock().now().to_msg()
                ros_image.header.frame_id = 'camera_link'
                
                # Publish the image
                self.image_pub.publish(ros_image)
                
            except Exception as e:
                self.get_logger().error(f'이미지 변환 실패: {str(e)}')
        else:
            self.get_logger().warn('프레임 읽기 실패')
    
    def destroy_node(self):
        if self.cap.isOpened():
            self.cap.release()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    
    camera_node = CameraNode()
    
    try:
        rclpy.spin(camera_node)
    except KeyboardInterrupt:
        pass
    finally:
        camera_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

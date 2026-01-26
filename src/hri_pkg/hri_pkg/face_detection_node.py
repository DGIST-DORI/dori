#!/usr/bin/env python3
"""
Face detection and tracking using MediaPipe
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from geometry_msgs.msg import Point
from std_msgs.msg import Bool
from cv_bridge import CvBridge
import cv2
import mediapipe as mp


class FaceDetectionNode(Node):
    def __init__(self):
        super().__init__('face_detection_node')
        
        # 
        self.declare_parameter('min_detection_confidence', 0.5)
        self.declare_parameter('visualize', True)
        
        # MediaPipe Face Detection initialization
        self.mp_face_detection = mp.solutions.face_detection
        self.mp_drawing = mp.solutions.drawing_utils
        
        min_confidence = self.get_parameter('min_detection_confidence').value
        self.face_detection = self.mp_face_detection.FaceDetection(
            min_detection_confidence=min_confidence
        )
        
        self.visualize = self.get_parameter('visualize').value
        
        # CvBridge initialization
        self.bridge = CvBridge()
        
        # Subscriber: camera images
        self.image_sub = self.create_subscription(
            Image,
            '/cube/camera/image_raw',
            self.image_callback,
            10
        )
        
        # Publishers
        self.face_detected_pub = self.create_publisher(Bool, '/cube/hri/face_detected', 10)
        self.face_position_pub = self.create_publisher(Point, '/cube/hri/face_position', 10)
        
        if self.visualize:
            self.annotated_image_pub = self.create_publisher(
                Image, 
                '/cube/hri/annotated_image', 
                10
            )
        
        self.get_logger().info('Face Detection Node 시작됨')
    
    def image_callback(self, msg):
        """카메라 이미지를 받아 얼굴 감지 수행"""
        try:
            # ROS Image to OpenCV image
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            
            # BGR to RGB conversion
            rgb_image = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
            
            # detect faces
            results = self.face_detection.process(rgb_image)
            
            # Publish face detected status
            face_detected = Bool()
            face_detected.data = results.detections is not None
            self.face_detected_pub.publish(face_detected)
            
            # Calculate face position and Publish
            if results.detections:
                # select the largest face
                largest_face = max(
                    results.detections, 
                    key=lambda d: self._get_bbox_area(d.location_data.relative_bounding_box)
                )
                
                bbox = largest_face.location_data.relative_bounding_box
                
                # calculate center of the bounding box
                center_x = bbox.xmin + bbox.width / 2
                center_y = bbox.ymin + bbox.height / 2
                
                # calculate offset from image center (-0.5 ~ 0.5)
                offset_x = center_x - 0.5
                offset_y = center_y - 0.5
                
                # Publish as Point message
                face_pos = Point()
                face_pos.x = offset_x
                face_pos.y = offset_y
                face_pos.z = bbox.width * bbox.height  # face size for distance estimation
                
                self.face_position_pub.publish(face_pos)
                
                self.get_logger().debug(
                    f'얼굴 감지: 위치=({offset_x:.2f}, {offset_y:.2f}), 크기={face_pos.z:.3f}'
                )
            
            # visualization
            if self.visualize:
                annotated_image = cv_image.copy()
                
                if results.detections:
                    for detection in results.detections:
                        self.mp_drawing.draw_detection(annotated_image, detection)
                
                # Publish annotated image
                annotated_msg = self.bridge.cv2_to_imgmsg(annotated_image, encoding='bgr8')
                annotated_msg.header = msg.header
                self.annotated_image_pub.publish(annotated_msg)
                
        except Exception as e:
            self.get_logger().error(f'이미지 처리 실패: {str(e)}')
    
    def _get_bbox_area(self, bbox):
        return bbox.width * bbox.height
    
    def destroy_node(self):
        self.face_detection.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    
    face_detection_node = FaceDetectionNode()
    
    try:
        rclpy.spin(face_detection_node)
    except KeyboardInterrupt:
        pass
    finally:
        face_detection_node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

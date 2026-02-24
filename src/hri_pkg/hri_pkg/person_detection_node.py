#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from geometry_msgs.msg import Point, PointStamped
from std_msgs.msg import Bool, Float32
from cv_bridge import CvBridge
import cv2
import numpy as np

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


from std_msgs.msg import String
import json


class PersonDetectionNode(Node):
    def __init__(self):
        super().__init__('person_detection_node')

        # Parameters
        self.declare_parameter('model_path', 'yolov8n.pt')       # n/s/m/l/x
        self.declare_parameter('confidence_threshold', 0.5)
        self.declare_parameter('device', 'cuda')                  # 'cuda' or 'cpu'
        self.declare_parameter('visualize', True)
        self.declare_parameter('interaction_distance_m', 2.0)
        self.declare_parameter('use_depth', True)                 # RealSense depth

        model_path = self.get_parameter('model_path').value
        self.conf_thresh = self.get_parameter('confidence_threshold').value
        device = self.get_parameter('device').value
        self.visualize = self.get_parameter('visualize').value
        self.interaction_dist = self.get_parameter('interaction_distance_m').value
        self.use_depth = self.get_parameter('use_depth').value

        if not YOLO_AVAILABLE:
            self.get_logger().error('ultralytics has not been found. Please install with pip install ultralytics.')
            return

        # Load YOLOv8 model
        try:
            self.model = YOLO(model_path)
            self.model.to(device)
            self.get_logger().info(f'YOLOv8 model loaded successfully: {model_path} on {device}')
        except Exception as e:
            self.get_logger().error(f'Failed to load YOLOv8 model: {e}')
            return

        # COCO class index for 'person' = 0
        self.PERSON_CLASS_ID = 0

        # CvBridge
        self.bridge = CvBridge()

        # Cache for latest depth image
        self._latest_depth: np.ndarray | None = None
        self._depth_scale: float = 0.001  # Initial default, will be updated from RealSenseNode if available

        # Subscribers
        self.image_sub = self.create_subscription(
            Image,
            '/dori/camera/color/image_raw',   # RealSense color topic
            self.image_callback,
            10
        )
        if self.use_depth:
            self.depth_sub = self.create_subscription(
                Image,
                '/dori/camera/depth/image_raw',
                self.depth_callback,
                10
            )
            self.depth_scale_sub = self.create_subscription(
                Float32,
                '/dori/camera/depth_scale',
                lambda msg: setattr(self, '_depth_scale', msg.data),
                10
            )

        # Publishers
        self.person_detected_pub = self.create_publisher(Bool, '/dori/hri/face_detected', 10)
        self.person_position_pub = self.create_publisher(Point, '/dori/hri/face_position', 10)

        # Additional publishers for detailed info and HRI trigger
        self.persons_detail_pub = self.create_publisher(String, '/dori/hri/persons', 10)
        self.hri_trigger_pub = self.create_publisher(Bool, '/dori/hri/interaction_trigger', 10)

        if self.visualize:
            self.annotated_pub = self.create_publisher(Image, '/dori/hri/annotated_image', 10)

        self.get_logger().info('Person Detection Node started (YOLOv8)')

    def depth_callback(self, msg: Image):
        try:
            self._latest_depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding='16UC1')
        except Exception as e:
            self.get_logger().error(f'Failed to convert depth image: {e}')

    def image_callback(self, msg: Image):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f'Failed to convert color image: {e}')
            return

        h, w = cv_image.shape[:2]

        # YOLOv8 inference
        results = self.model(cv_image, conf=self.conf_thresh, classes=[self.PERSON_CLASS_ID], verbose=False)

        detections = []
        closest_person = None
        min_distance = float('inf')

        for result in results:
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                conf = float(box.conf[0])

                # normalized center and area for ROS message
                cx_norm = ((x1 + x2) / 2) / w
                cy_norm = ((y1 + y2) / 2) / h
                bbox_area = ((x2 - x1) * (y2 - y1)) / (w * h)

                # estimate distance using depth if available
                distance_m = self._estimate_distance(x1, y1, x2, y2)

                det = {
                    'bbox': [x1, y1, x2, y2],
                    'confidence': round(conf, 3),
                    'center_norm': [round(cx_norm, 3), round(cy_norm, 3)],
                    'bbox_area_norm': round(bbox_area, 4),
                    'distance_m': round(distance_m, 3) if distance_m is not None else None,
                }
                detections.append(det)

                # estimate closest person based on distance (or fallback to bbox area if distance is not available)
                d = distance_m if distance_m is not None else (1.0 / (bbox_area + 1e-6))
                if d < min_distance:
                    min_distance = d
                    closest_person = det

        # face_detected (Bool)
        detected_msg = Bool()
        detected_msg.data = len(detections) > 0
        self.person_detected_pub.publish(detected_msg)

        # face_position (Point): Closest person's normalized center offset and distance
        if closest_person:
            pos = Point()
            pos.x = closest_person['center_norm'][0] - 0.5   # -0.5 ~ 0.5
            pos.y = closest_person['center_norm'][1] - 0.5
            pos.z = closest_person['distance_m'] if closest_person['distance_m'] else \
                    closest_person['bbox_area_norm']
            self.person_position_pub.publish(pos)

            self.get_logger().debug(
                f'person detected: pos=({pos.x:.2f}, {pos.y:.2f}), '
                f'dist={closest_person["distance_m"]}m, conf={closest_person["confidence"]}'
            )

        # persons detail (JSON String)
        detail_msg = String()
        detail_msg.data = json.dumps({
            'count': len(detections),
            'detections': detections
        })
        self.persons_detail_pub.publish(detail_msg)

        # HRI trigger (Bool): True if closest person is within interaction distance
        trigger = Bool()
        if closest_person and closest_person['distance_m'] is not None:
            trigger.data = closest_person['distance_m'] < self.interaction_dist
        else:
            trigger.data = False
        self.hri_trigger_pub.publish(trigger)

        # visualization
        if self.visualize:
            annotated = cv_image.copy()
            for det in detections:
                x1, y1, x2, y2 = det['bbox']
                dist_str = f"{det['distance_m']:.2f}m" if det['distance_m'] else 'N/A'
                color = (0, 255, 0) if (det['distance_m'] and det['distance_m'] < self.interaction_dist) \
                        else (255, 200, 0)
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
                label = f"person {det['confidence']:.2f} {dist_str}"
                cv2.putText(annotated, label, (x1, y1 - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

            ann_msg = self.bridge.cv2_to_imgmsg(annotated, encoding='bgr8')
            ann_msg.header = msg.header
            self.annotated_pub.publish(ann_msg)

    # Depth-based distance estimation
    def _estimate_distance(self, x1: int, y1: int, x2: int, y2: int) -> float | None:
        if self._latest_depth is None or not self.use_depth:
            return None

        # using a small region around the center of the bounding box to get a more robust depth estimate
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        margin_x = max(1, (x2 - x1) // 6)
        margin_y = max(1, (y2 - y1) // 6)

        roi = self._latest_depth[
            max(0, cy - margin_y): min(self._latest_depth.shape[0], cy + margin_y),
            max(0, cx - margin_x): min(self._latest_depth.shape[1], cx + margin_x)
        ]

        valid = roi[roi > 0]
        if valid.size == 0:
            return None

        median_depth = float(np.median(valid))
        return median_depth * self._depth_scale

    def destroy_node(self):
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = PersonDetectionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

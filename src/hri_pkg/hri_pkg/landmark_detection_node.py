#!/usr/bin/env python3

import json
import math
from pathlib import Path

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False


COCO_LANDMARK_CLASSES: dict[str, str] = {
    'couch':  'furniture',
    'chair':  'furniture',
    'tv':     'furniture',
    'clock':  'signage',
}


class LandmarkDetectionNode(Node):
    def __init__(self):
        super().__init__('landmark_detection_node')

        # Parameters
        self.declare_parameter('model_path', 'yolov8n.pt')
        self.declare_parameter('custom_model_path', '')          # TODO: if custom_model_path is set, use it instead of model_path
        self.declare_parameter('confidence_threshold', 0.45)
        self.declare_parameter('device', 'cuda')
        self.declare_parameter('visualize', True)
        self.declare_parameter('landmark_db_path', 'landmark_db.json')
        self.declare_parameter('max_detection_distance_m', 8.0)  # max distance to consider a detection valid for localization
        self.declare_parameter('localization_confidence_threshold', 0.6)

        model_path = self.get_parameter('model_path').value
        custom_model_path = self.get_parameter('custom_model_path').value
        self.conf_thresh = self.get_parameter('confidence_threshold').value
        device = self.get_parameter('device').value
        self.visualize = self.get_parameter('visualize').value
        db_path = self.get_parameter('landmark_db_path').value
        self.max_dist = self.get_parameter('max_detection_distance_m').value
        self.loc_conf_thresh = self.get_parameter('localization_confidence_threshold').value

        if not YOLO_AVAILABLE:
            self.get_logger().error('ultralytics not found. Please install with pip install ultralytics')
            return

        # load model
        # if custom_model_path is provided, use it; otherwise fall back to model_path
        active_model_path = custom_model_path if custom_model_path else model_path
        try:
            self.model = YOLO(active_model_path)
            self.model.to(device)
            self.using_custom_model = bool(custom_model_path)
            self.get_logger().info(
                f'Load model: {active_model_path} '
                f'({"Custom" if self.using_custom_model else "COCO"})'
            )
        except Exception as e:
            self.get_logger().error(f'Failed to load model: {e}')
            return

        # load landmark DB
        self.landmark_db: dict = {}           # id -> landmark info
        self.label_to_landmark_ids: dict[str, list[str]] = {}  # detection_label -> [landmark_id, ...]
        self._load_landmark_db(db_path)

        # set of all class names that can be detected (either from custom model or COCO + DB)
        # if using custom model, only classes in the model are considered; if using COCO, all COCO classes + coco_classes referenced in the DB are considered
        self.target_class_names: set[str] = set()
        if self.using_custom_model:
            self.target_class_names = set(self.label_to_landmark_ids.keys())
        else:
            self.target_class_names = set(COCO_LANDMARK_CLASSES.keys())
            for lm in self.landmark_db.values():
                if lm.get('type') == 'coco_class' and lm.get('enabled', False):
                    for label in lm.get('detection_labels', []):
                        self.target_class_names.add(label)

        self.get_logger().info(f'Target detection classes: {self.target_class_names}')

        # CvBridge
        self.bridge = CvBridge()
        self._latest_depth: np.ndarray | None = None
        self._depth_scale: float = 0.001
        self._camera_intrinsics: dict | None = None  # fx, fy, cx, cy

        # Subscribers
        self.image_sub = self.create_subscription(
            Image, '/dori/camera/color/image_raw', self.image_callback, 10
        )
        self.depth_sub = self.create_subscription(
            Image, '/dori/camera/depth/image_raw', self.depth_callback, 10
        )
        # internal topic for camera intrinsics (published by camera node or DepthCamera node)
        from sensor_msgs.msg import CameraInfo
        self.camera_info_sub = self.create_subscription(
            CameraInfo, '/dori/camera/color/camera_info', self.camera_info_callback, 10
        )

        # Publishers
        self.detections_pub = self.create_publisher(String, '/dori/landmark/detections', 10)
        self.localization_pub = self.create_publisher(String, '/dori/landmark/localization', 10)
        self.context_pub = self.create_publisher(String, '/dori/landmark/context', 10)

        if self.visualize:
            self.annotated_pub = self.create_publisher(
                Image, '/dori/hri/annotated_landmark', 10
            )

        self.get_logger().info('Landmark Detection Node started')

    # Load landmark database from JSON file
    def _load_landmark_db(self, db_path: str):
        path = Path(db_path)
        if not path.exists():
            self.get_logger().warn(f'There is no landmark_db.json: {db_path} — using only COCO classes without localization')
            return

        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        for lm in data.get('landmarks', []):
            if not lm.get('enabled', True):
                continue
            lm_id = lm['id']
            self.landmark_db[lm_id] = lm
            for label in lm.get('detection_labels', []):
                self.label_to_landmark_ids.setdefault(label, []).append(lm_id)

        self.get_logger().info(f'Loaded landmark DB: {len(self.landmark_db)} landmarks enabled')

    # Callbacks
    def depth_callback(self, msg: Image):
        try:
            self._latest_depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding='16UC1')
        except Exception as e:
            self.get_logger().error(f'Depth image conversion failed: {e}')

    def camera_info_callback(self, msg):
        if self._camera_intrinsics is None:
            self._camera_intrinsics = {
                'fx': msg.k[0], 'fy': msg.k[4],
                'cx': msg.k[2], 'cy': msg.k[5],
                'width': msg.width, 'height': msg.height,
            }
            self.get_logger().info('Camera intrinsics received')

    def image_callback(self, msg: Image):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f'Color image conversion failed: {e}')
            return

        h, w = cv_image.shape[:2]

        # YOLO inference
        results = self.model(cv_image, conf=self.conf_thresh, verbose=False)

        raw_detections = []   # everything detected by the model before DB matching
        matched_landmarks = []  # landmarks matched with the DB (for localization and LLM context)

        for result in results:
            for box in result.boxes:
                class_name = result.names[int(box.cls[0])]

                if class_name not in self.target_class_names:
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                conf = float(box.conf[0])

                # estimate distance using depth
                distance_m = self._estimate_distance(x1, y1, x2, y2)

                if distance_m is not None and distance_m > self.max_dist:
                    continue

                # Vector from camera to landmark (for localization)
                direction = self._pixel_to_direction(
                    (x1 + x2) / 2, (y1 + y2) / 2, w, h
                )

                det = {
                    'class_name': class_name,
                    'confidence': round(conf, 3),
                    'bbox': [x1, y1, x2, y2],
                    'distance_m': round(distance_m, 3) if distance_m else None,
                    'direction': direction,
                }
                raw_detections.append(det)

                # Match with landmark DB
                lm_ids = self.label_to_landmark_ids.get(class_name, [])
                if lm_ids:
                    for lm_id in lm_ids:
                        lm_info = self.landmark_db[lm_id]
                        matched_landmarks.append({
                            **det,
                            'landmark_id': lm_id,
                            'display_name': lm_info['display_name'],
                            'map_position': lm_info['map_position'],
                            'building': lm_info.get('building', ''),
                            'floor': lm_info.get('floor', ''),
                            'description': lm_info.get('description', ''),
                        })
                else:
                    matched_landmarks.append({
                        **det,
                        'landmark_id': f'coco_{class_name}',
                        'display_name': class_name,
                        'map_position': None,
                        'building': '',
                        'floor': '',
                        'description': '',
                    })

        # Publish
        now = self.get_clock().now().to_msg()
        self._publish_detections(matched_landmarks, now)
        self._publish_localization_candidates(matched_landmarks, now)
        self._publish_llm_context(matched_landmarks)

        # visualization
        if self.visualize:
            self._publish_annotated(cv_image, matched_landmarks, msg)

    # Pulish helper methods
    def _publish_detections(self, landmarks: list, now):
        payload = {
            'stamp': {'sec': now.sec, 'nanosec': now.nanosec},
            'count': len(landmarks),
            'landmarks': landmarks,
        }
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.detections_pub.publish(msg)

    def _publish_localization_candidates(self, landmarks: list, now):
        """
        {
          "candidates": [
            {
              "landmark_id": "e4_lobby_sofa_blue",
              "map_position": {x, y, z},       // 맵상 랜드마크 절대 좌표
              "observed_distance_m": 1.5,       // 카메라로부터의 거리
              "observed_direction": {x, y},     // 정규화된 방향벡터 (픽셀 기준)
              "confidence": 0.82
            }, ...
          ]
        }
        SLAM에서 이 정보 + 현재 추정 pose를 이용해 위치 보정
        """
        candidates = [
            {
                'landmark_id': lm['landmark_id'],
                'display_name': lm['display_name'],
                'map_position': lm['map_position'],
                'observed_distance_m': lm['distance_m'],
                'observed_direction': lm['direction'],
                'confidence': lm['confidence'],
            }
            for lm in landmarks
            if lm.get('map_position') is not None
            and lm['confidence'] >= self.loc_conf_thresh
        ]

        if candidates:
            msg = String()
            msg.data = json.dumps({
                'stamp': {'sec': now.sec, 'nanosec': now.nanosec},
                'candidates': candidates,
            }, ensure_ascii=False)
            self.localization_pub.publish(msg)
            self.get_logger().debug(f'Localization candidates {len(candidates)} published')

    def _publish_llm_context(self, landmarks: list):
        if not landmarks:
            return

        parts = []
        seen_buildings: set[str] = set()

        for lm in landmarks:
            if lm['building']:
                seen_buildings.add(f"{lm['building']} {lm['floor']} floor")

            dist_str = f"{lm['distance_m']:.1f}m ahead" if lm['distance_m'] else 'nearby'
            parts.append(f"{lm['display_name']}({dist_str})")

        location_str = ', '.join(seen_buildings) if seen_buildings else 'unknown location'
        objects_str = ', '.join(parts)

        context = f"current loc: {location_str}. detected landmarks: {objects_str}."

        msg = String()
        msg.data = context
        self.context_pub.publish(msg)
        self.get_logger().debug(f'LLM context: {context}')

    # Utilities
    def _estimate_distance(self, x1: int, y1: int, x2: int, y2: int) -> float | None:
        if self._latest_depth is None:
            return None

        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        mx = max(1, (x2 - x1) // 6)
        my = max(1, (y2 - y1) // 6)

        roi = self._latest_depth[
            max(0, cy - my): min(self._latest_depth.shape[0], cy + my),
            max(0, cx - mx): min(self._latest_depth.shape[1], cx + mx),
        ]
        valid = roi[roi > 0]
        if valid.size == 0:
            return None
        return float(np.median(valid)) * self._depth_scale

    def _pixel_to_direction(self, px: float, py: float, w: int, h: int) -> dict:
        if self._camera_intrinsics:
            fx = self._camera_intrinsics['fx']
            fy = self._camera_intrinsics['fy']
            cx = self._camera_intrinsics['cx']
            cy = self._camera_intrinsics['cy']
            dx = (px - cx) / fx
            dy = (py - cy) / fy
        else:
            dx = (px / w) - 0.5
            dy = (py / h) - 0.5

        norm = math.sqrt(dx * dx + dy * dy + 1.0)
        return {
            'x': round(dx / norm, 4),
            'y': round(dy / norm, 4),
            'z': round(1.0 / norm, 4),
        }

    def _publish_annotated(self, image: np.ndarray, landmarks: list, original_msg):
        annotated = image.copy()

        TYPE_COLORS = {
            'furniture': (0, 200, 255),   # Yellow
            'signage':   (255, 100, 0),   # Blue
            'entrance':  (0, 255, 100),   # Green
            'default':   (200, 200, 200),
        }

        for lm in landmarks:
            x1, y1, x2, y2 = lm['bbox']
            lm_type = COCO_LANDMARK_CLASSES.get(lm['class_name'], 'default')
            color = TYPE_COLORS.get(lm_type, TYPE_COLORS['default'])

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

            dist_str = f" {lm['distance_m']:.1f}m" if lm['distance_m'] else ''
            label = f"[LM] {lm['display_name']}{dist_str} ({lm['confidence']:.2f})"
            (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.45, 1)
            cv2.rectangle(annotated, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
            cv2.putText(annotated, label, (x1 + 2, y1 - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)

        ann_msg = self.bridge.cv2_to_imgmsg(annotated, encoding='bgr8')
        ann_msg.header = original_msg.header
        self.annotated_pub.publish(ann_msg)


def main(args=None):
    rclpy.init(args=args)
    node = LandmarkDetectionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

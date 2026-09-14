#!/usr/bin/env python3

import json
import time

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from geometry_msgs.msg import Point
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, Float32, String
from std_srvs.srv import SetBool

try:
    from ultralytics import YOLO
    YOLO_AVAILABLE = True
except ImportError:
    YOLO_AVAILABLE = False

class TrackingState:
    IDLE      = 'idle'
    TRACKING  = 'tracking'
    LOST      = 'lost'


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
        self.declare_parameter('tracker_config', 'bytetrack.yaml')
        self.declare_parameter('lost_timeout_sec', 5.0)
        self.declare_parameter('follow_distance_m', 1.2)
        self.declare_parameter('reacquire_iou_thresh', 0.3)
        self.declare_parameter('topics.color_image_sub', 'camera/front/color/image_raw')
        self.declare_parameter('topics.depth_image_sub', 'camera/front/depth/image_raw')
        self.declare_parameter('topics.depth_scale_sub', 'camera/front/depth/scale')
        self.declare_parameter('services.follow_mode_service', 'hri/set_follow_mode')
        self.declare_parameter('topics.persons_pub', 'hri/persons')
        self.declare_parameter('topics.interaction_trigger_pub', 'hri/interaction_trigger')
        self.declare_parameter('topics.tracking_state_pub', 'hri/tracking_state')
        self.declare_parameter('topics.follow_offset_pub', 'follow/target_offset')
        self.declare_parameter('topics.annotated_pub', 'hri/annotated_image')

        model_path            = self.get_parameter('model_path').value
        self.conf_thresh      = self.get_parameter('confidence_threshold').value
        device                = self.get_parameter('device').value
        self.visualize        = self.get_parameter('visualize').value
        self.interaction_dist = self.get_parameter('interaction_distance_m').value
        self.use_depth        = self.get_parameter('use_depth').value
        self.tracker_config   = self.get_parameter('tracker_config').value
        self.lost_timeout     = self.get_parameter('lost_timeout_sec').value
        self.follow_dist      = self.get_parameter('follow_distance_m').value
        self.reacquire_iou    = self.get_parameter('reacquire_iou_thresh').value

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

        # State Variations
        self.target_id: int | None       = None
        self.tracking_state: str         = TrackingState.IDLE
        self.lost_since: float | None    = None
        self.last_target_bbox: list | None = None
        self.last_target_dist: float | None = None
        self._pending_register: bool     = False 

        # CvBridge
        self.bridge = CvBridge()

        # Cache for latest depth image
        self._latest_depth: np.ndarray | None = None
        self._depth_scale: float = 0.001  # Initial default, will be updated from RealSenseNode if available

        color_image_topic = self.get_parameter('topics.color_image_sub').value
        depth_image_topic = self.get_parameter('topics.depth_image_sub').value
        depth_scale_topic = self.get_parameter('topics.depth_scale_sub').value
        follow_mode_service = self.get_parameter('services.follow_mode_service').value
        persons_topic = self.get_parameter('topics.persons_pub').value
        interaction_trigger_topic = self.get_parameter('topics.interaction_trigger_pub').value
        tracking_state_topic = self.get_parameter('topics.tracking_state_pub').value
        follow_offset_topic = self.get_parameter('topics.follow_offset_pub').value
        annotated_topic = self.get_parameter('topics.annotated_pub').value

        # Subscribers
        self.create_subscription(
            Image, color_image_topic, self.image_callback, 10)
        if self.use_depth:
            self.create_subscription(
                Image, depth_image_topic, self.depth_callback, 10)
            self.create_subscription(
                Float32, depth_scale_topic,
                lambda msg: setattr(self, '_depth_scale', msg.data), 10)
        self.create_service(
            SetBool, follow_mode_service, self._follow_mode_service_callback)

        # Publishers
        self.persons_detail_pub = self.create_publisher(String, persons_topic, 10)
        self.hri_trigger_pub = self.create_publisher(Bool, interaction_trigger_topic, 10)
        self.tracking_state_pub = self.create_publisher(String, tracking_state_topic, 10)
        self.follow_offset_pub = self.create_publisher(Point, follow_offset_topic, 10)
        if self.visualize:
            self.annotated_pub = self.create_publisher(Image, annotated_topic, 10)

        self.get_logger().info('Person Detection Node started (YOLOv8)')

    def depth_callback(self, msg: Image):
        try:
            self._latest_depth = self.bridge.imgmsg_to_cv2(msg, desired_encoding='16UC1')
        except Exception as e:
            self.get_logger().error(f'Failed to convert depth image: {e}')

    def _follow_mode_service_callback(self, request: SetBool.Request, response: SetBool.Response):
        if request.data:
            self._pending_register = True
            response.success = True
            response.message = 'Follow mode enable accepted (target will be registered on next frame)'
            self.get_logger().info('Follow mode service request ON — register target in next frame')
        else:
            self._release_target('Unfollow by external command')
            response.success = True
            response.message = 'Follow mode disabled and target released'

        return response

    def image_callback(self, msg: Image):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f'Failed to convert color image: {e}')
            return

        h, w = cv_image.shape[:2]

        # YOLOv8 inference
        results = self.model.track(
            cv_image,
            conf=self.conf_thresh,
            classes=[self.PERSON_CLASS_ID],
            tracker=self.tracker_config,
            persist=True,
            verbose=False,
        )

        detections: list[dict] = []
        target_det: dict | None = None
        closest_person: dict | None = None
        min_dist = float('inf')

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                conf     = float(box.conf[0])
                track_id = int(box.id[0]) if box.id is not None else -1

                cx_norm   = ((x1 + x2) / 2) / w
                cy_norm   = ((y1 + y2) / 2) / h
                bbox_area = ((x2 - x1) * (y2 - y1)) / (w * h)
                dist_m    = self._estimate_distance(x1, y1, x2, y2)

                det = {
                    'track_id':       track_id,
                    'bbox':           [x1, y1, x2, y2],
                    'confidence':     round(conf, 3),
                    'center_norm':    [round(cx_norm, 3), round(cy_norm, 3)],
                    'bbox_area_norm': round(bbox_area, 4),
                    'distance_m':     round(dist_m, 3) if dist_m is not None else None,
                }
                detections.append(det)

                if self.target_id is not None and track_id == self.target_id:
                    target_det = det

                d = dist_m if dist_m is not None else (1.0 / (bbox_area + 1e-6))
                if d < min_dist:
                    min_dist = d
                    closest_person = det
        
        # target 등록 로직
        # Case 1: 외부 명령(_pending_register)으로 closest 등록
        if self._pending_register and closest_person:
            self._register_target(closest_person)
            self._pending_register = False

        # Case 2: 자동 등록 — interaction_distance 이내 첫 감지 시
        if (self.target_id is None
                and closest_person
                and closest_person['distance_m'] is not None
                and closest_person['distance_m'] < self.interaction_dist):
            self._register_target(closest_person)

        self._update_tracking_state(target_det, detections)
        self._publish_all(detections, closest_person, target_det, w, h, msg)

    def _register_target(self, det: dict):
        self.target_id      = det['track_id']
        self.tracking_state = TrackingState.TRACKING
        self.lost_since     = None
        self.last_target_bbox = det['bbox']
        self.last_target_dist = det['distance_m']
        self.get_logger().info(
            f'Target registered: ID={self.target_id}, distance={det["distance_m"]}m'
        )

    def _release_target(self, reason: str = ''):
        self.get_logger().info(f'Target released (ID={self.target_id}): {reason}')
        self.target_id        = None
        self.tracking_state   = TrackingState.IDLE
        self.lost_since       = None
        self.last_target_bbox = None
        self.last_target_dist = None

    def _update_tracking_state(self, target_det: dict | None, all_dets: list):
        if self.target_id is None:
            return

        now = time.time()

        if target_det is not None:
            if self.tracking_state == TrackingState.LOST:
                self.get_logger().info(f'Target reacquired: ID={self.target_id}')
            self.tracking_state   = TrackingState.TRACKING
            self.lost_since       = None
            self.last_target_bbox = target_det['bbox']
            self.last_target_dist = target_det['distance_m']

        else:
            if self.tracking_state == TrackingState.TRACKING:
                self.tracking_state = TrackingState.LOST
                self.lost_since     = now
                self.get_logger().warn(
                    f'Target lost: ID={self.target_id} — waiting {self.lost_timeout:.0f}s'
                )
            elif self.tracking_state == TrackingState.LOST:
                elapsed = now - self.lost_since
                if elapsed > self.lost_timeout:
                    self._release_target(f'{self.lost_timeout:.0f}초 초과')
                else:
                    self._try_reacquire(all_dets)

    def _try_reacquire(self, detections: list) -> bool:
        if not self.last_target_bbox or not detections:
            return False

        best_iou, best_det = self.reacquire_iou, None
        for det in detections:
            iou = self._calc_iou(self.last_target_bbox, det['bbox'])
            if iou > best_iou:
                best_iou, best_det = iou, det

        if best_det:
            old_id = self.target_id
            self.target_id      = best_det['track_id']
            self.tracking_state = TrackingState.TRACKING
            self.lost_since     = None
            self.get_logger().info(
                f'Target ID reacquired: {old_id} → {self.target_id} (IoU={best_iou:.2f})'
            )
            return True
        return False

    @staticmethod
    def _calc_iou(a: list, b: list) -> float:
        ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
        ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        area_a = (a[2] - a[0]) * (a[3] - a[1])
        area_b = (b[2] - b[0]) * (b[3] - b[1])
        return inter / (area_a + area_b - inter)

    # Publish
    def _publish_all(self, detections, closest_person, target_det, w, h, original_msg):
        # persons detail JSON
        detail = String()
        detail.data = json.dumps({
            'count':      len(detections),
            'target_id':  self.target_id,
            'state':      self.tracking_state,
            'detections': detections,
        }, ensure_ascii=False)
        self.persons_detail_pub.publish(detail)

        # interaction_trigger
        trigger = Bool()
        if closest_person and closest_person['distance_m'] is not None:
            trigger.data = closest_person['distance_m'] < self.interaction_dist
        else:
            trigger.data = False
        self.hri_trigger_pub.publish(trigger)

        # tracking_state JSON
        now = time.time()
        lost_elapsed = round(now - self.lost_since, 2) if self.lost_since else 0.0
        state_msg = String()
        state_msg.data = json.dumps({
            'state':            self.tracking_state,
            'target_id':        self.target_id,
            'lost_elapsed_sec': lost_elapsed,
            'lost_timeout_sec': self.lost_timeout,
            'last_distance_m':  self.last_target_dist,
        }, ensure_ascii=False)
        self.tracking_state_pub.publish(state_msg)

        # follow/target_offset
        if target_det and target_det['distance_m'] is not None:
            offset = Point()
            offset.x = target_det['center_norm'][0] - 0.5  # 좌우 편차
            offset.y = target_det['center_norm'][1] - 0.5  # 상하 편차
            offset.z = target_det['distance_m']             # 현재 거리(m)
            self.follow_offset_pub.publish(offset)

        if self.visualize:
            self._publish_annotated(
                original_msg.header,
                cv2.cvtColor(
                    self.bridge.imgmsg_to_cv2(original_msg, desired_encoding='bgr8'),
                    cv2.COLOR_BGR2BGR,
                ) if False else self.bridge.imgmsg_to_cv2(original_msg, 'bgr8'),
                detections,
                target_det,
                original_msg,
            )

    def _publish_annotated(self, header, image, detections, target_det, original_msg):
        annotated = image.copy()

        for det in detections:
            x1, y1, x2, y2 = det['bbox']
            is_target = (det['track_id'] == self.target_id)

            if is_target and self.tracking_state == TrackingState.LOST:
                color, thick = (0, 165, 255), 3   # 주황: 소실 중
            elif is_target:
                color, thick = (0, 255, 0), 3     # 초록: 추적 중
            else:
                color, thick = (255, 200, 0), 1   # 파랑: 일반

            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thick)

            dist_str = f'{det["distance_m"]:.1f}m' if det['distance_m'] else 'N/A'
            id_str   = f'ID:{det["track_id"]}' if det['track_id'] != -1 else 'ID:?'
            label    = f'{"[T] " if is_target else ""}{id_str} {det["confidence"]:.2f} {dist_str}'
            cv2.putText(annotated, label, (x1, max(y1 - 8, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        state_colors = {
            TrackingState.IDLE:     (180, 180, 180),
            TrackingState.TRACKING: (0, 255, 0),
            TrackingState.LOST:     (0, 165, 255),
        }
        sc = state_colors.get(self.tracking_state, (255, 255, 255))
        overlay = f'[{self.tracking_state.upper()}]'
        if self.target_id is not None:
            overlay += f' Target={self.target_id}'
        if self.tracking_state == TrackingState.LOST and self.lost_since:
            overlay += f' ({time.time() - self.lost_since:.1f}s / {self.lost_timeout:.0f}s)'
        cv2.putText(annotated, overlay, (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, sc, 2)

        ann_msg = self.bridge.cv2_to_imgmsg(annotated, encoding='bgr8')
        ann_msg.header = original_msg.header
        self.annotated_pub.publish(ann_msg)

    # Depth 거리 추정
    def _estimate_distance(self, x1, y1, x2, y2) -> float | None:
        if self._latest_depth is None or not self.use_depth:
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

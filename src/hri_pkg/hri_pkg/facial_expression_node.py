#!/usr/bin/env python3
"""
Facial Expression Recognition Node (MediaPipe Face Mesh)
- 468-point face landmark extraction
- Classifies expression using mouth corner slope, brow distance, EAR
- Active only when interaction_trigger is true

Expressions: SATISFIED / CONFUSED / NEUTRAL

Publish topics:
  /dori/hri/expression           (String) - expression JSON
  /dori/hri/expression_command   (String) - expression → response command
  /dori/hri/annotated_expression (Image)  - visualization (optional)

Subscribe topics:
  /dori/camera/color/image_raw   (Image)
  /dori/hri/interaction_trigger  (Bool)
"""

import json
import math
import time
from collections import deque

import cv2
import numpy as np
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import Bool, String

try:
    import mediapipe as mp
    MP_AVAILABLE = True
except ImportError:
    MP_AVAILABLE = False


# MediaPipe Face Mesh
# https://github.com/google/mediapipe/blob/master/mediapipe/modules/face_geometry/data/canonical_face_model_uv_visualization.png

# Eyebrows
LEFT_EYEBROW_INNER  = 107
RIGHT_EYEBROW_INNER = 336
LEFT_EYEBROW_OUTER  = 70
RIGHT_EYEBROW_OUTER = 300

# Eyes
LEFT_EYE_H = (33, 133)
LEFT_EYE_V = (160, 144, 158, 153)

RIGHT_EYE_H = (362, 263)
RIGHT_EYE_V = (385, 380, 387, 373)

# Mouth
MOUTH_LEFT  = 61
MOUTH_RIGHT = 291
MOUTH_TOP   = 13
MOUTH_BOTTOM = 14

# Nose
NOSE_TIP = 4


class Expression:
    SATISFIED   = 'SATISFIED'
    CONFUSED    = 'CONFUSED'
    NEUTRAL     = 'NEUTRAL'


class FacialExpressionNode(Node):
    def __init__(self):
        super().__init__('facial_expression_node')

        # Parameters
        self.declare_parameter('min_detection_confidence', 0.5)
        self.declare_parameter('min_tracking_confidence', 0.5)
        self.declare_parameter('visualize', True)
        self.declare_parameter('active_only_on_trigger', True)
        self.declare_parameter('confirm_frames', 5)

        # Face expression thresholds (needs to be tuned)
        self.declare_parameter('smile_threshold', 0.02)
        self.declare_parameter('frown_threshold', -0.015)
        self.declare_parameter('brow_frown_threshold', 0.025)
        self.declare_parameter('ear_open_threshold', 0.25)

        det_conf  = self.get_parameter('min_detection_confidence').value
        trk_conf  = self.get_parameter('min_tracking_confidence').value
        self.visualize         = self.get_parameter('visualize').value
        self.active_on_trigger = self.get_parameter('active_only_on_trigger').value
        self.confirm_frames    = self.get_parameter('confirm_frames').value
        self.smile_thresh      = self.get_parameter('smile_threshold').value
        self.frown_thresh      = self.get_parameter('frown_threshold').value
        self.brow_frown_thresh = self.get_parameter('brow_frown_threshold').value
        self.ear_open_thresh   = self.get_parameter('ear_open_threshold').value

        if not MP_AVAILABLE:
            self.get_logger().error('mediapipe not installed: pip install mediapipe')
            return

        # MediaPipe Face Mesh initialization
        self.mp_face_mesh = mp.solutions.face_mesh
        self.mp_drawing   = mp.solutions.drawing_utils
        self.mp_styles    = mp.solutions.drawing_styles
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=False,
            min_detection_confidence=det_conf,
            min_tracking_confidence=trk_conf,
        )

        # State
        self.is_active = not self.active_on_trigger
        self.bridge    = CvBridge()
        self._expr_history: deque = deque(maxlen=self.confirm_frames)

        # Counters for expression-specific logic
        self._confused_count: int = 0
        self._confused_trigger_count: int = 3

        # Subscribers
        self.create_subscription(
            Image, '/dori/camera/color/image_raw', self.image_callback, 10)
        self.create_subscription(
            Bool, '/dori/hri/interaction_trigger', self._trigger_callback, 10)

        # Publishers
        self.expression_pub = self.create_publisher(String, '/dori/hri/expression', 10)
        self.command_pub    = self.create_publisher(String, '/dori/hri/expression_command', 10)
        if self.visualize:
            self.annotated_pub = self.create_publisher(
                Image, '/dori/hri/annotated_expression', 10)

        self.get_logger().info('Facial Expression Node started')

    # Callbacks
    def _trigger_callback(self, msg: Bool):
        if self.active_on_trigger:
            if msg.data and not self.is_active:
                self.is_active = True
                self._expr_history.clear()
                self._confused_count = 0
                self.get_logger().info('Face expression recognition activated')
            elif not msg.data and self.is_active:
                self.is_active = False
                self.get_logger().info('Face expression recognition deactivated')

    def image_callback(self, msg: Image):
        if not self.is_active:
            return

        try:
            cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
        except Exception as e:
            self.get_logger().error(f'Failed to convert image: {e}')
            return

        h, w = cv_image.shape[:2]
        rgb = cv2.cvtColor(cv_image, cv2.COLOR_BGR2RGB)
        results = self.face_mesh.process(rgb)

        if not results.multi_face_landmarks:
            self._expr_history.append(Expression.NEUTRAL)
            self._publish_expression(Expression.NEUTRAL, {}, msg)
            if self.visualize:
                self._publish_annotated(cv_image, None, Expression.NEUTRAL, {}, msg)
            return

        face_lm = results.multi_face_landmarks[0].landmark
        metrics = self._extract_metrics(face_lm, w, h)
        expression = self._classify(metrics)

        self._expr_history.append(expression)
        confirmed = self._confirm()

        if confirmed == Expression.CONFUSED:
            self._confused_count += 1
        else:
            self._confused_count = 0

        self._publish_expression(confirmed, metrics, msg)

        if self._confused_count >= self._confused_trigger_count:
            self._publish_command(confirmed, metrics)
            self._confused_count = 0

        if confirmed == Expression.SATISFIED:
            self._publish_command(confirmed, metrics)

        if self.visualize:
            self._publish_annotated(
                cv_image, results.multi_face_landmarks[0], confirmed, metrics, msg)

    def _extract_metrics(self, lm, w: int, h: int) -> dict:
        nose_y = lm[NOSE_TIP].y
        ref_dist = abs(lm[MOUTH_TOP].y - nose_y) + 1e-6

        # 1. mouth_corner_slope
        left_corner_y  = lm[MOUTH_LEFT].y
        right_corner_y = lm[MOUTH_RIGHT].y
        mouth_slope = (left_corner_y + right_corner_y) / 2 - lm[MOUTH_TOP].y
        mouth_slope_norm = -mouth_slope / ref_dist

        # 2. brow_distance
        brow_dist = abs(lm[LEFT_EYEBROW_INNER].x - lm[RIGHT_EYEBROW_INNER].x)
        face_width = abs(lm[MOUTH_LEFT].x - lm[MOUTH_RIGHT].x) + 1e-6
        brow_dist_norm = brow_dist / face_width

        # 3. EAR (Eye Aspect Ratio)
        left_ear  = self._calc_ear(lm, LEFT_EYE_H, LEFT_EYE_V)
        right_ear = self._calc_ear(lm, RIGHT_EYE_H, RIGHT_EYE_V)
        ear = (left_ear + right_ear) / 2

        return {
            'mouth_slope':    round(mouth_slope_norm, 4),
            'brow_distance':  round(brow_dist_norm, 4),
            'ear':            round(ear, 4),
        }

    @staticmethod
    def _calc_ear(lm, h_indices: tuple, v_indices: tuple) -> float:
        h_dist = math.dist(
            (lm[h_indices[0]].x, lm[h_indices[0]].y),
            (lm[h_indices[1]].x, lm[h_indices[1]].y)
        )
        v1 = math.dist(
            (lm[v_indices[0]].x, lm[v_indices[0]].y),
            (lm[v_indices[1]].x, lm[v_indices[1]].y)
        )
        v2 = math.dist(
            (lm[v_indices[2]].x, lm[v_indices[2]].y),
            (lm[v_indices[3]].x, lm[v_indices[3]].y)
        )
        if h_dist < 1e-6:
            return 0.0
        return (v1 + v2) / (2.0 * h_dist)

    def _classify(self, metrics: dict) -> str:

        slope = metrics['mouth_slope']
        brow  = metrics['brow_distance']
        ear   = metrics['ear']

        # CONFUSED
        if brow < self.brow_frown_thresh and slope < self.frown_thresh:
            return Expression.CONFUSED

        # SATISFIED
        if ear > self.ear_open_thresh and slope > self.smile_thresh:
            return Expression.SATISFIED

        return Expression.NEUTRAL

    def _confirm(self) -> str:
        if len(self._expr_history) < self.confirm_frames:
            return Expression.NEUTRAL
        hist = list(self._expr_history)
        if all(e == hist[-1] for e in hist):
            return hist[-1]
        return Expression.NEUTRAL

    # Publishing
    def _publish_expression(self, expression: str, metrics: dict, original_msg):
        msg = String()
        msg.data = json.dumps({
            'expression': expression,
            'metrics':    metrics,
            'timestamp':  time.time(),
        }, ensure_ascii=False)
        self.expression_pub.publish(msg)

    def _publish_command(self, expression: str, metrics: dict):
        if expression == Expression.CONFUSED:
            command = {
                'command':     'REPEAT_GUIDANCE',
                'description': '다시 설명해드릴까요?',
                'tts_text':    '안내가 잘 이해되셨나요? 다시 설명해드릴까요?',
            }
        elif expression == Expression.SATISFIED:
            command = {
                'command':     'GUIDANCE_COMPLETE',
                'description': '안내 완료',
                'tts_text':    '안내가 도움이 되셨다니 다행입니다!',
            }
        else:
            return

        msg = String()
        msg.data = json.dumps(command, ensure_ascii=False)
        self.command_pub.publish(msg)
        self.get_logger().info(f'Expression command: {command["command"]}')

    def _publish_annotated(self, image: np.ndarray, face_landmarks,
                           expression: str, metrics: dict, original_msg):
        annotated = image.copy()

        if face_landmarks:
            self.mp_drawing.draw_landmarks(
                annotated,
                face_landmarks,
                self.mp_face_mesh.FACEMESH_CONTOURS,
                landmark_drawing_spec=None,
                connection_drawing_spec=self.mp_styles.get_default_face_mesh_contours_style(),
            )

        color = {
            Expression.SATISFIED: (0, 255, 0),
            Expression.CONFUSED:  (0, 100, 255),
            Expression.NEUTRAL:   (180, 180, 180),
        }.get(expression, (255, 255, 255))

        cv2.putText(annotated, f'Expression: {expression}', (10, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.85, color, 2)

        if metrics:
            y = 65
            for key, val in metrics.items():
                cv2.putText(annotated, f'{key}: {val:.3f}', (10, y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
                y += 18

        active_str = 'ACTIVE' if self.is_active else 'INACTIVE'
        cv2.putText(annotated, active_str,
                    (annotated.shape[1] - 90, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (0, 255, 0) if self.is_active else (100, 100, 100), 1)

        ann_msg = self.bridge.cv2_to_imgmsg(annotated, encoding='bgr8')
        ann_msg.header = original_msg.header
        self.annotated_pub.publish(ann_msg)

    def destroy_node(self):
        self.face_mesh.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FacialExpressionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

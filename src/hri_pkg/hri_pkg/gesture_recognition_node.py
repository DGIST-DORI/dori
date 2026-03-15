#!/usr/bin/env python3
"""
Gesture Recognition Node (MediaPipe Hands)
- 21-point hand landmark-based gesture classification
- Active only when interaction_trigger is true (saves resources)
- CPU-only (GPU reserved for YOLO)

Recognized gestures:
  STOP      : all 5 fingers extended → stop command
  POINT     : index only + direction → destination hint
  WAVE      : left-right wrist motion → call robot (triggers wake word handler)
  THUMBS_UP : thumb up only → positive confirmation
  NONE      : no hand / unclassified

Publish topics:
  /dori/hri/gesture           (String) - gesture detection JSON
  /dori/hri/gesture_command   (String) - gesture → command mapping
  /dori/stt/wake_word_detected (Bool)  - published on WAVE (routes to HRI Manager)
  /dori/hri/annotated_gesture (Image)  - visualization (optional)

Subscribe topics:
  /dori/camera/color/image_raw    (Image)
  /dori/hri/interaction_trigger   (Bool)
"""

import json
import math
import time
from collections import deque
from enum import Enum

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


class Gesture(str, Enum):
    STOP      = 'STOP'
    POINT     = 'POINT'
    WAVE      = 'WAVE'
    THUMBS_UP = 'THUMBS_UP'
    NONE      = 'NONE'


# MediaPipe Hands
# https://developers.google.com/mediapipe/solutions/vision/hand_landmarker
WRIST        = 0
THUMB_TIP    = 4;  THUMB_MCP    = 2
INDEX_TIP    = 8;  INDEX_PIP    = 6;  INDEX_MCP = 5
MIDDLE_TIP   = 12; MIDDLE_PIP   = 10
RING_TIP     = 16; RING_PIP     = 14
PINKY_TIP    = 20; PINKY_PIP    = 18


class GestureRecognitionNode(Node):
    def __init__(self):
        super().__init__('gesture_recognition_node')

        # Parameters
        self.declare_parameter('min_detection_confidence', 0.7)
        self.declare_parameter('min_tracking_confidence', 0.5)
        self.declare_parameter('visualize', True)
        self.declare_parameter('active_only_on_trigger', True)   # trigger 시에만 활성화
        self.declare_parameter('wave_history_len', 10)           # WAVE 판정용 이력 길이
        self.declare_parameter('wave_threshold', 0.08)           # WAVE x축 변화 임계값
        self.declare_parameter('gesture_confirm_frames', 3)      # 연속 N프레임 확인 후 발행

        det_conf   = self.get_parameter('min_detection_confidence').value
        trk_conf   = self.get_parameter('min_tracking_confidence').value
        self.visualize          = self.get_parameter('visualize').value
        self.active_on_trigger  = self.get_parameter('active_only_on_trigger').value
        wave_history_len        = self.get_parameter('wave_history_len').value
        self.wave_thresh        = self.get_parameter('wave_threshold').value
        self.confirm_frames     = self.get_parameter('gesture_confirm_frames').value

        if not MP_AVAILABLE:
            self.get_logger().error('mediapipe not installed: pip install mediapipe')
            return

        # MediaPipe initialization
        self.mp_hands    = mp.solutions.hands
        self.mp_drawing  = mp.solutions.drawing_utils
        self.mp_styles   = mp.solutions.drawing_styles
        self.hands = self.mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=1,              # 캠퍼스 안내 상황: 주요 손 1개만
            min_detection_confidence=det_conf,
            min_tracking_confidence=trk_conf,
            model_complexity=0,           # 0=경량 (Jetson CPU 최적)
        )

        # State
        self.is_active: bool = not self.active_on_trigger  # trigger OFF면 항상 활성
        self.bridge = CvBridge()

        self._wrist_x_history: deque = deque(maxlen=wave_history_len)

        self._gesture_history: deque = deque(maxlen=self.confirm_frames)

        # Subscribers
        self.create_subscription(
            Image, '/dori/camera/color/image_raw', self.image_callback, 10)
        self.create_subscription(
            Bool, '/dori/hri/interaction_trigger', self._trigger_callback, 10)

        # Publishers
        self.gesture_pub   = self.create_publisher(String, '/dori/hri/gesture', 10)
        self.command_pub   = self.create_publisher(String, '/dori/hri/gesture_command', 10)
        # WAVE gesture routes to HRI Manager via wake_word_detected (same handler as voice)
        self.trigger_pub   = self.create_publisher(Bool, '/dori/stt/wake_word_detected', 10)
        if self.visualize:
            self.annotated_pub = self.create_publisher(
                Image, '/dori/hri/annotated_gesture', 10)

        self.get_logger().info(
            f'Gesture Recognition Node started with parameters: '
            f'(active_on_trigger={self.active_on_trigger})'
        )

    # Callbacks
    def _trigger_callback(self, msg: Bool):
        """interaction_trigger true → 제스처 인식 활성화"""
        if self.active_on_trigger:
            if msg.data and not self.is_active:
                self.is_active = True
                self.get_logger().info('Gesture recognition activated by trigger')
            elif not msg.data and self.is_active:
                self.is_active = False
                self._gesture_history.clear()
                self._wrist_x_history.clear()
                self.get_logger().info('Gesture recognition deactivated by trigger')

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
        results = self.hands.process(rgb)

        if not results.multi_hand_landmarks:
            self._gesture_history.append(Gesture.NONE)
            self._wrist_x_history.clear()
            self._publish_gesture(Gesture.NONE, None, None)
            if self.visualize:
                self._publish_annotated(cv_image, None, Gesture.NONE, msg)
            return

        # 첫 번째 손만 처리
        hand_landmarks = results.multi_hand_landmarks[0]
        lm = hand_landmarks.landmark  # 랜드마크 리스트 (0~20)

        # 손목 x이력 갱신 (WAVE 감지용) ───────────────────────────
        self._wrist_x_history.append(lm[WRIST].x)

        # 제스처 분류 ──────────────────────────────────────────────
        gesture = self._classify(lm, w, h)

        # 연속 confirm_frames 동안 같은 제스처여야 발행 (노이즈 방지)
        self._gesture_history.append(gesture)
        confirmed = self._confirm_gesture()

        # 방향 추정 (POINT 제스처일 때) ───────────────────────────
        direction = None
        if confirmed == Gesture.POINT:
            direction = self._calc_point_direction(lm)

        self._publish_gesture(confirmed, direction, hand_landmarks)

        # WAVE → interaction_trigger 강제 발행
        if confirmed == Gesture.WAVE:
            trig = Bool()
            trig.data = True
            self.trigger_pub.publish(trig)
            self.get_logger().info('WAVE detected → interaction_trigger forced publication')

        if self.visualize:
            self._publish_annotated(cv_image, hand_landmarks, confirmed, msg)

    def _classify(self, lm, w: int, h: int) -> Gesture:
        """
        손 랜드마크 기하학적 분석으로 제스처 분류

        손가락 펼침 판단:
          - TIP의 y좌표 < PIP의 y좌표 → 펼쳐짐 (이미지 좌표계: 위가 y=0)
          - 엄지는 x축으로 판단 (왼손/오른손 방향 고려)
        """
        fingers_extended = self._get_extended_fingers(lm)
        # fingers_extended: [thumb, index, middle, ring, pinky] bool list

        # STOP: 5개 모두 펼침 ──────────────────────────────────────
        if all(fingers_extended):
            return Gesture.STOP

        # THUMBS_UP: 엄지만 펼침 ──────────────────────────────────
        if fingers_extended[0] and not any(fingers_extended[1:]):
            return Gesture.THUMBS_UP

        # POINT: 검지만 펼침 ──────────────────────────────────────
        if (fingers_extended[1]
                and not fingers_extended[2]
                and not fingers_extended[3]
                and not fingers_extended[4]):
            return Gesture.POINT

        # WAVE: 손목 x 이력에서 방향 전환 감지 ────────────────────
        if self._detect_wave():
            return Gesture.WAVE

        return Gesture.NONE

    def _get_extended_fingers(self, lm) -> list[bool]:
        """
        각 손가락 펼침 여부 반환 [thumb, index, middle, ring, pinky]
        엄지: tip이 mcp보다 바깥쪽 (x축)
        나머지: tip이 pip보다 위 (y축, 이미지 좌표)
        """
        # 엄지 — x축 기준 (왼손 기준; 오른손이면 부호 반전되나 근사값으로 사용)
        thumb_ext = lm[THUMB_TIP].x < lm[THUMB_MCP].x

        index_ext  = lm[INDEX_TIP].y  < lm[INDEX_PIP].y
        middle_ext = lm[MIDDLE_TIP].y < lm[MIDDLE_PIP].y
        ring_ext   = lm[RING_TIP].y   < lm[RING_PIP].y
        pinky_ext  = lm[PINKY_TIP].y  < lm[PINKY_PIP].y

        return [thumb_ext, index_ext, middle_ext, ring_ext, pinky_ext]

    def _detect_wave(self) -> bool:
        hist = list(self._wrist_x_history)
        if len(hist) < 6:
            return False

        direction_changes = 0
        prev_dir = None
        for i in range(1, len(hist)):
            diff = hist[i] - hist[i - 1]
            if abs(diff) < self.wave_thresh:
                continue
            cur_dir = 1 if diff > 0 else -1
            if prev_dir is not None and cur_dir != prev_dir:
                direction_changes += 1
            prev_dir = cur_dir

        return direction_changes >= 2

    def _confirm_gesture(self) -> Gesture:
        if len(self._gesture_history) < self.confirm_frames:
            return Gesture.NONE
        hist = list(self._gesture_history)
        if all(g == hist[-1] for g in hist):
            return hist[-1]
        return Gesture.NONE

    def _calc_point_direction(self, lm) -> dict:
        dx = lm[INDEX_TIP].x - lm[INDEX_MCP].x
        dy = lm[INDEX_TIP].y - lm[INDEX_MCP].y   # y: upside down in image coordinates

        angle_rad = math.atan2(-dy, dx)
        angle_deg = math.degrees(angle_rad) % 360

        if 45 <= angle_deg < 135:
            label = 'UP'
        elif 135 <= angle_deg < 225:
            label = 'LEFT'
        elif 225 <= angle_deg < 315:
            label = 'DOWN'
        else:
            label = 'RIGHT'

        return {
            'angle_deg': round(angle_deg, 1),
            'label':     label,
            'vector':    [round(dx, 3), round(-dy, 3)],
        }

    # Publishing
    def _publish_gesture(self, gesture: Gesture, direction: dict | None, hand_landmarks):
        gesture_data = {
            'gesture':   gesture.value,
            'direction': direction,
            'timestamp': time.time(),
        }
        g_msg = String()
        g_msg.data = json.dumps(gesture_data, ensure_ascii=False)
        self.gesture_pub.publish(g_msg)

        # gesture to command
        command = self._gesture_to_command(gesture, direction)
        if command:
            c_msg = String()
            c_msg.data = json.dumps(command, ensure_ascii=False)
            self.command_pub.publish(c_msg)
            self.get_logger().info(f'Gesture command: {command}')

    def _gesture_to_command(self, gesture: Gesture, direction: dict | None) -> dict | None:
        if gesture == Gesture.STOP:
            return {'command': 'STOP', 'description': '주행 정지'}

        if gesture == Gesture.WAVE:
            return {'command': 'CALL', 'description': '로봇 호출'}

        if gesture == Gesture.THUMBS_UP:
            return {'command': 'CONFIRM', 'description': '긍정 / 안내 확인'}

        if gesture == Gesture.POINT and direction:
            return {
                'command':     'DIRECTION_HINT',
                'direction':   direction['label'],
                'angle_deg':   direction['angle_deg'],
                'description': f'{direction["label"]} 방향 지시',
            }

        return None

    def _publish_annotated(self, image: np.ndarray, hand_landmarks, gesture: Gesture, original_msg):
        annotated = image.copy()

        if hand_landmarks:
            self.mp_drawing.draw_landmarks(
                annotated,
                hand_landmarks,
                self.mp_hands.HAND_CONNECTIONS,
                self.mp_styles.get_default_hand_landmarks_style(),
                self.mp_styles.get_default_hand_connections_style(),
            )

        color = {
            Gesture.STOP:      (0, 0, 255),
            Gesture.POINT:     (0, 255, 255),
            Gesture.WAVE:      (255, 0, 255),
            Gesture.THUMBS_UP: (0, 255, 0),
            Gesture.NONE:      (180, 180, 180),
        }.get(gesture, (255, 255, 255))

        cv2.putText(annotated, f'Gesture: {gesture.value}', (10, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)

        active_str = 'ACTIVE' if self.is_active else 'INACTIVE'
        cv2.putText(annotated, active_str, (10, 65),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    (0, 255, 0) if self.is_active else (100, 100, 100), 1)

        ann_msg = self.bridge.cv2_to_imgmsg(annotated, encoding='bgr8')
        ann_msg.header = original_msg.header
        self.annotated_pub.publish(ann_msg)

    def destroy_node(self):
        self.hands.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = GestureRecognitionNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

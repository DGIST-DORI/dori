#!/usr/bin/env python3
"""
Subscribe topics:
  /dori/hri/interaction_trigger  (Bool)
  /dori/hri/tracking_state       (String)
  /dori/hri/gesture_command      (String)
  /dori/hri/expression_command   (String)
  /dori/landmark/context         (String)

Publish topics:
  /dori/hri/set_follow_mode      (Bool)
  /dori/hri/manager_state        (String)
  /dori/llm/query                (String)
  /dori/tts/text                 (String)
  /dori/nav/command              (String)

HRI Manager state machine:
  IDLE
  GREETING
  LISTENING
  NAVIGATING
  RESPONDING
"""

import json
import time
from enum import Enum

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String


class HRIState(str, Enum):
    IDLE       = 'IDLE'
    GREETING   = 'GREETING'
    LISTENING  = 'LISTENING'
    NAVIGATING = 'NAVIGATING'
    RESPONDING = 'RESPONDING'


class HRIManagerNode(Node):
    def __init__(self):
        super().__init__('hri_manager_node')

        # Parameters
        self.declare_parameter('greeting_text', '안녕하세요! 저는 캠퍼스 안내 로봇입니다. 어디로 안내해드릴까요?')
        self.declare_parameter('idle_timeout_sec', 10.0)       # GREETING 후 응답 없으면 IDLE 복귀
        self.declare_parameter('navigation_follow_dist', 1.2)  # 추종 거리 (m)

        self.greeting_text  = self.get_parameter('greeting_text').value
        self.idle_timeout   = self.get_parameter('idle_timeout_sec').value

        # State Variations
        self.state: HRIState = HRIState.IDLE
        self.state_enter_time: float = time.time()
        self.current_landmark_context: str = ''   # 최신 위치 컨텍스트
        self.last_trigger: bool = False            # 직전 trigger 상태 (엣지 감지용)
        self.tracking_state: dict = {}             # 최신 추적 상태

        # Subscribers
        self.create_subscription(
            Bool, '/dori/hri/interaction_trigger', self._on_trigger, 10)
        self.create_subscription(
            String, '/dori/hri/tracking_state', self._on_tracking_state, 10)
        self.create_subscription(
            String, '/dori/hri/gesture_command', self._on_gesture_command, 10)
        self.create_subscription(
            String, '/dori/hri/expression_command', self._on_expression_command, 10)
        self.create_subscription(
            String, '/dori/landmark/context', self._on_landmark_context, 10)
        self.create_subscription(
            String, '/dori/stt/result', self._on_stt_result, 10)

        # Publishers
        self.follow_mode_pub    = self.create_publisher(Bool,   '/dori/hri/set_follow_mode', 10)
        self.manager_state_pub  = self.create_publisher(String, '/dori/hri/manager_state', 10)
        self.llm_query_pub      = self.create_publisher(String, '/dori/llm/query', 10)
        self.tts_pub            = self.create_publisher(String, '/dori/tts/text', 10)
        self.nav_command_pub    = self.create_publisher(String, '/dori/nav/command', 10)

        # Status Periodic Publishing (1Hz)
        self.create_timer(1.0, self._publish_state)
        # check idle_timeout (2Hz)
        self.create_timer(0.5, self._check_timeout)

        self.get_logger().info('HRI Manager Node 시작')

    # callback
    def _on_trigger(self, msg: Bool):
        rising_edge = msg.data and not self.last_trigger
        self.last_trigger = msg.data

        if rising_edge and self.state == HRIState.IDLE:
            self._transition(HRIState.GREETING)
            self._greet()

    def _on_tracking_state(self, msg: String):
        try:
            self.tracking_state = json.loads(msg.data)
        except json.JSONDecodeError:
            pass

        if (self.state == HRIState.NAVIGATING
                and self.tracking_state.get('state') == 'idle'):
            self.get_logger().info('Target 소실로 네비게이션 종료')
            self._transition(HRIState.IDLE)
            self._set_follow_mode(False)
            self._say('안내 대상을 잃어버렸습니다. 다시 말씀해 주세요.')

    def _on_gesture_command(self, msg: String):
        try:
            cmd = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        command = cmd.get('command')
        self.get_logger().info(f'제스처 명령 수신: {command}')

        if command == 'STOP':
            self._nav_command('STOP')
            self._say('알겠습니다, 멈추겠습니다.')

        elif command == 'CALL' and self.state == HRIState.IDLE:
            # WAVE로 호출 → GREETING
            self._transition(HRIState.GREETING)
            self._greet()

        elif command == 'CONFIRM':
            if self.state == HRIState.NAVIGATING:
                self._say('네, 계속 안내해 드리겠습니다.')

        elif command == 'DIRECTION_HINT':
            direction = cmd.get('direction', '')
            self.get_logger().info(f'방향 힌트: {direction}')

    def _on_expression_command(self, msg: String):
        try:
            cmd = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        command = cmd.get('command')
        self.get_logger().info(f'표정 명령 수신: {command}')

        if command == 'REPEAT_GUIDANCE':
            # 불만족 표정
            if self.state in (HRIState.NAVIGATING, HRIState.RESPONDING):
                self._say(cmd.get('tts_text', '다시 설명해드릴까요?'))

        elif command == 'GUIDANCE_COMPLETE':
            # 만족 표정
            if self.state == HRIState.NAVIGATING:
                self._say(cmd.get('tts_text', '안내가 도움이 되셨다니 다행입니다!'))
                self._transition(HRIState.IDLE)
                self._set_follow_mode(False)

    def _on_landmark_context(self, msg: String):
        self.current_landmark_context = msg.data

    def _on_stt_result(self, msg: String):
        user_text = msg.data.strip()
        if not user_text:
            return

        self.get_logger().info(f'STT 수신: "{user_text}"')
        self._transition(HRIState.RESPONDING)
        self._send_to_llm(user_text)

    # State machine helper
    def _transition(self, new_state: HRIState):
        old = self.state
        self.state = new_state
        self.state_enter_time = time.time()
        self.get_logger().info(f'state transition: {old} → {new_state}')

    def _check_timeout(self):
        if self.state == HRIState.GREETING:
            elapsed = time.time() - self.state_enter_time
            if elapsed > self.idle_timeout:
                self.get_logger().info(f'GREETING timeout ({self.idle_timeout}s) → IDLE')
                self._transition(HRIState.IDLE)

    # Action helper
    def _greet(self):
        self._say(self.greeting_text)
        self._transition(HRIState.LISTENING)

    def _say(self, text: str):
        msg = String()
        msg.data = text
        self.tts_pub.publish(msg)
        self.get_logger().info(f'TTS: "{text}"')

    def _send_to_llm(self, user_text: str):
        payload = {
            'user_text':         user_text,
            'location_context':  self.current_landmark_context,
            'hri_state':         self.state.value,
            'tracking_state':    self.tracking_state,
            'timestamp':         time.time(),
        }
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.llm_query_pub.publish(msg)
        self.get_logger().info(f'LLM 쿼리 발행: "{user_text[:30]}..."')

    def _set_follow_mode(self, enable: bool):
        msg = Bool()
        msg.data = enable
        self.follow_mode_pub.publish(msg)
        self.get_logger().info(f'Follow mode: {"ON" if enable else "OFF"}')

    def _nav_command(self, command: str, **kwargs):
        payload = {'command': command, **kwargs, 'timestamp': time.time()}
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.nav_command_pub.publish(msg)

    # State publish
        msg = String()
        msg.data = json.dumps({
            'state':             self.state.value,
            'state_elapsed_sec': round(time.time() - self.state_enter_time, 1),
            'target_id':         self.tracking_state.get('target_id'),
            'location_context':  self.current_landmark_context,
        }, ensure_ascii=False)
        self.manager_state_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = HRIManagerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
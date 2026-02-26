#!/usr/bin/env python3
"""
Central coordinator for all HRI subsystems.
Manages state machine and routes commands between nodes.

Subscribe topics:
  /dori/stt/wake_word_detected   (Bool)   - wake word detected signal
  /dori/stt/result               (String) - transcribed text from STT
  /dori/hri/tracking_state       (String) - person tracking state
  /dori/hri/gesture_command      (String) - gesture command
  /dori/hri/expression_command   (String) - expression command
  /dori/landmark/context         (String) - current location context for LLM
  /dori/tts/done                 (Bool)   - TTS playback finished

Publish topics:
  /dori/hri/set_follow_mode      (Bool)   - enable/disable person following
  /dori/hri/manager_state        (String) - current HRI state (1 Hz)
  /dori/llm/query                (String) - query + context sent to LLM node
  /dori/tts/text                 (String) - direct TTS output (bypass LLM)
  /dori/nav/command              (String) - high-level navigation command

State machine:
  IDLE        - waiting for wake word
  LISTENING   - wake word detected, waiting for STT result
  RESPONDING  - LLM generating response
  NAVIGATING  - guiding user to destination (person following active)
"""

import json
import time
from enum import Enum

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String


class HRIState(str, Enum):
    IDLE       = 'IDLE'
    LISTENING  = 'LISTENING'
    RESPONDING = 'RESPONDING'
    NAVIGATING = 'NAVIGATING'


class HRIManagerNode(Node):
    def __init__(self):
        super().__init__('hri_manager_node')

        # Parameters
        self.declare_parameter('greeting_text', '안녕하세요! 저는 캠퍼스 안내 로봇 도리입니다. 어디로 안내해드릴까요?')
        self.declare_parameter('idle_timeout_sec', 10.0)

        self.greeting_text = self.get_parameter('greeting_text').value
        self.idle_timeout  = self.get_parameter('idle_timeout_sec').value

        # State variables
        self.state: HRIState        = HRIState.IDLE
        self.state_enter_time: float = time.time()
        self.landmark_context: str  = ''
        self.tracking_state: dict   = {}

        # Subscribers
        self.create_subscription(
            Bool, '/dori/stt/wake_word_detected', self._on_wake_word, 10)
        self.create_subscription(
            String, '/dori/stt/result', self._on_stt_result, 10)
        self.create_subscription(
            String, '/dori/hri/tracking_state', self._on_tracking_state, 10)
        self.create_subscription(
            String, '/dori/hri/gesture_command', self._on_gesture_command, 10)
        self.create_subscription(
            String, '/dori/hri/expression_command', self._on_expression_command, 10)
        self.create_subscription(
            String, '/dori/landmark/context', self._on_landmark_context, 10)
        self.create_subscription(
            Bool, '/dori/tts/done', self._on_tts_done, 10)

        # Publishers
        self.follow_mode_pub   = self.create_publisher(Bool,   '/dori/hri/set_follow_mode', 10)
        self.manager_state_pub = self.create_publisher(String, '/dori/hri/manager_state', 10)
        self.llm_query_pub     = self.create_publisher(String, '/dori/llm/query', 10)
        self.tts_pub           = self.create_publisher(String, '/dori/tts/text', 10)
        self.nav_command_pub   = self.create_publisher(String, '/dori/nav/command', 10)

        # State publish timer (1 Hz)
        self.create_timer(1.0, self._publish_state)
        # Idle timeout check (2 Hz)
        self.create_timer(0.5, self._check_timeout)

        self.get_logger().info('HRI Manager Node started')

    # Subscriber callbacks
    def _on_wake_word(self, msg: Bool):
        """
        Wake word detected → start HRI session.
        Only responds when IDLE to prevent re-triggering mid-conversation.
        WAVE gesture also routes here via /dori/stt/wake_word_detected.
        """
        if not msg.data:
            return

        if self.state == HRIState.IDLE:
            self.get_logger().info('Wake word detected — starting HRI session')
            self._transition(HRIState.LISTENING)
            self._say(self.greeting_text)
        else:
            self.get_logger().debug(
                f'Wake word ignored — already in state {self.state}'
            )

    def _on_stt_result(self, msg: String):
        """STT transcription received — forward to LLM with location context."""
        if self.state != HRIState.LISTENING:
            self.get_logger().debug('STT result ignored — not in LISTENING state')
            return

        try:
            data = json.loads(msg.data)
            user_text = data.get('text', '').strip()
        except (json.JSONDecodeError, AttributeError):
            user_text = msg.data.strip()

        if not user_text:
            return

        self.get_logger().info(f'STT result: "{user_text}"')
        self._transition(HRIState.RESPONDING)
        self._send_to_llm(user_text)

    def _on_tracking_state(self, msg: String):
        try:
            self.tracking_state = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        # Target lost during navigation → end session
        if (self.state == HRIState.NAVIGATING
                and self.tracking_state.get('state') == 'idle'):
            self.get_logger().info('Target lost — ending navigation')
            self._transition(HRIState.IDLE)
            self._set_follow_mode(False)
            self._say('안내 대상을 잃어버렸습니다. 다시 불러주세요.')

    def _on_gesture_command(self, msg: String):
        try:
            cmd = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        command = cmd.get('command')
        self.get_logger().info(f'Gesture command: {command}')

        if command == 'STOP':
            self._nav_command('STOP')
            self._say('알겠습니다, 멈추겠습니다.')

        elif command == 'CALL' and self.state == HRIState.IDLE:
            # WAVE gesture → same as wake word
            self.get_logger().info('WAVE gesture → triggering wake word handler')
            wake_msg = Bool()
            wake_msg.data = True
            self._on_wake_word(wake_msg)

        elif command == 'CONFIRM' and self.state == HRIState.NAVIGATING:
            self._say('네, 계속 안내해 드리겠습니다.')

        elif command == 'DIRECTION_HINT':
            self.get_logger().info(f'Direction hint: {cmd.get("direction", "")}')

    def _on_expression_command(self, msg: String):
        try:
            cmd = json.loads(msg.data)
        except json.JSONDecodeError:
            return

        command = cmd.get('command')
        self.get_logger().info(f'Expression command: {command}')

        if command == 'REPEAT_GUIDANCE':
            if self.state in (HRIState.NAVIGATING, HRIState.RESPONDING):
                self._say(cmd.get('tts_text', '다시 설명해드릴까요?'))

        elif command == 'GUIDANCE_COMPLETE':
            if self.state == HRIState.NAVIGATING:
                self._say(cmd.get('tts_text', '안내가 도움이 되셨다니 다행입니다!'))
                self._transition(HRIState.IDLE)
                self._set_follow_mode(False)

    def _on_landmark_context(self, msg: String):
        self.landmark_context = msg.data

    def _on_tts_done(self, msg: Bool):
        """
        TTS finished speaking.
        RESPONDING → LISTENING: wait for follow-up question.
        NAVIGATING: stay in NAVIGATING (still guiding).
        """
        if not msg.data:
            return

        if self.state == HRIState.RESPONDING:
            self.get_logger().info('TTS done — back to LISTENING')
            self._transition(HRIState.LISTENING)

    # State machine
    def _transition(self, new_state: HRIState):
        self.get_logger().info(f'State: {self.state} → {new_state}')
        self.state = new_state
        self.state_enter_time = time.time()

    def _check_timeout(self):
        """
        LISTENING timeout: if no STT result within idle_timeout seconds,
        return to IDLE and release follow mode.
        """
        if self.state == HRIState.LISTENING:
            elapsed = time.time() - self.state_enter_time
            if elapsed > self.idle_timeout:
                self.get_logger().info(
                    f'LISTENING timeout ({self.idle_timeout}s) → IDLE'
                )
                self._transition(HRIState.IDLE)
                self._set_follow_mode(False)

    # Action helpers
    def _say(self, text: str):
        """Publish text directly to TTS node (bypasses LLM)."""
        msg = String()
        msg.data = text
        self.tts_pub.publish(msg)
        self.get_logger().info(f'TTS: "{text}"')

    def _send_to_llm(self, user_text: str):
        """Package user text + location context and publish to LLM node."""
        payload = {
            'user_text':        user_text,
            'location_context': self.landmark_context,
            'hri_state':        self.state.value,
            'timestamp':        time.time(),
        }
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.llm_query_pub.publish(msg)
        self.get_logger().info(f'LLM query: "{user_text[:40]}"')

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
    def _publish_state(self):
        msg = String()
        msg.data = json.dumps({
            'state':             self.state.value,
            'state_elapsed_sec': round(time.time() - self.state_enter_time, 1),
            'target_id':         self.tracking_state.get('target_id'),
            'location_context':  self.landmark_context,
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

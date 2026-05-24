#!/usr/bin/env python3
"""
Central coordinator for all HRI subsystems.
Manages state machine and routes commands between nodes.

Subscribe topics:
  stt/wake_word_detected   (Bool)   - wake word detected signal
  stt/result               (String) - transcribed text from STT
  hri/tracking_state       (String) - person tracking state
  hri/gesture_command      (String) - gesture command
  hri/expression_command   (String) - expression command
  landmark/context         (String) - current location context for LLM
  tts/done                 (Bool)   - legacy completion signal
  tts/done_detail          (String) - JSON completion payload with success/error

Publish topics:
  hri/manager_state        (String) - current HRI state (1 Hz)
  llm/query                (String) - query + context sent to LLM node
  tts/text                 (String) - direct TTS output (bypass LLM)
  nav/command              (String) - high-level navigation command
  hri/audio_cue            (String) - short SFX cue event

Service clients:
  hri/set_follow_mode      (SetBool) - enable/disable person following

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
from std_srvs.srv import SetBool
from std_msgs.msg import Bool, String


class HRIState(str, Enum):
    IDLE       = 'IDLE'
    LISTENING  = 'LISTENING'
    RESPONDING = 'RESPONDING'
    NAVIGATING = 'NAVIGATING'



SYSTEM_PROMPTS = {
    'timeout_exit': '응답이 없어 대화를 종료할게요.',
    'reprompt_short': '잘 못 들었어요. 다시 말씀해 주세요.',
    'tts_error_retry': '죄송해요, 음성 출력에 문제가 있었어요. 다시 한 번 말씀해 주세요.',
    'target_lost': '안내 대상을 잃어버렸습니다. 다시 불러주세요.',
}

STT_EVENTS = {
    'RESULT': 'stt_result',
    'EMPTY_OR_LOW_CONF': 'stt_empty_or_low_conf',
}

class HRIManagerNode(Node):
    def __init__(self):
        super().__init__('hri_manager_node')

        # Parameters
        self.declare_parameter('greeting_text', '안녕하세요! 저는 캠퍼스 안내 로봇 도리입니다. 어디로 안내해드릴까요?')
        self.declare_parameter('idle_timeout_sec', 10.0)
        self.declare_parameter('wake_debounce_sec', 1.5)
        self.declare_parameter('reprompt_max_count', 2)
        self.declare_parameter('system_prompt_cooldown_sec', 2.0)
        self.declare_parameter('topics.wake_word_sub', 'stt/wake_word_detected')
        self.declare_parameter('topics.stt_result_sub', 'stt/result')
        self.declare_parameter('topics.tracking_state_sub', 'hri/tracking_state')
        self.declare_parameter('topics.gesture_command_sub', 'hri/gesture_command')
        self.declare_parameter('topics.expression_command_sub', 'hri/expression_command')
        self.declare_parameter('topics.landmark_context_sub', 'landmark/context')
        self.declare_parameter('topics.tts_done_sub', 'tts/done')
        self.declare_parameter('topics.tts_done_detail_sub', 'tts/done_detail')
        self.declare_parameter('services.follow_mode_service', 'hri/set_follow_mode')
        self.declare_parameter('topics.manager_state_pub', 'hri/manager_state')
        self.declare_parameter('topics.llm_query_pub', 'llm/query')
        self.declare_parameter('topics.tts_text_pub', 'tts/text')
        self.declare_parameter('topics.nav_command_pub', 'nav/command')
        self.declare_parameter('topics.audio_cue_pub', 'hri/audio_cue')

        self.greeting_text = self.get_parameter('greeting_text').value
        self.idle_timeout  = self.get_parameter('idle_timeout_sec').value
        self.wake_debounce_sec = self.get_parameter('wake_debounce_sec').value
        self.reprompt_max_count = int(self.get_parameter('reprompt_max_count').value)
        self.system_prompt_cooldown_sec = float(self.get_parameter('system_prompt_cooldown_sec').value)

        # State variables
        self.state: HRIState        = HRIState.IDLE
        self.state_enter_time: float = time.time()
        self.landmark_context: str  = ''
        self.tracking_state: dict   = {}
        self.last_wake_time: float  = 0.0
        self.activated: bool = False
        self.tts_retry_count: int = 0
        self.reprompt_count: int = 0
        self.last_system_prompt_time: dict[str, float] = {}

        wake_word_topic = self.get_parameter('topics.wake_word_sub').value
        stt_result_topic = self.get_parameter('topics.stt_result_sub').value
        tracking_state_topic = self.get_parameter('topics.tracking_state_sub').value
        gesture_command_topic = self.get_parameter('topics.gesture_command_sub').value
        expression_command_topic = self.get_parameter('topics.expression_command_sub').value
        landmark_context_topic = self.get_parameter('topics.landmark_context_sub').value
        tts_done_topic = self.get_parameter('topics.tts_done_sub').value
        tts_done_detail_topic = self.get_parameter('topics.tts_done_detail_sub').value
        follow_mode_service = self.get_parameter('services.follow_mode_service').value
        manager_state_topic = self.get_parameter('topics.manager_state_pub').value
        llm_query_topic = self.get_parameter('topics.llm_query_pub').value
        tts_text_topic = self.get_parameter('topics.tts_text_pub').value
        nav_command_topic = self.get_parameter('topics.nav_command_pub').value
        audio_cue_topic = self.get_parameter('topics.audio_cue_pub').value

        # Subscribers
        self.create_subscription(
            Bool, wake_word_topic, self._on_wake_word, 10)
        self.create_subscription(
            String, stt_result_topic, self._on_stt_result, 10)
        self.create_subscription(
            String, tracking_state_topic, self._on_tracking_state, 10)
        self.create_subscription(
            String, gesture_command_topic, self._on_gesture_command, 10)
        self.create_subscription(
            String, expression_command_topic, self._on_expression_command, 10)
        self.create_subscription(
            String, landmark_context_topic, self._on_landmark_context, 10)
        self.create_subscription(
            Bool, tts_done_topic, self._on_tts_done_legacy, 10)
        self.create_subscription(
            String, tts_done_detail_topic, self._on_tts_done_detail, 10)

        # Publishers
        self.manager_state_pub = self.create_publisher(String, manager_state_topic, 10)
        self.llm_query_pub = self.create_publisher(String, llm_query_topic, 10)
        self.tts_pub = self.create_publisher(String, tts_text_topic, 10)
        self.nav_command_pub = self.create_publisher(String, nav_command_topic, 10)
        self.audio_cue_pub = self.create_publisher(String, audio_cue_topic, 10)
        self.follow_mode_client = self.create_client(SetBool, follow_mode_service)

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
        WAVE gesture also routes here via stt/wake_word_detected.
        """
        if not msg.data:
            return
        now = time.time()
        elapsed = now - self.last_wake_time
        if elapsed < self.wake_debounce_sec:
            self.get_logger().debug(
                f'Wake word ignored — debounced ({elapsed:.2f}s < {self.wake_debounce_sec:.2f}s)'
            )
            return
        self.last_wake_time = now

        if self.state == HRIState.IDLE:
            self.get_logger().info('Wake word detected — starting HRI session')
            self.activated = True
            self.reprompt_count = 0
            self._transition(HRIState.LISTENING, reason='wake_word_detected')
            self._emit_wake_ack()
        else:
            self.get_logger().debug(
                f'Wake word ignored — already in state {self.state}'
            )

    def _on_stt_result(self, msg: String):
        """STT transcription/event received — forward valid text to LLM."""
        if self.state != HRIState.LISTENING:
            self.get_logger().debug('STT result ignored — not in LISTENING state')
            return

        try:
            data = json.loads(msg.data)
            user_text = str(data.get('text', '')).strip()
            event = str(data.get('event', STT_EVENTS['RESULT']))
            confidence = float(data.get('confidence', 0.0))
        except (json.JSONDecodeError, AttributeError, TypeError, ValueError):
            user_text = msg.data.strip()
            event = STT_EVENTS['RESULT'] if user_text else STT_EVENTS['EMPTY_OR_LOW_CONF']
            confidence = 0.0

        if event == STT_EVENTS['EMPTY_OR_LOW_CONF'] or not user_text:
            self.get_logger().info(
                f'STT empty/low-confidence event received (conf={confidence:.2f})'
            )
            self._handle_reprompt_or_end()
            return

        self.get_logger().info(f'STT result: "{user_text}" (conf={confidence:.2f})')
        self._transition(HRIState.RESPONDING, reason='stt_result_received')
        self.tts_retry_count = 0
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
            self._transition(HRIState.IDLE, reason='navigation_target_lost')
            self._set_follow_mode(False)
            self._say_system('target_lost')

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
                self._transition(HRIState.IDLE, reason='guidance_complete')
                self._set_follow_mode(False)

    def _on_landmark_context(self, msg: String):
        self.landmark_context = msg.data

    def _on_tts_done_legacy(self, msg: Bool):
        """Legacy bool completion signal; used only as fallback compatibility path."""
        if msg.data:
            self.get_logger().debug('Received legacy tts/done bool (compatibility mode)')

    def _on_tts_done_detail(self, msg: String):
        """Handle rich TTS completion payload with success/error state."""
        try:
            payload = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError):
            self.get_logger().warn('Invalid tts/done_detail payload')
            return

        success = bool(payload.get('success', False))
        error = str(payload.get('error', '') or '')

        if success:
            self.tts_retry_count = 0
            if self.state == HRIState.RESPONDING:
                self.get_logger().info('TTS success — back to LISTENING')
                self._transition(HRIState.LISTENING, reason='tts_success_after_response')
            return

        self.get_logger().warn(f'TTS failed: {error}')
        self._play_audio_cue('wake_chime')

        if self.state == HRIState.RESPONDING:
            if self.tts_retry_count < 1:
                self.tts_retry_count += 1
                self._say_system('tts_error_retry')
            self._transition(HRIState.LISTENING, reason='tts_failure_recover')

    # State machine
    def _transition(self, new_state: HRIState, reason: str = 'unspecified'):
        self.get_logger().info(f'State: {self.state} → {new_state} (reason: {reason})')
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
                self._say_system('timeout_exit')
                self._transition(HRIState.IDLE, reason='listening_timeout')
                self._set_follow_mode(False)

    # Action helpers
    def _say(self, text: str):
        """Publish text directly to TTS node (bypasses LLM)."""
        msg = String()
        msg.data = text
        self.tts_pub.publish(msg)
        self.get_logger().info(f'TTS: "{text}"')

    def _say_system(self, prompt_key: str) -> bool:
        text = SYSTEM_PROMPTS.get(prompt_key)
        if not text:
            self.get_logger().warn(f'Unknown system prompt key: {prompt_key}')
            return False

        now = time.time()
        last_ts = self.last_system_prompt_time.get(prompt_key, 0.0)
        if (now - last_ts) < self.system_prompt_cooldown_sec:
            self.get_logger().info(
                f'System prompt suppressed by cooldown: {prompt_key} ({now - last_ts:.2f}s)'
            )
            return False

        self.last_system_prompt_time[prompt_key] = now
        self._say(text)
        return True

    def _handle_reprompt_or_end(self):
        if self.reprompt_count < self.reprompt_max_count:
            self.reprompt_count += 1
            self._say_system('reprompt_short')
            self.get_logger().info(
                f'Reprompt issued ({self.reprompt_count}/{self.reprompt_max_count})'
            )
            return

        self.get_logger().info('Reprompt limit reached — ending session')
        self._say_system('timeout_exit')
        self._transition(HRIState.IDLE, reason='reprompt_limit_reached')
        self._set_follow_mode(False)

    def _emit_wake_ack(self):
        """Emit wake acknowledgement after activation."""
        if not self.activated:
            return
        self._play_audio_cue('wake_chime')
        self.activated = False

    def _play_audio_cue(self, cue_name: str):
        msg = String()
        msg.data = cue_name
        self.audio_cue_pub.publish(msg)
        self.get_logger().info(f'Audio cue: "{cue_name}"')

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
        if not self.follow_mode_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().error('Follow mode service unavailable')
            return

        req = SetBool.Request()
        req.data = enable
        future = self.follow_mode_client.call_async(req)
        future.add_done_callback(
            lambda done: self._on_follow_mode_response(done, enable)
        )

    def _on_follow_mode_response(self, future, requested_enable: bool):
        try:
            res = future.result()
        except Exception as exc:
            self.get_logger().error(
                f'Follow mode {"ON" if requested_enable else "OFF"} failed: {exc}'
            )
            return

        level = self.get_logger().info if res.success else self.get_logger().warn
        level(
            f'Follow mode {"ON" if requested_enable else "OFF"} '
            f'{"succeeded" if res.success else "failed"}: {res.message}'
        )

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

#!/usr/bin/env python3
"""
Emotion Publisher Node
Converts HRI state machine state into robot emotion and publishes it.

Design: 2-layer separation
  Layer 1 (what): HRI state machine (IDLE / LISTENING / RESPONDING / NAVIGATING)
  Layer 2 (how):  Emotion (/dori/hri/emotion) — can be overridden externally

Subscribe topics:
  /dori/hri/manager_state   (String) - HRI state machine state
  /dori/hri/emotion_override (String) - optional external emotion override
                                        JSON: { "emotion": "EXCITED", "duration_sec": 5.0 }

Publish topics:
  /dori/hri/emotion         (String) - current robot emotion JSON
                                       { "emotion": str, "source": str, "timestamp": float }

Emotion types (extensible):
  CALM        - IDLE default: resting, slow blink
  ATTENTIVE   - LISTENING: ears perked, engaged
  THINKING    - RESPONDING: processing, loading
  HAPPY       - NAVIGATING: guiding with enthusiasm

  # Future emotions (add mapping in EMOTION_OVERRIDE_WHITELIST):
  EXCITED, CURIOUS, SURPRISED, CONFUSED, SAD, PROUD, WORRIED
"""

import json
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

# ── Default state → emotion mapping ─────────────────────────────────────────
# Extend this dict as the state machine grows
STATE_TO_EMOTION: dict[str, str] = {
    'IDLE':       'CALM',
    'LISTENING':  'ATTENTIVE',
    'RESPONDING': 'THINKING',
    'NAVIGATING': 'HAPPY',
}

DEFAULT_EMOTION = 'CALM'

# Whitelist of valid emotion values (extend when adding new expressions)
EMOTION_WHITELIST = {
    'CALM', 'ATTENTIVE', 'THINKING', 'HAPPY',
    # Future:
    'EXCITED', 'CURIOUS', 'SURPRISED', 'CONFUSED', 'SAD', 'PROUD', 'WORRIED',
}


class EmotionPublisherNode(Node):
    def __init__(self):
        super().__init__('emotion_publisher_node')

        # State
        self._hri_state: str = 'IDLE'
        self._override_emotion: str | None = None
        self._override_until: float = 0.0

        # Subscribers
        self.create_subscription(
            String, '/dori/hri/manager_state', self._on_manager_state, 10)
        self.create_subscription(
            String, '/dori/hri/emotion_override', self._on_emotion_override, 10)

        # Publisher
        self._emotion_pub = self.create_publisher(String, '/dori/hri/emotion', 10)

        # Publish at 2 Hz (face animation polling rate)
        self.create_timer(0.5, self._publish_emotion)

        self.get_logger().info('Emotion Publisher Node started')

    def _on_manager_state(self, msg: String):
        """Update internal HRI state from manager_state topic."""
        try:
            parsed = json.loads(msg.data)
            self._hri_state = parsed.get('state', 'IDLE')
        except (json.JSONDecodeError, AttributeError):
            self._hri_state = 'IDLE'

    def _on_emotion_override(self, msg: String):
        """
        Accept external emotion override.
        Expected JSON: { "emotion": "EXCITED", "duration_sec": 5.0 }
        duration_sec = 0 or omitted → permanent override until next state change
        """
        try:
            parsed = json.loads(msg.data)
            emotion = parsed.get('emotion', '').upper()
            if emotion not in EMOTION_WHITELIST:
                self.get_logger().warn(
                    f'Unknown emotion override: "{emotion}" — ignored. '
                    f'Valid: {sorted(EMOTION_WHITELIST)}'
                )
                return

            duration = float(parsed.get('duration_sec', 0.0))
            self._override_emotion = emotion
            self._override_until = time.time() + duration if duration > 0 else float('inf')
            self.get_logger().info(
                f'Emotion override: {emotion} '
                f'({"permanent" if duration <= 0 else f"{duration:.1f}s"})'
            )
        except (json.JSONDecodeError, ValueError, AttributeError) as e:
            self.get_logger().error(f'Failed to parse emotion_override: {e}')

    def _resolve_emotion(self) -> tuple[str, str]:
        """
        Resolve current emotion and its source.
        Returns (emotion, source) where source is 'override' or 'state'.
        Override expires automatically after duration.
        """
        now = time.time()

        if self._override_emotion and now < self._override_until:
            return self._override_emotion, 'override'

        # Override expired — clear it
        if self._override_emotion:
            self.get_logger().info(
                f'Emotion override "{self._override_emotion}" expired → '
                f'returning to state-driven emotion'
            )
            self._override_emotion = None
            self._override_until = 0.0

        emotion = STATE_TO_EMOTION.get(self._hri_state, DEFAULT_EMOTION)
        return emotion, 'state'

    def _publish_emotion(self):
        emotion, source = self._resolve_emotion()
        msg = String()
        msg.data = json.dumps({
            'emotion':   emotion,
            'source':    source,
            'hri_state': self._hri_state,
            'timestamp': time.time(),
        }, ensure_ascii=False)
        self._emotion_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = EmotionPublisherNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

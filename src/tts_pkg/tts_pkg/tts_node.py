#!/usr/bin/env python3
"""
Text-to-speech playback with speaking state management.

Engines (priority order):
  1. pyttsx3  - offline, fast, lower quality
  2. gTTS     - online (requires internet), better Korean quality
  NOTE: Consider replacing gTTS with Piper TTS for fully offline operation.

Subscribe topics:
  /dori/llm/response     (String) - response text from LLM node
  /dori/tts/text         (String) - direct TTS from HRI Manager (bypasses LLM)

Publish topics:
  /dori/tts/speaking     (Bool)   - True while speaking (STT mutes itself)
  /dori/tts/done         (Bool)   - True when playback finishes (HRI Manager transitions state)
"""

import os
import queue
import tempfile
import threading
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

try:
    import pyttsx3
    PYTTSX3_AVAILABLE = True
except ImportError:
    PYTTSX3_AVAILABLE = False

try:
    import sounddevice as sd
    import soundfile as sf
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False


class TTSNode(Node):
    def __init__(self):
        super().__init__('tts_node')

        # Parameters
        self.declare_parameter('tts_engine', 'gtts')   # 'gtts' or 'pyttsx3'
        self.declare_parameter('language', 'ko')
        self.declare_parameter('speech_rate', 150)
        self.declare_parameter('volume', 0.9)

        self.engine_name  = self.get_parameter('tts_engine').value
        self.language     = self.get_parameter('language').value
        self.speech_rate  = self.get_parameter('speech_rate').value
        self.volume       = self.get_parameter('volume').value

        # State
        self.is_speaking   = False
        self.text_queue    = queue.Queue()
        self.speak_lock    = threading.Lock()

        # Publishers
        self.speaking_pub = self.create_publisher(Bool, '/dori/tts/speaking', 10)
        self.done_pub     = self.create_publisher(Bool, '/dori/tts/done', 10)

        # Subscribers
        # LLM response (main path)
        self.create_subscription(
            String, '/dori/llm/response', self._on_text, 10)
        # Direct TTS from HRI Manager (greetings, system messages)
        self.create_subscription(
            String, '/dori/tts/text', self._on_text, 10)

        # Engine init
        self._init_engine()

        # TTS worker thread
        self._worker = threading.Thread(
            target=self._process_queue, daemon=True)
        self._worker.start()

        self.get_logger().info(f'TTS Node started (engine: {self.engine_name})')

    # Engine initialization
    def _init_engine(self):
        if self.engine_name == 'pyttsx3':
            if not PYTTSX3_AVAILABLE:
                self.get_logger().warn('pyttsx3 not available — falling back to gTTS')
                self.engine_name = 'gtts'
            else:
                try:
                    self._pyttsx3 = pyttsx3.init()
                    self._pyttsx3.setProperty('rate', self.speech_rate)
                    self._pyttsx3.setProperty('volume', self.volume)
                    # Use Korean voice if available
                    for voice in self._pyttsx3.getProperty('voices'):
                        if 'korean' in voice.name.lower() or 'ko' in voice.id.lower():
                            self._pyttsx3.setProperty('voice', voice.id)
                            break
                    self.get_logger().info('pyttsx3 engine ready')
                    return
                except Exception as e:
                    self.get_logger().error(f'pyttsx3 init failed: {e}')
                    self.engine_name = 'gtts'

        if self.engine_name == 'gtts':
            if not GTTS_AVAILABLE:
                self.get_logger().error(
                    'gTTS not available. Install with: pip install gtts\n'
                    'NOTE: gTTS requires internet. Consider Piper TTS for offline use.'
                )
                raise RuntimeError('No TTS engine available')
            self.get_logger().info(
                'gTTS engine ready (requires internet connection)'
            )

    # Callbacks
    def _on_text(self, msg: String):
        text = msg.data.strip()
        if not text:
            return
        self.get_logger().info(f'Queued: "{text[:50]}"')
        self.text_queue.put(text)

    # Worker thread
    def _process_queue(self):
        while True:
            try:
                text = self.text_queue.get(timeout=0.1)
                self._speak(text)
            except queue.Empty:
                continue
            except Exception as e:
                self.get_logger().error(f'TTS worker error: {e}')

    def _speak(self, text: str):
        with self.speak_lock:
            try:
                self.is_speaking = True
                self._pub_speaking(True)
                self.get_logger().info(f'Speaking: "{text[:60]}"')

                if self.engine_name == 'pyttsx3':
                    self._speak_pyttsx3(text)
                elif self.engine_name == 'gtts':
                    self._speak_gtts(text)

                time.sleep(0.3)  # brief pause after speech
            except Exception as e:
                self.get_logger().error(f'Speech error: {e}')
            finally:
                self.is_speaking = False
                self._pub_speaking(False)
                self._pub_done()
                self.get_logger().info('Speech complete')

    def _speak_pyttsx3(self, text: str):
        self._pyttsx3.say(text)
        self._pyttsx3.runAndWait()

    def _speak_gtts(self, text: str):
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as fp:
            tmp = fp.name
        try:
            gTTS(text=text, lang=self.language, slow=False).save(tmp)
            if AUDIO_AVAILABLE:
                data, sr = sf.read(tmp)
                sd.play(data, sr)
                sd.wait()
            else:
                # Fallback: system audio command
                os.system(
                    f'mpg123 -q {tmp} 2>/dev/null || '
                    f'ffplay -nodisp -autoexit {tmp} 2>/dev/null'
                )
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # Publisher helpers
    def _pub_speaking(self, value: bool):
        msg = Bool()
        msg.data = value
        self.speaking_pub.publish(msg)

    def _pub_done(self):
        msg = Bool()
        msg.data = True
        self.done_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = TTSNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Text-to-speech playback with speaking state management.

Engines (priority order):
  1. pyttsx3  - offline, fast, lower quality
  2. gTTS     - online (requires internet), better Korean quality
  NOTE: Consider replacing gTTS with Piper TTS for fully offline operation.

Subscribe topics:
  llm/response     (String) - response text from LLM node
  tts/text         (String) - direct TTS from HRI Manager (bypasses LLM)
  hri/audio_cue    (String) - short non-blocking SFX cue (e.g. wake_chime)

Publish topics:
  tts/speaking      (Bool)   - True while speaking (STT mutes itself)
  tts/done          (Bool)   - Legacy completion signal (backward compatibility)
  tts/done_detail   (String) - JSON completion payload ({success,error,text,timestamp})
"""

import os
import queue
import tempfile
import threading
import time
from pathlib import Path

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
import json

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
        self.declare_parameter('topics.speaking_pub', 'tts/speaking')
        self.declare_parameter('topics.done_pub', 'tts/done')
        self.declare_parameter('topics.done_detail_pub', 'tts/done_detail')
        self.declare_parameter('topics.llm_response_sub', 'llm/response')
        self.declare_parameter('topics.tts_text_sub', 'tts/text')
        self.declare_parameter('topics.audio_cue_sub', 'hri/audio_cue')
        self.declare_parameter('sfx.base_path', '')
        self.declare_parameter('playback_mode', 'local_and_publish')
        self.declare_parameter('topics.audio_event_pub', 'tts/audio_event')

        self.engine_name = self.get_parameter('tts_engine').value
        self.language = self.get_parameter('language').value
        self.speech_rate = self.get_parameter('speech_rate').value
        self.volume = self.get_parameter('volume').value

        # State
        self.is_speaking = False
        self.text_queue = queue.Queue()
        self.sfx_queue = queue.Queue()
        self.speak_lock = threading.Lock()
        self.sfx_base_path = self._resolve_sfx_base_path(
            self.get_parameter('sfx.base_path').value
        )
        self.playback_mode = self.get_parameter('playback_mode').value
        valid_playback_modes = {'local_only', 'publish_only', 'local_and_publish'}
        if self.playback_mode not in valid_playback_modes:
            self.get_logger().warn(
                f'Invalid playback_mode: {self.playback_mode} — fallback to local_and_publish'
            )
            self.playback_mode = 'local_and_publish'

        speaking_topic = self.get_parameter('topics.speaking_pub').value
        done_topic = self.get_parameter('topics.done_pub').value
        done_detail_topic = self.get_parameter('topics.done_detail_pub').value
        llm_response_topic = self.get_parameter('topics.llm_response_sub').value
        tts_text_topic = self.get_parameter('topics.tts_text_sub').value
        audio_cue_topic = self.get_parameter('topics.audio_cue_sub').value
        audio_event_topic = self.get_parameter('topics.audio_event_pub').value

        # Publishers
        self.speaking_pub = self.create_publisher(Bool, speaking_topic, 10)
        self.done_pub = self.create_publisher(Bool, done_topic, 10)
        self.done_detail_pub = self.create_publisher(String, done_detail_topic, 10)
        self.audio_event_pub = self.create_publisher(String, audio_event_topic, 10)

        # Subscribers
        self.create_subscription(String, llm_response_topic, self._on_text, 10)
        self.create_subscription(String, tts_text_topic, self._on_text, 10)
        self.create_subscription(String, audio_cue_topic, self._on_audio_cue, 10)

        self._init_engine()

        self._worker = threading.Thread(target=self._process_queue, daemon=True)
        self._worker.start()

        # Separate SFX worker: decoupled from TTS queue to minimize latency/blocking.
        self._sfx_worker = threading.Thread(target=self._process_sfx_queue, daemon=True)
        self._sfx_worker.start()

        self.get_logger().info(f'TTS Node started (engine: {self.engine_name})')
        self.get_logger().info(f'SFX base path: {self.sfx_base_path}')
        self.get_logger().info(f'Playback mode: {self.playback_mode}')

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
            self.get_logger().info('gTTS engine ready (requires internet connection)')

    def _on_text(self, msg: String):
        text = msg.data.strip()
        if not text:
            return
        self.get_logger().info(f'Queued: "{text[:50]}"')
        self.text_queue.put(text)

    def _on_audio_cue(self, msg: String):
        cue_name = msg.data.strip()
        if cue_name:
            self.sfx_queue.put(cue_name)

    def _process_queue(self):
        while True:
            try:
                text = self.text_queue.get(timeout=0.1)
                self._speak(text)
            except queue.Empty:
                continue
            except Exception as e:
                self.get_logger().error(f'TTS worker error: {e}')

    def _process_sfx_queue(self):
        while True:
            try:
                cue_name = self.sfx_queue.get(timeout=0.1)
                self._play_audio_cue(cue_name)
            except queue.Empty:
                continue
            except Exception as e:
                self.get_logger().error(f'SFX worker error: {e}')

    def _speak(self, text: str):
        with self.speak_lock:
            success = False
            error = ''
            try:
                self.is_speaking = True
                self._pub_speaking(True)
                self.get_logger().info(f'Speaking: "{text[:60]}"')

                self._publish_audio_event('tts_text', {'text': text, 'engine': self.engine_name})

                if self.engine_name == 'pyttsx3':
                    self._speak_pyttsx3(text)
                elif self.engine_name == 'gtts':
                    self._speak_gtts(text)

                time.sleep(0.3)
                success = True
            except Exception as e:
                error = str(e)
                self.get_logger().error(f'Speech error: {e}')
            finally:
                self.is_speaking = False
                self._pub_speaking(False)
                self._pub_done(success=success, error=error, text=text)
                self.get_logger().info('Speech complete')

    def _speak_pyttsx3(self, text: str):
        if self.playback_mode == 'publish_only':
            self.get_logger().info('publish_only mode: skip pyttsx3 local playback')
            return
        self._pyttsx3.say(text)
        self._pyttsx3.runAndWait()

    def _speak_gtts(self, text: str):
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as fp:
            tmp = fp.name
        try:
            gTTS(text=text, lang=self.language, slow=False).save(tmp)
            if self.playback_mode == 'publish_only':
                self.get_logger().info('publish_only mode: skip gTTS local playback')
                return

            if AUDIO_AVAILABLE:
                data, sr = sf.read(tmp)
                sd.play(data, sr)
                sd.wait()
            else:
                os.system(
                    f'mpg123 -q {tmp} 2>/dev/null || '
                    f'ffplay -nodisp -autoexit {tmp} 2>/dev/null'
                )
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def _resolve_sfx_base_path(self, configured_path: str) -> str:
        if configured_path:
            return configured_path

        env_path = os.environ.get('DORI_AUDIO_ASSETS', '').strip()
        if env_path:
            return env_path

        try:
            pkg_share = get_package_share_directory('tts_pkg')
            return str(Path(pkg_share) / 'assets' / 'audio')
        except Exception:
            return ''

    def _cue_file_path(self, cue_name: str) -> Path:
        return Path(self.sfx_base_path) / f'{cue_name}.wav'

    def _play_audio_cue(self, cue_name: str):
        # Policy: short cues do NOT toggle tts/speaking.
        if cue_name != 'wake_chime':
            self.get_logger().warn(f'Unknown audio cue: "{cue_name}"')
            return

        self._publish_audio_event('audio_cue', {'cue_name': cue_name})

        cue_path = self._cue_file_path(cue_name)
        if not self.sfx_base_path or not cue_path.exists():
            self.get_logger().warn(
                f'Audio cue missing ({cue_name}): {cue_path} — fallback to silence'
            )
            return

        try:
            if self.playback_mode == 'publish_only':
                self.get_logger().info('publish_only mode: skip local audio cue playback')
                return

            if AUDIO_AVAILABLE:
                data, sr = sf.read(str(cue_path))
                sd.play(data, sr)
                sd.wait()
            else:
                os.system(
                    f'aplay -q "{cue_path}" 2>/dev/null || '
                    f'ffplay -nodisp -autoexit "{cue_path}" 2>/dev/null'
                )
        except Exception as e:
            self.get_logger().warn(
                f'Audio cue playback failed ({cue_name}): {e} — fallback to silence'
            )


    def _publish_audio_event(self, event_type: str, payload: dict):
        if self.playback_mode == 'local_only':
            return

        msg = String()
        msg.data = json.dumps({
            'event_type': event_type,
            'playback_mode': self.playback_mode,
            'timestamp': time.time(),
            **payload,
        }, ensure_ascii=False)
        self.audio_event_pub.publish(msg)

    def _pub_speaking(self, value: bool):
        msg = Bool()
        msg.data = value
        self.speaking_pub.publish(msg)

    def _pub_done(self, success: bool = True, error: str = '', text: str = ''):
        legacy_msg = Bool()
        legacy_msg.data = True
        self.done_pub.publish(legacy_msg)

        detail_msg = String()
        detail_msg.data = json.dumps({
            'success': success,
            'error': error,
            'text': text[:120],
            'timestamp': time.time(),
        }, ensure_ascii=False)
        self.done_detail_pub.publish(detail_msg)


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

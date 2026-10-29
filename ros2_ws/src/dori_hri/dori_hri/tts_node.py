#!/usr/bin/env python3
"""
Text-to-speech playback with speaking state management using Google Cloud TTS and fallback to gTTS.

Engines (priority order):
  1. Google Cloud TTS (Neural2 -> WaveNet -> Standard)
  2. gTTS     - online (requires internet), fallback when Cloud TTS limits are reached

Actions:
  tts/speak        (Speak)  - Action server for speech synthesis and playback

Subscribe topics:
  llm/response     (String) - response text from LLM node
  tts/text         (String) - direct TTS from HRI Manager (bypasses LLM)
  tts/text         (String) - Optional direct TTS injection (for web dashboard/testing)
  hri/audio_cue    (String) - short non-blocking SFX cue (e.g. wake_chime)

Publish topics:
  tts/speaking      (Bool)   - True while speaking (STT mutes itself)
  tts/done          (Bool)   - Legacy completion signal (backward compatibility)
  tts/done_detail   (String) - JSON completion payload ({success,error,text,timestamp})
  tts/audio_event   (String) - Audio event notifications
"""

import os
import queue
import tempfile
import threading
import time
import subprocess
from pathlib import Path
from datetime import datetime
import json

import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor

from std_msgs.msg import Bool, String

from dori_msgs.action import Speak

from dori_core.db_manager import TTSDatabaseManager

try:
    from gtts import gTTS

    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

try:
    from google.cloud import texttospeech
    from google.api_core.exceptions import ResourceExhausted

    GCP_TTS_AVAILABLE = True
except ImportError:
    GCP_TTS_AVAILABLE = False


class TTSNode(Node):
    def __init__(self):
        super().__init__("tts_node")

        # Parameters
        self.declare_parameter("language", "ko")
        self.declare_parameter("tts_engine", "gtts")
        self.declare_parameter("speech_rate", 150)
        self.declare_parameter("volume", 0.9)
        self.declare_parameter("topics.speaking_pub", "tts/speaking")
        self.declare_parameter("topics.done_pub", "tts/done")
        self.declare_parameter("topics.done_detail_pub", "tts/done_detail")
        self.declare_parameter("topics.audio_cue_sub", "hri/audio_cue")
        self.declare_parameter("topics.tts_text_sub", "tts/text")
        self.declare_parameter("action_name", "tts/speak")
        self.declare_parameter("sfx.base_path", "")
        self.declare_parameter("playback_mode", "local_and_publish")
        self.declare_parameter("topics.audio_event_pub", "tts/audio_event")

        # New parameters for Google Cloud TTS limits
        self.declare_parameter("gcp_limits.neural2", 30000)
        self.declare_parameter("gcp_limits.wavenet", 30000)
        self.declare_parameter("gcp_limits.standard", 120000)

        self.language = self.get_parameter("language").value

        self.limits = {
            "neural2": self.get_parameter("gcp_limits.neural2").value,
            "wavenet": self.get_parameter("gcp_limits.wavenet").value,
            "standard": self.get_parameter("gcp_limits.standard").value,
        }

        # State
        self.is_speaking = False
        self._speech_lock = threading.Lock()
        self._busy = False
        self.sfx_queue = queue.Queue()
        self.sfx_base_path = self._resolve_sfx_base_path(
            self.get_parameter("sfx.base_path").value
        )
        self.playback_mode = self.get_parameter("playback_mode").value
        valid_playback_modes = {"local_only", "publish_only", "local_and_publish"}
        if self.playback_mode not in valid_playback_modes:
            self.get_logger().warn(
                f"Invalid playback_mode: {self.playback_mode} — fallback to local_and_publish"
            )
            self.playback_mode = "local_and_publish"

        speaking_topic = self.get_parameter("topics.speaking_pub").value
        done_topic = self.get_parameter("topics.done_pub").value
        done_detail_topic = self.get_parameter("topics.done_detail_pub").value
        audio_cue_topic = self.get_parameter("topics.audio_cue_sub").value
        tts_text_topic = self.get_parameter("topics.tts_text_sub").value
        action_name = self.get_parameter("action_name").value
        audio_event_topic = self.get_parameter("topics.audio_event_pub").value

        # Publishers
        self.speaking_pub = self.create_publisher(Bool, speaking_topic, 10)
        self.done_pub = self.create_publisher(Bool, done_topic, 10)
        self.done_detail_pub = self.create_publisher(String, done_detail_topic, 10)
        self.audio_event_pub = self.create_publisher(String, audio_event_topic, 10)

        # Callback Group
        self.callback_group = ReentrantCallbackGroup()

        # Subscribers (SFX 전용)
        # Subscribers
        self.create_subscription(
            String,
            audio_cue_topic,
            self._on_audio_cue,
            10,
            callback_group=self.callback_group,
        )
        if tts_text_topic:
            self.create_subscription(
                String,
                tts_text_topic,
                self._on_tts_text,
                10,
                callback_group=self.callback_group,
            )

        # Action Server 초기화
        self._action_server = ActionServer(
            self,
            Speak,
            action_name,
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.callback_group,
        )

        self._init_engine()

        # Separate SFX worker
        self._sfx_worker = threading.Thread(target=self._process_sfx_queue, daemon=True)
        self._sfx_worker.start()

        self.get_logger().info("TTS Action Node started")

    def _init_engine(self):
        self.gcp_client = None
        if self.playback_mode == "publish_only":
            return
        if not GTTS_AVAILABLE:
            raise RuntimeError("gTTS engine required for fallback")

        if GCP_TTS_AVAILABLE and self.get_parameter("tts_engine").value in (
            "gcp",
            "auto",
        ):
            try:
                self.gcp_client = texttospeech.TextToSpeechClient()
                self.db = TTSDatabaseManager("tts_usage.db")  # DB 매니저 연동
                self.get_logger().info("Google Cloud TTS engine & DB ready")
            except Exception as e:
                self.get_logger().error(f"Failed to init GCP TTS client: {e}")
                self.gcp_client = None
        else:
            self.gcp_client = None

    # --- Action Server Callbacks ---
    def goal_callback(self, goal_request):
        with self._speech_lock:
            if self._busy or not 0 < len(goal_request.text.strip()) <= 4000:
                return GoalResponse.REJECT
            self._busy = True
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        self.get_logger().warn("Goal cancel requested!")
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle):
        text = goal_handle.request.text
        result = Speak.Result()
        feedback = Speak.Feedback()

        self.is_speaking = True
        self._pub_speaking(True)
        used_engine = "gtts"
        audio_file_path = None

        feedback.status = "Synthesizing audio..."
        goal_handle.publish_feedback(feedback)

        try:
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                result.success = False
                result.message = "Canceled before synthesis"
                self._finish_speaking(success=False, text=text)
                return result
            # 1. 텍스트 합성 (파일 경로만 반환받음)
            if self.playback_mode == "publish_only":
                used_engine = "browser"
            elif self.gcp_client:
                audio_file_path, used_engine = self._speak_with_waterfall(text)
            else:
                audio_file_path = self._synthesize_gtts(text)

            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                result.success = False
                result.message = "Canceled during synthesis"
                self._cleanup_temp_file(audio_file_path)
                self._finish_speaking(success=False, text=text)
                return result
            self._publish_audio_event("tts_text", {"text": text, "engine": used_engine})

            # 2. 재생 처리 (취소 가능하도록 subprocess 적용)
            if self.playback_mode != "publish_only" and audio_file_path:
                feedback.status = "Playing audio..."
                goal_handle.publish_feedback(feedback)

                play_process = subprocess.Popen(
                    ["mpg123", "-q", audio_file_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

                deadline = time.monotonic() + 60.0
                while play_process.poll() is None:
                    if time.monotonic() > deadline or not rclpy.ok():
                        play_process.kill()
                        play_process.wait(timeout=2)
                        raise RuntimeError("Audio playback timeout/shutdown")
                    # 재생 중 취소 요청 감지
                    if goal_handle.is_cancel_requested:
                        play_process.terminate()
                        try:
                            play_process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            play_process.kill()
                            play_process.wait(timeout=2)

                        goal_handle.canceled()
                        result.success = False
                        result.message = "Canceled during playback"
                        self._cleanup_temp_file(audio_file_path)
                        self._finish_speaking(success=False, text=text)
                        return result

                    time.sleep(0.1)

                if play_process.returncode != 0:
                    raise RuntimeError(f"Audio player exited {play_process.returncode}")

            # 정상 종료
            goal_handle.succeed()
            result.success = True
            result.message = "Playback finished"
            self._cleanup_temp_file(audio_file_path)
            self._finish_speaking(success=True, text=text)
            return result

        except Exception as e:
            self.get_logger().error(f"Execution error: {e}")
            goal_handle.abort()
            result.success = False
            result.message = str(e)
            self._cleanup_temp_file(audio_file_path)
            self._finish_speaking(success=False, error=str(e), text=text)
            return result

    def _finish_speaking(self, success=True, error="", text=""):
        with self._speech_lock:
            self._busy = False
            self.is_speaking = False
        self._pub_speaking(False)
        self._pub_done(success=success, error=error, text=text)

    def _on_tts_text(self, msg: String):
        text = msg.data.strip()
        if not text:
            return
        self.get_logger().info(f'Received direct TTS text: "{text[:50]}"')
        threading.Thread(
            target=self._play_direct_text, args=(text,), daemon=True
        ).start()

    def _play_direct_text(self, text: str):
        with self._speech_lock:
            if self._busy:
                self.get_logger().warning("TTS busy; direct request ignored")
                return
            self._busy = True

        self.is_speaking = True
        self._pub_speaking(True)
        used_engine = "gtts"
        audio_file_path = None

        try:
            if self.playback_mode == "publish_only":
                used_engine = "browser"
            elif self.gcp_client:
                audio_file_path, used_engine = self._speak_with_waterfall(text)
            else:
                audio_file_path = self._synthesize_gtts(text)

            self._publish_audio_event("tts_text", {"text": text, "engine": used_engine})

            if self.playback_mode != "publish_only" and audio_file_path:
                subprocess.run(
                    ["mpg123", "-q", audio_file_path],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    check=True,
                )

            self._cleanup_temp_file(audio_file_path)
            self._finish_speaking(success=True, text=text)
        except Exception as e:
            self.get_logger().error(f"Direct playback error: {e}")
            self._cleanup_temp_file(audio_file_path)
            self._finish_speaking(success=False, error=str(e), text=text)

    def _cleanup_temp_file(self, file_path):
        if file_path and os.path.exists(file_path):
            try:
                os.unlink(file_path)
            except OSError:
                pass

    # --- Synthesis Logic (재생 로직 분리) ---
    def _speak_with_waterfall(self, text: str):
        char_count = len(text)
        today = datetime.now().strftime("%Y-%m-%d")
        current_usage = self.db.get_usage(today)  # DB 읽기

        try:
            if current_usage["neural2"] + char_count <= self.limits["neural2"]:
                path = self._synthesize_gcp(text, "ko-KR-Neural2-A")
                self.db.add_usage(today, "neural2", char_count)  # DB 쓰기
                return path, "neural2"

            elif current_usage["wavenet"] + char_count <= self.limits["wavenet"]:
                path = self._synthesize_gcp(text, "ko-KR-Wavenet-A")
                self.db.add_usage(today, "wavenet", char_count)
                return path, "wavenet"

            elif current_usage["standard"] + char_count <= self.limits["standard"]:
                path = self._synthesize_gcp(text, "ko-KR-Standard-A")
                self.db.add_usage(today, "standard", char_count)
                return path, "standard"

            else:
                self.get_logger().warn("GCP Limits reached. Fallback to gTTS")
                return self._synthesize_gtts(text), "gtts"

        except Exception as e:
            self.get_logger().error(f"GCP Fallback triggered: {e}")
            return self._synthesize_gtts(text), "gtts"

    def _synthesize_gcp(self, text: str, voice_name: str) -> str:
        synthesis_input = texttospeech.SynthesisInput(text=text)
        voice = texttospeech.VoiceSelectionParams(
            language_code="ko-KR", name=voice_name
        )
        audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.MP3
        )

        response = self.gcp_client.synthesize_speech(
            input=synthesis_input, voice=voice, audio_config=audio_config, timeout=10
        )

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fp:
            fp.write(response.audio_content)
            return fp.name

    def _synthesize_gtts(self, text: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as fp:
            tmp = fp.name
        try:
            gTTS(text=text, lang=self.language, slow=False, timeout=(3, 10)).save(tmp)
            return tmp
        except Exception:
            self._cleanup_temp_file(tmp)
            raise

    # --- SFX & Publishers 유지 ---
    def _on_audio_cue(self, msg: String):
        cue_name = msg.data.strip()
        if cue_name:
            self.sfx_queue.put(cue_name)

    def _process_sfx_queue(self):
        while True:
            try:
                cue_name = self.sfx_queue.get(timeout=0.1)
                self._play_audio_cue(cue_name)
            except queue.Empty:
                continue

    def _play_audio_cue(self, cue_name: str):
        if cue_name != "wake_chime":
            return

        self._publish_audio_event("audio_cue", {"cue_name": cue_name})
        cue_path = self._cue_file_path(cue_name)

        if not self.sfx_base_path or not cue_path.exists():
            return

        if self.playback_mode != "publish_only":
            subprocess.run(
                ["mpg123", "-q", str(cue_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
                check=False,
            )

    def _resolve_sfx_base_path(self, configured_path: str) -> str:
        if configured_path:
            return configured_path
        env_path = os.environ.get("DORI_AUDIO_ASSETS", "").strip()
        if env_path:
            return env_path
        try:
            pkg_share = get_package_share_directory("dori_hri")
            return str(Path(pkg_share) / "assets" / "audio")
        except Exception:
            return ""

    def _cue_file_path(self, cue_name: str) -> Path:
        return Path(self.sfx_base_path) / f"{cue_name}.wav"

    def _publish_audio_event(self, event_type: str, payload: dict):
        # Always publish output metadata; browsers suppress local_only playback.
        msg = String()
        msg.data = json.dumps(
            {
                "event_type": event_type,
                "playback_mode": self.playback_mode,
                "timestamp": time.time(),
                **payload,
            },
            ensure_ascii=False,
        )
        self.audio_event_pub.publish(msg)

    def _pub_speaking(self, value: bool):
        msg = Bool()
        msg.data = value
        self.speaking_pub.publish(msg)

    def _pub_done(self, success: bool = True, error: str = "", text: str = ""):
        legacy_msg = Bool()
        legacy_msg.data = True
        self.done_pub.publish(legacy_msg)
        detail_msg = String()
        detail_msg.data = json.dumps(
            {
                "success": success,
                "error": error,
                "text": text[:120],
                "timestamp": time.time(),
            },
            ensure_ascii=False,
        )
        self.done_detail_pub.publish(detail_msg)


def main(args=None):
    rclpy.init(args=args)
    node = TTSNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

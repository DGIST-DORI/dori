#!/usr/bin/env python3
"""
Wake word detection + speech transcription pipeline.

Pipeline:
  Microphone → openWakeWord (wake word) → Whisper (transcription) → publish

Publish topics:
  stt/wake_word_detected   (Bool)   - rising edge on wake word detection
  stt/result               (String) - JSON: {text, language, confidence, timestamp}

Subscribe topics:
  tts/speaking             (Bool)   - mute microphone while robot is speaking
"""

import json
import os
import queue
import struct
import threading
import time
import wave
from io import BytesIO
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger

try:
    import sounddevice as sd
except (ImportError, OSError):
    sd = None

try:
    import openwakeword
    from openwakeword.model import Model

    OPENWAKEWORD_AVAILABLE = True
except ImportError:
    OPENWAKEWORD_AVAILABLE = False

try:
    from faster_whisper import WhisperModel

    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False


SAMPLE_RATE = 16000
FRAME_LENGTH = 1280  # openWakeWord: 1280
CHANNELS = 1

MAX_BUFFER_SEC = 120.0
MIN_SPEECH_SEC = 0.5


class STTState:
    IDLE = "IDLE"  # waiting for wake word
    LISTENING = "LISTENING"  # recording speech after wake word


class STTNode(Node):
    def __init__(self):
        super().__init__("stt_node")

        # Parameters
        self.declare_parameter("wake_word", "hey_mycroft")
        self.declare_parameter("wake_word_threshold", 0.5)
        self.declare_parameter("whisper_model", "small")
        self.declare_parameter("whisper_device", "cpu")
        self.declare_parameter("vad_threshold", 0.5)
        self.declare_parameter("silence_duration", 1.5)
        self.declare_parameter("topics.wake_word_pub", "stt/wake_word_detected")
        self.declare_parameter("topics.result_pub", "stt/result")
        self.declare_parameter("min_confidence", 0.55)
        # Phone turns cannot dispatch motion and short greetings score lower.
        self.declare_parameter("visitor_min_confidence", 0.4)
        self.declare_parameter("topics.tts_speaking_sub", "tts/speaking")
        self.declare_parameter("topics.audio_input_sub", "stt/audio_input")
        self.declare_parameter("audio_input_mode", "microphone")

        wake_word = self.get_parameter("wake_word").value
        wake_word_models = [w.strip() for w in wake_word.split(",")]
        self.wake_word_threshold = self.get_parameter("wake_word_threshold").value
        model_size = self.get_parameter("whisper_model").value
        device = self.get_parameter("whisper_device").value
        self.vad_threshold = self.get_parameter("vad_threshold").value
        self.vad_silence_sec = self.get_parameter("silence_duration").value
        self.min_confidence = float(self.get_parameter("min_confidence").value)
        self.visitor_min_confidence = float(self.get_parameter("visitor_min_confidence").value)

        wake_word_topic = self.get_parameter("topics.wake_word_pub").value
        result_topic = self.get_parameter("topics.result_pub").value
        tts_speaking_topic = self.get_parameter("topics.tts_speaking_sub").value
        audio_input_topic = self.get_parameter("topics.audio_input_sub").value
        self.audio_input_mode = self.get_parameter("audio_input_mode").value

        # Publishers
        self.wake_word_pub = self.create_publisher(Bool, wake_word_topic, 10)
        self.result_pub = self.create_publisher(String, result_topic, 10)
        self.visitor_result_pub = self.create_publisher(String, "stt/visitor_result", 10)

        # Subscribers
        self.create_subscription(Bool, tts_speaking_topic, self._on_tts_speaking, 10)
        self.create_subscription(
            String, audio_input_topic, self._on_audio_input_topic, 10
        )

        # State
        self.state = STTState.IDLE
        self.dori_speaking = False
        self.mute_until = 0.0  # 잔향 방지를 위한 음소거 유예 시간
        self.audio_queue = queue.Queue(maxsize=160)
        self.buffer = []
        self.listen_start_time: float | None = None
        self.last_voice_time: float | None = None
        self.state_lock = threading.Lock()

        if self.audio_input_mode not in ("microphone", "topic"):
            raise ValueError("audio_input_mode must be microphone or topic")
        self.oww_model = None
        if self.audio_input_mode == "microphone":
            if sd is None:
                raise RuntimeError("Microphone requires sounddevice and libportaudio2")
            if not OPENWAKEWORD_AVAILABLE:
                raise RuntimeError(
                    "Install openwakeword and prepare models before microphone startup"
                )
            self.oww_model = Model(
                wakeword_models=wake_word_models, inference_framework="onnx"
            )
        # Energy VAD has no network dependency; Whisper handles transcription.
        self.vad_model = None

        # Whisper
        if not WHISPER_AVAILABLE:
            raise RuntimeError(
                "faster-whisper is required; follow DORI-AMM task 20-20 model preparation"
            )

        try:
            self.get_logger().info(f"Loading Whisper ({model_size})...")
            self.whisper = WhisperModel(
                model_size,
                device=device,
                compute_type="int8" if device == "cpu" else "float16",
            )
            self.get_logger().info("Whisper ready")
        except Exception as e:
            raise RuntimeError(f"Whisper init failed: {e}") from e

        # Audio stream
        if self.audio_input_mode == "microphone":
            try:
                self.stream = sd.RawInputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=FRAME_LENGTH,
                    dtype="int16",
                    channels=CHANNELS,
                    callback=self._audio_callback,
                )
                self.stream.start()
                self.get_logger().info("Audio stream started")
            except Exception as e:
                raise RuntimeError(f"Audio stream failed: {e}") from e
        else:
            self.get_logger().info(
                f'Audio input mode is "{self.audio_input_mode}" - microphone capture disabled'
            )

        # Single-threaded callback ordering makes reset an inference drain barrier.
        self._input_epoch = time.time()
        self.create_service(Trigger, "stt/reset", self._reset_input)

        # Processing timer (20 Hz)
        self.create_timer(0.05, self._process_audio)

        self.get_logger().info("STT Node ready")

    def _reset_input(self, request, response):
        self._input_epoch = time.time()
        self.buffer.clear()
        while not self.audio_queue.empty():
            self.audio_queue.get_nowait()
        self.state = STTState.IDLE
        response.success = self.audio_input_mode == "topic"
        response.message = "Input drained" if response.success else "Visitor requires topic audio input"
        return response

    # Callbacks
    def _on_tts_speaking(self, msg: Bool):
        """Mute microphone while TTS is playing to prevent self-detection."""
        with self.state_lock:
            was_speaking = self.dori_speaking
            self.dori_speaking = msg.data

            if self.dori_speaking:
                self.get_logger().info("TTS speaking — STT muted")
                self.state = STTState.IDLE
                self.buffer.clear()
                while not self.audio_queue.empty():
                    self.audio_queue.get_nowait()

            elif was_speaking and not self.dori_speaking:
                self.mute_until = time.time() + 0.8
                self.get_logger().info("TTS ended — STT deaf margin active for 0.8s")

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            self.get_logger().warn(f"Audio status: {status}")

        if self.dori_speaking or time.time() < self.mute_until:
            return

        try:
            pcm = np.frombuffer(indata, dtype=np.int16)

            with self.state_lock:
                if self.state == STTState.IDLE:
                    prediction = self.oww_model.predict(pcm)
                    # prediction은 딕셔너리 형태 {'hey_mycroft': 0.85, ...}
                    for model_name, score in prediction.items():
                        if score > self.wake_word_threshold:
                            self.get_logger().info(
                                f"Wake word detected! ({model_name}: {score:.2f})"
                            )
                            self.state = STTState.LISTENING
                            self.listen_start_time = time.time()
                            self.last_voice_time = time.time()
                            self.buffer.clear()

                            wake_msg = Bool()
                            wake_msg.data = True
                            self.wake_word_pub.publish(wake_msg)

                            # 한 번 인식되면 버퍼(내부 상태)를 비워 연속 인식을 방지합니다.
                            self.oww_model.reset()
                            break

                elif self.state == STTState.LISTENING:
                    self.audio_queue.put_nowait(bytes(indata))

        except Exception as e:
            self.get_logger().error(f"Audio callback error: {e}")

    def _on_audio_input_topic(self, msg: String):
        if self.audio_input_mode != "topic":
            return
        request_id = None
        try:
            import base64

            payload = json.loads(msg.data)
            request_id = payload.get("request_id")
            if payload.get("request_id") and payload.get("created_at", 0) < self._input_epoch:
                return  # Queued audio predating session cleanup.
            if self.dori_speaking:
                self._publish_stt_error(request_id, "stt_busy")
                return
            fmt = payload.get("format")
            if fmt != "wav_pcm16":
                raise ValueError(f"Unsupported audio format: {fmt}")
            audio_b64 = payload.get("audio_b64")
            if not audio_b64:
                raise ValueError("Missing audio")
            if not isinstance(audio_b64, str) or len(audio_b64) > ((44 + SAMPLE_RATE * 2 * int(MAX_BUFFER_SEC) + 2) // 3 * 4):
                raise ValueError("Audio message exceeds 120 seconds")
            wav_bytes = base64.b64decode(audio_b64, validate=True)
            with wave.open(BytesIO(wav_bytes), "rb") as wf:
                sr = wf.getframerate()
                ch = wf.getnchannels()
                width = wf.getsampwidth()
                frames = wf.getnframes()
                raw = wf.readframes(frames)
            if sr != SAMPLE_RATE or ch != 1 or width != 2 or len(raw) != frames * 2:
                raise ValueError("Expected complete 16000Hz mono 16-bit PCM")
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            if not MIN_SPEECH_SEC <= len(audio) / SAMPLE_RATE <= MAX_BUFFER_SEC:
                raise ValueError("Audio duration must be 0.5 to 120 seconds")
            self.buffer = [audio]
            self._transcribe(request_id=request_id)
        except Exception as e:
            self.get_logger().error(f"Audio topic decode/transcribe failed: {e}")
            self._publish_stt_error(request_id, "stt_invalid_audio")
        finally:
            self.buffer.clear()

    def _publish_stt_error(self, request_id, code):
        if request_id:
            self.visitor_result_pub.publish(String(data=json.dumps({
                "request_id": request_id, "event": "stt_error", "code": code,
                "text": "", "timestamp": time.time(),
            })))

    # Audio processing (timer callback)
    def _process_audio(self):
        if self.dori_speaking:
            return

        with self.state_lock:
            if self.state != STTState.LISTENING:
                return

            chunks = 0
            while not self.audio_queue.empty() and chunks < 10:
                chunk = self.audio_queue.get()
                audio = (
                    np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                )
                self.buffer.append(audio)
                chunks += 1

                if self._has_voice(audio):
                    self.last_voice_time = time.time()

            now = time.time()
            audio_duration = len(self.buffer) * FRAME_LENGTH / SAMPLE_RATE

            if (
                self.last_voice_time
                and (now - self.last_voice_time) > self.vad_silence_sec
            ):
                if audio_duration >= MIN_SPEECH_SEC:
                    self.get_logger().info(
                        f"Speech end detected ({audio_duration:.2f}s) — transcribing"
                    )
                    self._transcribe()
                else:
                    self.get_logger().info(
                        f"Speech too short ({audio_duration:.2f}s) — discarding"
                    )
                self.state = STTState.IDLE
                self.buffer.clear()
                return

            if (
                self.listen_start_time
                and (now - self.listen_start_time) > MAX_BUFFER_SEC
            ):
                self.get_logger().warn("Max buffer exceeded — force transcribing")
                self._transcribe()
                self.state = STTState.IDLE
                self.buffer.clear()

    def _has_voice(self, audio: np.ndarray) -> bool:
        """Detect voice energy without fetching a model at runtime."""
        if self.vad_model is None:
            return float(np.sqrt(np.mean(audio * audio))) > 0.01
        try:
            import torch

            tensor = torch.from_numpy(audio)
            prob = self.vad_model(tensor, SAMPLE_RATE).item()
            return prob > self.vad_threshold
        except Exception:
            return True

    # Transcription
    def _transcribe(self, request_id=None):
        if not self.buffer:
            self.get_logger().warn("Empty buffer — skipping transcription")
            self._publish_stt_error(request_id, "stt_invalid_audio")
            return

        try:
            audio = np.concatenate(self.buffer, axis=0)
            self.get_logger().info(
                f"Transcribing {len(audio) / SAMPLE_RATE:.2f}s audio..."
            )

            started = time.monotonic()
            visitor = bool(request_id)
            segments_gen, info = self.whisper.transcribe(
                audio,
                language=None,
                vad_filter=visitor,
                vad_parameters={"min_silence_duration_ms": 300, "speech_pad_ms": 200},
                beam_size=1 if visitor else 5,
                **({"temperature": 0.0, "condition_on_previous_text": False,
                    "without_timestamps": True} if visitor else {}),
            )
            segments = list(segments_gen)
            if visitor:
                # A relaxed text confidence threshold must not admit silence.
                segments = [seg for seg in segments if getattr(seg, "no_speech_prob", 0.0) < 0.6]
            text = "".join(seg.text for seg in segments).strip()

            logprobs = [
                seg.avg_logprob
                for seg in segments
                if hasattr(seg, "avg_logprob") and seg.avg_logprob is not None
            ]
            confidence = (
                float(min(1.0, max(0.0, np.exp(np.mean(logprobs)))))
                if logprobs
                else 0.5
            )

            normalized_text = text.strip()
            threshold = self.visitor_min_confidence if visitor else self.min_confidence
            is_low_conf = confidence < threshold
            is_empty = not normalized_text

            payload = {
                "text": normalized_text,
                "language": info.language,
                "confidence": round(confidence, 3),
                "timestamp": time.time(),
                "event": (
                    "stt_empty_or_low_conf"
                    if (is_empty or is_low_conf)
                    else "stt_result"
                ),
            }

            if is_empty:
                self.get_logger().info("Empty transcription result")
            elif is_low_conf:
                self.get_logger().info(
                    f'[{info.language}] low confidence (conf={confidence:.2f} < {threshold:.2f}) "{normalized_text}"'
                )
            else:
                self.get_logger().info(
                    f'[{info.language}] (conf={confidence:.2f}) "{normalized_text}"'
                )

            msg = String()
            msg.data = json.dumps(payload, ensure_ascii=False)
            if request_id:
                payload["request_id"] = request_id
                msg.data = json.dumps(payload, ensure_ascii=False)
                self.visitor_result_pub.publish(msg)
            else:
                self.result_pub.publish(msg)
            self.get_logger().info(f"Transcription completed in {time.monotonic() - started:.2f}s")

        except Exception as e:
            self.get_logger().error(f"Transcription failed: {e}")
            self._publish_stt_error(request_id, "stt_failed")

    # Cleanup
    def destroy_node(self):
        try:
            if hasattr(self, "stream"):
                self.stream.stop()
                self.stream.close()
            self.get_logger().info("STT resources released")
        except Exception as e:
            self.get_logger().error(f"Cleanup error: {e}")
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = STTNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

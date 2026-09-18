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

import sounddevice as sd

try:
    import openwakeword
    from openwakeword.model import Model
    openwakeword.utils.download_models() # 기본 모델 다운로드
    OPENWAKEWORD_AVAILABLE = True
except (ImportError, Exception):
    OPENWAKEWORD_AVAILABLE = False

try:
    from faster_whisper import WhisperModel
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


SAMPLE_RATE    = 16000
FRAME_LENGTH   = 1280    # openWakeWord: 1280
CHANNELS       = 1

MAX_BUFFER_SEC  = 10.0
MIN_SPEECH_SEC  = 0.5

class STTState:
    IDLE      = 'IDLE'       # waiting for wake word
    LISTENING = 'LISTENING'  # recording speech after wake word


class STTNode(Node):
    def __init__(self):
        super().__init__('stt_node')

        # Parameters
        self.declare_parameter('wake_word', 'hey_mycroft')
        self.declare_parameter('wake_word_threshold', 0.5)
        self.declare_parameter('whisper_model', 'small')
        self.declare_parameter('whisper_device', 'cpu')
        self.declare_parameter('vad_threshold', 0.5)
        self.declare_parameter('silence_duration', 1.2)
        self.declare_parameter('topics.wake_word_pub', 'stt/wake_word_detected')
        self.declare_parameter('topics.result_pub', 'stt/result')
        self.declare_parameter('min_confidence', 0.55)
        self.declare_parameter('topics.tts_speaking_sub', 'tts/speaking')
        self.declare_parameter('topics.audio_input_sub', 'stt/audio_input')
        self.declare_parameter('audio_input_mode', 'microphone')

        wake_word        = self.get_parameter('wake_word').value
        self.wake_word_threshold = self.get_parameter('wake_word_threshold').value
        model_size       = self.get_parameter('whisper_model').value
        device           = self.get_parameter('whisper_device').value
        self.vad_threshold   = self.get_parameter('vad_threshold').value
        self.vad_silence_sec = self.get_parameter('silence_duration').value
        self.min_confidence = float(self.get_parameter('min_confidence').value)

        wake_word_topic = self.get_parameter('topics.wake_word_pub').value
        result_topic = self.get_parameter('topics.result_pub').value
        tts_speaking_topic = self.get_parameter('topics.tts_speaking_sub').value
        audio_input_topic = self.get_parameter('topics.audio_input_sub').value
        self.audio_input_mode = self.get_parameter('audio_input_mode').value

        # Publishers
        self.wake_word_pub = self.create_publisher(Bool, wake_word_topic, 10)
        self.result_pub = self.create_publisher(String, result_topic, 10)

        # Subscribers
        self.create_subscription(
            Bool, tts_speaking_topic, self._on_tts_speaking, 10)
        self.create_subscription(
            String, audio_input_topic, self._on_audio_input_topic, 10)

        # State
        self.state           = STTState.IDLE
        self.robot_speaking  = False
        self.mute_until      = 0.0 # 잔향 방지를 위한 음소거 유예 시간
        self.audio_queue     = queue.Queue()
        self.buffer          = []
        self.listen_start_time: float | None = None
        self.last_voice_time: float | None   = None
        self.state_lock      = threading.Lock()

        # openWakeWord (wake word)
        if not OPENWAKEWORD_AVAILABLE:
            self.get_logger().warn('openwakeword not found: pip install openwakeword')
            return

        try:
            self.oww_model = Model(
                wakeword_models=[wake_word],
                inference_framework='onnx'
            )
            self.get_logger().info(f'openWakeWord ready (model: {wake_word})')
        except Exception as e:
            self.get_logger().error(f'openWakeWord init failed: {e}')
            return

        # Silero VAD
        self.vad_model = None
        self.get_vad_speech_prob = None
        if TORCH_AVAILABLE:
            try:
                self.vad_model, utils = torch.hub.load(
                    repo_or_dir='snakers4/silero-vad',
                    model='silero_vad',
                    force_reload=False,
                    onnx=False,
                )
                self.get_vad_speech_prob = utils[0]
                self.get_logger().info(
                    f'Silero VAD ready (threshold={self.vad_threshold})'
                )
            except Exception as e:
                self.get_logger().warn(f'VAD init failed, falling back to silence detection: {e}')
        else:
            self.get_logger().warn('torch not available — VAD disabled')

        # Whisper
        if not WHISPER_AVAILABLE:
            self.get_logger().error('faster-whisper not found: pip install faster-whisper')
            return

        try:
            self.get_logger().info(f'Loading Whisper ({model_size})...')
            self.whisper = WhisperModel(
                model_size,
                device=device,
                compute_type='int8' if device == 'cpu' else 'float16',
            )
            self.get_logger().info('Whisper ready')
        except Exception as e:
            self.get_logger().error(f'Whisper init failed: {e}')
            return

        # Audio stream
        if self.audio_input_mode == 'microphone':
            try:
                self.stream = sd.RawInputStream(
                    samplerate=SAMPLE_RATE,
                    blocksize=FRAME_LENGTH,
                    dtype='int16',
                    channels=CHANNELS,
                    callback=self._audio_callback,
                )
                self.stream.start()
                self.get_logger().info('Audio stream started')
            except Exception as e:
                self.get_logger().error(f'Audio stream failed: {e}')
                return
        else:
            self.get_logger().info(
                f'Audio input mode is "{self.audio_input_mode}" - microphone capture disabled'
            )

        # Processing timer (20 Hz)
        self.create_timer(0.05, self._process_audio)

        self.get_logger().info('STT Node ready')

    # Callbacks
    def _on_tts_speaking(self, msg: Bool):
        """Mute microphone while TTS is playing to prevent self-detection."""
        with self.state_lock:
            was_speaking = self.robot_speaking
            self.robot_speaking = msg.data

            if self.robot_speaking:
                self.get_logger().info('TTS speaking — STT muted')
                self.state = STTState.IDLE
                self.buffer.clear()
                while not self.audio_queue.empty():
                    self.audio_queue.get_nowait()

            elif was_speaking and not self.robot_speaking:
                self.mute_until = time.time() + 0.8
                self.get_logger().info('TTS ended — STT deaf margin active for 0.8s')

    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            self.get_logger().warn(f'Audio status: {status}')

        if self.robot_speaking or time.time() < self.mute_until:
            return

        try:
            pcm = np.frombuffer(indata, dtype=np.int16)

            with self.state_lock:
                if self.state == STTState.IDLE:
                    prediction = self.oww_model.predict(pcm)
                    # prediction은 딕셔너리 형태 {'hey_mycroft': 0.85, ...}
                    for model_name, score in prediction.items():
                        if score > self.wake_word_threshold:
                            self.get_logger().info(f'Wake word detected! ({model_name}: {score:.2f})')
                            self.state = STTState.LISTENING
                            self.listen_start_time = time.time()
                            self.last_voice_time   = time.time()
                            self.buffer.clear()

                            wake_msg = Bool()
                            wake_msg.data = True
                            self.wake_word_pub.publish(wake_msg)
                            
                            # 한 번 인식되면 버퍼(내부 상태)를 비워 연속 인식을 방지합니다.
                            self.oww_model.reset()
                            break

                elif self.state == STTState.LISTENING:
                    self.audio_queue.put(bytes(indata))

        except Exception as e:
            self.get_logger().error(f'Audio callback error: {e}')

    def _on_audio_input_topic(self, msg: String):
        if self.robot_speaking:
            return
        if self.audio_input_mode != 'topic':
            return
        try:
            import base64
            payload = json.loads(msg.data)
            fmt = payload.get('format')
            if fmt != 'wav_pcm16':
                self.get_logger().warn(f'Unsupported audio format: {fmt}')
                return
            audio_b64 = payload.get('audio_b64')
            if not audio_b64:
                return
            wav_bytes = base64.b64decode(audio_b64)
            with wave.open(BytesIO(wav_bytes), 'rb') as wf:
                sr = wf.getframerate()
                ch = wf.getnchannels()
                width = wf.getsampwidth()
                raw = wf.readframes(wf.getnframes())
            if sr != SAMPLE_RATE or ch != 1 or width != 2:
                self.get_logger().warn(
                    f'Audio spec mismatch (sr={sr}, ch={ch}, width={width * 8}bit). '
                    f'Expected {SAMPLE_RATE}Hz mono 16-bit PCM.'
                )
                return
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            self.buffer = [audio]
            self._transcribe()
            self.buffer.clear()
        except Exception as e:
            self.get_logger().error(f'Audio topic decode/transcribe failed: {e}')

    # Audio processing (timer callback)
    def _process_audio(self):
        if self.robot_speaking:
            return

        with self.state_lock:
            if self.state != STTState.LISTENING:
                return

            chunks = 0
            while not self.audio_queue.empty() and chunks < 10:
                chunk = self.audio_queue.get()
                audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                self.buffer.append(audio)
                chunks += 1

                if self._has_voice(audio):
                    self.last_voice_time = time.time()

            now = time.time()
            audio_duration = len(self.buffer) * FRAME_LENGTH / SAMPLE_RATE

            if (self.last_voice_time
                    and (now - self.last_voice_time) > self.vad_silence_sec):
                if audio_duration >= MIN_SPEECH_SEC:
                    self.get_logger().info(
                        f'Speech end detected ({audio_duration:.2f}s) — transcribing'
                    )
                    self._transcribe()
                else:
                    self.get_logger().info(
                        f'Speech too short ({audio_duration:.2f}s) — discarding'
                    )
                self.state = STTState.IDLE
                self.buffer.clear()
                return

            if (self.listen_start_time
                    and (now - self.listen_start_time) > MAX_BUFFER_SEC):
                self.get_logger().warn('Max buffer exceeded — force transcribing')
                self._transcribe()
                self.state = STTState.IDLE
                self.buffer.clear()

    def _has_voice(self, audio: np.ndarray) -> bool:
        """Return True if VAD detects speech, or True by default if VAD unavailable."""
        if self.vad_model is None:
            return True
        try:
            import torch
            tensor = torch.from_numpy(audio)
            prob = self.vad_model(tensor, SAMPLE_RATE).item()
            return prob > self.vad_threshold
        except Exception:
            return True

    # Transcription
    def _transcribe(self):
        if not self.buffer:
            self.get_logger().warn('Empty buffer — skipping transcription')
            return

        try:
            audio = np.concatenate(self.buffer, axis=0)
            self.get_logger().info(
                f'Transcribing {len(audio) / SAMPLE_RATE:.2f}s audio...'
            )

            segments_gen, info = self.whisper.transcribe(
                audio,
                language=None,
                vad_filter=False,
                beam_size=5,
            )
            segments = list(segments_gen)
            text = ''.join(seg.text for seg in segments).strip()

            logprobs = [
                seg.avg_logprob for seg in segments
                if hasattr(seg, 'avg_logprob') and seg.avg_logprob is not None
            ]
            confidence = float(
                min(1.0, max(0.0, np.exp(np.mean(logprobs))))
            ) if logprobs else 0.5

            normalized_text = text.strip()
            is_low_conf = confidence < self.min_confidence
            is_empty = not normalized_text

            payload = {
                'text': normalized_text,
                'language': info.language,
                'confidence': round(confidence, 3),
                'timestamp': time.time(),
                'event': 'stt_empty_or_low_conf' if (is_empty or is_low_conf) else 'stt_result',
            }

            if is_empty:
                self.get_logger().info('Empty transcription result')
            elif is_low_conf:
                self.get_logger().info(
                    f'[{info.language}] low confidence (conf={confidence:.2f} < {self.min_confidence:.2f}) "{normalized_text}"'
                )
            else:
                self.get_logger().info(
                    f'[{info.language}] (conf={confidence:.2f}) "{normalized_text}"'
                )

            msg = String()
            msg.data = json.dumps(payload, ensure_ascii=False)
            self.result_pub.publish(msg)

        except Exception as e:
            self.get_logger().error(f'Transcription failed: {e}')

    # Cleanup
    def destroy_node(self):
        try:
            if hasattr(self, 'stream'):
                self.stream.stop()
                self.stream.close()
            self.get_logger().info('STT resources released')
        except Exception as e:
            self.get_logger().error(f'Cleanup error: {e}')
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


if __name__ == '__main__':
    main()

import rclpy
from rclpy.node import Node

from std_msgs.msg import String, Bool

import sounddevice as sd
import numpy as np
import queue
import struct
import time
import threading
import json
import os

import pvporcupine
from faster_whisper import WhisperModel
from faster_whisper.vad import Vad


SAMPLE_RATE = 16000
FRAME_LENGTH = 512 # Porcupine
CHANNELS = 1

MAX_BUFFER_SEC = 10.0 
VAD_SILENCE_SEC = 1.2

FRAME_DURATION = 30  # ms
FRAME_SIZE = int(SAMPLE_RATE * FRAME_DURATION / 1000)
MAX_SPEECH_SECONDS = 8
MIN_SPEECH_SECONDS = 0.5


class STTNode(Node):
    def __init__(self):
        super().__init__('stt_node')

        # Parameters
        self.declare_parameter('wake_word', 'hey robot')
        self.declare_parameter('whisper_model', 'small')
        self.declare_parameter('whisper_device', 'cpu')
        self.declare_parameter('vad_threshold', 0.5)
        self.declare_parameter('silence_duration', 1.2)
        
        wake_word = self.get_parameter('wake_word').value
        model_size = self.get_parameter('whisper_model').value
        device = self.get_parameter('whisper_device').value
        vad_threshold = self.get_parameter('vad_threshold').value
        self.vad_silence_sec = self.get_parameter('silence_duration').value

        # ROS Publishers / Subscribers
        self.text_pub = self.create_publisher(String, '/stt/text', 10)

        self.speaking_sub = self.create_subscription(
            Bool,
            '/robot/speaking',
            self.speaking_callback,
            10
        )

        # State variables
        self.state = "IDLE"
        self.robot_speaking = False

        self.audio_queue = queue.Queue()
        self.buffer = []

        self.listen_start_time = None
        self.last_voice_time = None
        
        # Thread safety
        self.state_lock = threading.Lock()

        # Wake word
        try:
            self.porcupine = pvporcupine.create(
                access_key=os.getenv('PORCUPINE_ACCESS_KEY'),
                keywords=[wake_word]
            )
            self.get_logger().info(f"Porcupine initialized with wake word: {wake_word}")
        except Exception as e:
            self.get_logger().error(f"Failed to initialize Porcupine: {e}")
            raise
        
        # VAD
        try:
            self.vad = Vad(
                sample_rate=SAMPLE_RATE,
                threshold=vad_threshold
            )
            self.get_logger().info(f"VAD initialized (threshold: {vad_threshold})")
        except Exception as e:
            self.get_logger().error(f"Failed to initialize VAD: {e}")
            raise

        # Whisper
        try:
            self.get_logger().info("Loading Whisper model...")
            self.model = WhisperModel(
                model_size, # tiny base small medium large
                device="cpu", # GPU: "cuda"
                compute_type="int8" if device == "cpu" else "float16"
            )
            self.get_logger().info("Whisper model loaded successfully")
        except Exception as e:
            self.get_logger().error(f"Failed to load Whisper: {e}")
            raise

        # Audio stream
        try:
            self.stream = sd.RawInputStream(
                samplerate=SAMPLE_RATE,
                blocksize=FRAME_LENGTH,
                dtype="int16",
                channels=CHANNELS,
                callback=self.audio_callback
            )
            self.stream.start()
            self.get_logger().info("Audio stream started")
        except Exception as e:
            self.get_logger().error(f"Failed to start audio stream: {e}")
            raise

        # Timer
        self.timer = self.create_timer(0.05, self.process_audio) # 20 Hz

        self.get_logger().info("STT initialized successfully")

    def __del__(self):
        self.cleanup()
    
    def cleanup(self):
        try:
            if hasattr(self, 'stream'):
                self.stream.stop()
                self.stream.close()
            if hasattr(self, 'porcupine'):
                self.porcupine.delete()
            self.get_logger().info("Resources cleaned up")
        except Exception as e:
            self.get_logger().error(f"Error during cleanup: {e}")

    # ROS callbacks
    def speaking_callback(self, msg: Bool):
        with self.state_lock:
            self.robot_speaking = msg.data

            if self.robot_speaking:
                self.get_logger().info("STT muted since Robot speaking")
                self.state = "IDLE"
                self.buffer.clear()
                with self.audio_queue.mutex:
                    self.audio_queue.queue.clear()

    def audio_callback(self, indata, frames, time_info, status):
        if status:
            self.get_logger().warn(f"Audio status: {status}")

        if self.robot_speaking:
            return
        
        try:
            pcm = struct.unpack_from("h" * frames, indata)

            with self.state_lock:
                if self.state == "IDLE":
                    keyword_index = self.porcupine.process(pcm)
                    if keyword_index >= 0:
                        self.get_logger().info("Wake word detected")
                        self.state = "LISTENING"
                        self.listen_start_time = time.time()
                        self.last_voice_time = time.time()
                        self.buffer.clear()

                elif self.state == "LISTENING":
                    self.audio_queue.put(indata.copy())
        
        except Exception as e:
            self.get_logger().error(f"Error in audio callback: {e}")

    def process_audio(self):
        if self.robot_speaking:
            return

        with self.state_lock:
            if self.state != "LISTENING":
                return

            chunks_processed = 0
            while not self.audio_queue.empty() and chunks_processed < 10:
                chunk = self.audio_queue.get()
                audio = np.frombuffer(chunk, dtype=np.int16).astype(np.float32) / 32768.0
                self.buffer.append(audio)
                chunks_processed += 1

                # VAD
                try:
                    if self.vad(audio):
                        self.last_voice_time = time.time()
                except Exception as e:
                    self.get_logger().warn(f"VAD error: {e}")

            now = time.time()

            # check for speech end (silence detected)
            if self.last_voice_time and (now - self.last_voice_time) > self.vad_silence_sec:
                audio_duration = len(self.buffer) * FRAME_LENGTH / SAMPLE_RATE
                
                if audio_duration >= MIN_SPEECH_SECONDS:
                    self.get_logger().info(f"✓ Speech ended ({audio_duration:.2f}s)")
                    self.transcribe_buffer()
                else:
                    self.get_logger().info(f"✗ Speech too short ({audio_duration:.2f}s), skipping")
                
                self.state = "IDLE"
                self.buffer.clear()

            # check for max buffer exceeded
            elif self.listen_start_time and (now - self.listen_start_time) > MAX_BUFFER_SEC:
                self.get_logger().warn("Max buffer exceeded, force transcribe.")
                self.transcribe_buffer()
                self.state = "IDLE"
                self.buffer.clear()

    def transcribe_buffer(self):
        if len(self.buffer) == 0:
            self.get_logger().warn("Empty buffer, skipping transcription")
            return

        try:
            audio = np.concatenate(self.buffer, axis=0)

            self.get_logger().info(f"Transcribing {len(audio) / SAMPLE_RATE:.2f} s audio")

            segments, info = self.model.transcribe(
                audio,
                language=None,
                vad_filter=False,
                beam_size=5
            )

            text = "".join([seg.text for seg in segments]).strip()
            
            logprobs = [
                seg.avg_logprob for seg in segments
                if seg.avg_logprob is not None
            ]

            confidence = min(1.0, max(0.0, (np.mean(logprobs) + 1.0))) # >0.8: >0.5: <0.4:

            if text:
                payload = {
                    "text": text,
                    "language": info.language,
                    "confidence": float(confidence),
                    "wake_word": True,
                    "timestamp": time.time()
                }
                self.get_logger().info(f"[{info.language}] {text}")
                self.text_pub.publish(
                    String(data=json.dumps(payload, ensure_ascii=False))
                    )
            else:
                self.get_logger().info("Empty transcription")
        
        except Exception as e:
            self.get_logger().error(f"Transcription failed: {e}")

def main():
    rclpy.init()
    node = STTNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("Shutting down...")
    finally:
        node.cleanup()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

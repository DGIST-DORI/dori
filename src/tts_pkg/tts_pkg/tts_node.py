import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool

import queue
import threading
import time
import os
import tempfile

# select TTS engine
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
    AUDIO_PLAYBACK_AVAILABLE = True
except ImportError:
    AUDIO_PLAYBACK_AVAILABLE = False


class TTSNode(Node):
    def __init__(self):
        super().__init__('tts_node')
        
        # Parameters
        self.declare_parameter('tts_engine', 'gtts')  # 'gtts' or 'pyttsx3'
        self.declare_parameter('language', 'ko')
        self.declare_parameter('speech_rate', 150)
        self.declare_parameter('volume', 0.9)
        
        self.tts_engine = self.get_parameter('tts_engine').value
        self.language = self.get_parameter('language').value
        self.speech_rate = self.get_parameter('speech_rate').value
        self.volume = self.get_parameter('volume').value
        
        # State
        self.is_speaking = False
        self.text_queue = queue.Queue()
        
        # Thread safety
        self.speaking_lock = threading.Lock()
        
        # ROS Publishers
        self.speaking_pub = self.create_publisher(Bool, '/dori/speaking', 10)
        self.done_pub = self.create_publisher(Bool, '/tts/done', 10)
        
        # ROS Subscribers
        self.text_sub = self.create_subscription(
            String,
            '/llm/response',
            self.text_callback,
            10
        )
        
        # Initialize TTS engine
        self._init_tts_engine()
        
        # TTS processing thread
        self.tts_thread = threading.Thread(target=self._process_tts_queue, daemon=True)
        self.tts_thread.start()
        
        self.get_logger().info(f"TTS node started with engine: {self.tts_engine}")
    
    def _init_tts_engine(self):
        if self.tts_engine == 'pyttsx3':
            if not PYTTSX3_AVAILABLE:
                self.get_logger().error("pyttsx3 not available, falling back to gTTS")
                self.tts_engine = 'gtts'
            else:
                try:
                    self.pyttsx3_engine = pyttsx3.init()
                    self.pyttsx3_engine.setProperty('rate', self.speech_rate)
                    self.pyttsx3_engine.setProperty('volume', self.volume)
                    
                    # Korean voice setup (if available)
                    voices = self.pyttsx3_engine.getProperty('voices')
                    for voice in voices:
                        if 'korean' in voice.name.lower() or 'ko' in voice.id.lower():
                            self.pyttsx3_engine.setProperty('voice', voice.id)
                            break
                    
                    self.get_logger().info("pyttsx3 engine initialized")
                except Exception as e:
                    self.get_logger().error(f"Failed to init pyttsx3: {e}")
                    self.tts_engine = 'gtts'
        
        if self.tts_engine == 'gtts':
            if not GTTS_AVAILABLE:
                self.get_logger().error("gTTS not available!")
                raise RuntimeError("No TTS engine available")
            self.get_logger().info("Using gTTS engine")
    
    def text_callback(self, msg: String):
        text = msg.data.strip()
        
        if not text:
            self.get_logger().warn("Empty text received, skipping TTS")
            return
        
        self.get_logger().info(f"Received text: {text}")
        self.text_queue.put(text)
    
    def _process_tts_queue(self):
        while True:
            try:
                text = self.text_queue.get(timeout=0.1)
                self._speak(text)
            except queue.Empty:
                continue
            except Exception as e:
                self.get_logger().error(f"Error in TTS thread: {e}")
    
    def _speak(self, text: str): # text to speech and playback
        with self.speaking_lock:
            try:
                # speaking start signal
                self.is_speaking = True
                self.speaking_pub.publish(Bool(data=True))
                self.get_logger().info(f"Speaking: {text}")
                
                if self.tts_engine == 'pyttsx3':
                    self._speak_pyttsx3(text)
                elif self.tts_engine == 'gtts':
                    self._speak_gtts(text)
                
                # speaking end signal
                time.sleep(0.5)
                self.is_speaking = False
                self.speaking_pub.publish(Bool(data=False))
                self.done_pub.publish(Bool(data=True))
                self.get_logger().info("Speech completed")
                
            except Exception as e:
                self.get_logger().error(f"TTS failed: {e}")
                self.is_speaking = False
                self.speaking_pub.publish(Bool(data=False))
                self.done_pub.publish(Bool(data=True))
    
    def _speak_pyttsx3(self, text: str):
        try:
            self.pyttsx3_engine.say(text)
            self.pyttsx3_engine.runAndWait()
        except Exception as e:
            self.get_logger().error(f"pyttsx3 error: {e}")
            raise
    
    def _speak_gtts(self, text: str):
        try:
            # generate temp audio file
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as fp:
                temp_file = fp.name
            
            # generate TTS audio file
            tts = gTTS(text=text, lang=self.language, slow=False)
            tts.save(temp_file)
            
            # playback
            if AUDIO_PLAYBACK_AVAILABLE:
                self._play_audio(temp_file)
            else:
                # fallback: use system command
                os.system(f"mpg123 -q {temp_file} 2>/dev/null || afplay {temp_file} 2>/dev/null")
            
            # delete temp file
            os.unlink(temp_file)
            
        except Exception as e:
            self.get_logger().error(f"gTTS error: {e}")
            raise
    
    def _play_audio(self, filepath: str):
        try:
            data, samplerate = sf.read(filepath)
            sd.play(data, samplerate)
            sd.wait()
        except Exception as e:
            self.get_logger().error(f"Audio playback error: {e}")
            # fallback
            os.system(f"mpg123 -q {filepath} 2>/dev/null || afplay {filepath} 2>/dev/null")


def main():
    rclpy.init()
    node = TTSNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("Shutting down...")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

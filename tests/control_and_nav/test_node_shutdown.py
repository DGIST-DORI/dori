"""ROS shutdown must be idempotent; all hardware and provider I/O is mocked."""
import importlib
from unittest.mock import Mock

import pytest
from rclpy.executors import ExternalShutdownException


@pytest.mark.parametrize("module_name,class_name,multithreaded", [
    ("dori_hardware.imu_node", "ImuSerialNode", False),
    ("dori_hardware.body_pitch_node", "BodyPitchNode", False),
    ("dori_hardware.body_stabilizer_node", "BodyStabilizerNode", False),
    ("dori_hardware.servo3_pitch_follower_node", "Servo3PitchFollowerNode", False),
    ("dori_hardware.motor4_servo_node", "Motor4ServoNode", False),
    ("dori_hri.emotion_publisher_node", "EmotionPublisherNode", False),
    ("dori_hri.tts_node", "TTSNode", True),
    ("dori_llm.llm_node", "LLMNode", True),
])
@pytest.mark.parametrize("interruption", [KeyboardInterrupt, ExternalShutdownException])
def test_shutdown_cleans_up_after_signal(module_name, class_name, multithreaded, interruption, monkeypatch):
    module = importlib.import_module(module_name)
    node = Mock()
    monkeypatch.setattr(module, class_name, Mock(return_value=node))
    monkeypatch.setattr(module.rclpy, "init", Mock())
    shutdown = Mock()
    monkeypatch.setattr(module.rclpy, "try_shutdown", shutdown)
    monkeypatch.setattr(module.rclpy, "ok", lambda: True)
    if multithreaded:
        executor = Mock()
        executor.spin.side_effect = interruption()
        monkeypatch.setattr(module, "MultiThreadedExecutor", Mock(return_value=executor))
    else:
        monkeypatch.setattr(module.rclpy, "spin", Mock(side_effect=interruption()))
    module.main()
    node.destroy_node.assert_called_once()
    shutdown.assert_called_once()

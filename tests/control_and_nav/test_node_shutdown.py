"""ROS shutdown must be idempotent; all hardware and provider I/O is mocked."""
import importlib
import importlib.util
from pathlib import Path
import sys
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
@pytest.mark.parametrize("interruption,context_active", [
    (KeyboardInterrupt, True), (ExternalShutdownException, True),
    (RuntimeError, False), (RuntimeError, True),
])
def test_shutdown_cleans_up_after_signal(module_name, class_name, multithreaded, interruption, context_active, monkeypatch):
    module = importlib.import_module(module_name)
    node = Mock()
    monkeypatch.setattr(module, class_name, Mock(return_value=node))
    monkeypatch.setattr(module.rclpy, "init", Mock())
    shutdown = Mock()
    monkeypatch.setattr(module.rclpy, "try_shutdown", shutdown)
    monkeypatch.setattr(module.rclpy, "ok", lambda: context_active)
    if multithreaded:
        executor = Mock()
        executor.spin.side_effect = interruption()
        monkeypatch.setattr(module, "MultiThreadedExecutor", Mock(return_value=executor))
    else:
        monkeypatch.setattr(module.rclpy, "spin", Mock(side_effect=interruption()))
    if interruption is RuntimeError and context_active:
        with pytest.raises(RuntimeError):
            module.main()
    else:
        module.main()
    node.destroy_node.assert_called_once()
    shutdown.assert_called_once()


@pytest.mark.parametrize("package,script,class_name", [
    ("dori_mapping", "lidar_odometry_node", "LidarOdometry"),
    ("dori_navigation", "nav_drive_bridge", "NavDriveBridge"),
    ("dori_navigation", "web_viewer", "WebBridge"),
    ("dori_navigation", "navigation_startup", "NavigationStartup"),
])
def test_navigation_scripts_clean_up_after_context_shutdown(package, script, class_name, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "ros2_ws/src" / package / "scripts" / (script + ".py")
    monkeypatch.syspath_prepend(str(path.parent))
    spec = importlib.util.spec_from_file_location(script + "_shutdown_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    node = Mock()
    monkeypatch.setattr(module, class_name, Mock(return_value=node))
    monkeypatch.setattr(module.rclpy, "init", Mock())
    monkeypatch.setattr(module.rclpy, "ok", lambda: False)
    monkeypatch.setattr(module.rclpy, "spin", Mock(side_effect=ExternalShutdownException()))
    shutdown = Mock()
    monkeypatch.setattr(module.rclpy, "try_shutdown", shutdown)
    if script == "web_viewer":
        monkeypatch.setattr(sys, "argv", [script, "--user-port", "0"])
        monkeypatch.setattr(module, "ViewerServer", Mock())
        monkeypatch.setattr(module.threading, "Thread", Mock())
    module.main()
    node.destroy_node.assert_called_once()
    shutdown.assert_called_once()


@pytest.mark.parametrize("module_name,class_name", [
    ("dori_llm.llm_node", "LLMNode"), ("dori_hri.tts_node", "TTSNode"),
])
def test_signal_during_provider_initialization_still_closes_context(module_name, class_name, monkeypatch):
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module.rclpy, "init", Mock())
    monkeypatch.setattr(module, class_name, Mock(side_effect=KeyboardInterrupt()))
    shutdown = Mock()
    monkeypatch.setattr(module.rclpy, "try_shutdown", shutdown)
    module.main()
    shutdown.assert_called_once()


@pytest.mark.parametrize("context_active", [False, True])
def test_imu_serial_thread_only_ignores_publish_error_after_shutdown(context_active, monkeypatch):
    from dori_hardware import imu_node
    node = Mock()
    node.running = True
    node.ser.readline.return_value = b"0,0,1,0,0,0,0,0,0\n"
    node.publish_data.side_effect = imu_node.RCLError("publisher context invalid")
    monkeypatch.setattr(imu_node.rclpy, "ok", lambda: context_active)
    if context_active:
        with pytest.raises(imu_node.RCLError):
            imu_node.ImuSerialNode.serial_loop(node)
    else:
        imu_node.ImuSerialNode.serial_loop(node)
    node.publish_data.assert_called_once()


@pytest.mark.parametrize("context_active", [False, True])
def test_servo_follower_only_ignores_take_message_error_after_shutdown(context_active, monkeypatch):
    from dori_hardware import servo3_pitch_follower_node as module
    node = Mock()
    monkeypatch.setattr(module, "Servo3PitchFollowerNode", Mock(return_value=node))
    monkeypatch.setattr(module.rclpy, "init", Mock())
    monkeypatch.setattr(module.rclpy, "spin", Mock(side_effect=RuntimeError("take_message failed")))
    monkeypatch.setattr(module.rclpy, "ok", lambda: context_active)
    monkeypatch.setattr(module.rclpy, "try_shutdown", Mock())
    if context_active:
        with pytest.raises(RuntimeError, match="take_message failed"):
            module.main()
    else:
        module.main()
    node.destroy_node.assert_called_once()

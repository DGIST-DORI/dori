"""Exercise trial termination with simulated feedback; no ROS or CAN access."""
from dataclasses import dataclass
import importlib.util
import json
import math
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


@dataclass
class State:
    position_deg: float = 0.0
    velocity_rad_s: float = 0.0
    current_a: float = 7.45
    temperature_c: int = 65
    error: int = 0


@pytest.mark.parametrize("fault,expected", [(None, "success"), ("motor", "aborted"), ("temperature", "aborted")])
def test_current_is_telemetry_but_motor_faults_and_temperature_still_stop(monkeypatch, tmp_path, fault, expected):
    clock = SimpleNamespace(now=10.0)
    instances = []

    class Bridge:
        def __init__(self):
            self.guard = SimpleNamespace(state=State(), feedback_at=clock.now,
                                         faulted=False, owned=False)
            self.guard.ready = lambda now: not self.guard.faulted and not self.guard.state.error
            self.stop_pending = False
            self.target = 0.0
            self.stop_called = False
            instances.append(self)

        def action(self, msg):
            pass

        def command(self, msg):
            self.target = msg.data
            self.guard.owned = True

        def stop(self):
            self.stop_called = True
            self.guard.owned = False

        def close(self):
            pass

        def destroy_node(self):
            pass

    def spin_once(node, timeout_sec):
        clock.now += 0.02
        node.guard.feedback_at = clock.now
        state = node.guard.state
        error = node.target - state.position_deg
        movement = max(-0.2, min(0.2, error)) if node.guard.owned else 0.0
        state.position_deg += movement
        state.velocity_rad_s = math.radians(movement / 0.02)
        if state.position_deg < -1:
            state.error = 3 if fault == "motor" else 0
            state.temperature_c = 81 if fault == "temperature" else 65

    fake_ros = ModuleType("rclpy")
    fake_ros.init = lambda args: None
    fake_ros.spin_once = spin_once
    fake_ros.ok = lambda: True
    fake_ros.shutdown = lambda: None
    fake_messages = ModuleType("std_msgs.msg")
    fake_messages.Float64 = fake_messages.Int32 = lambda **kw: SimpleNamespace(**kw)
    fake_driver = ModuleType("dori_hardware.motor4_servo_node")
    fake_driver.Motor4ServoNode = Bridge
    for name, module in (("rclpy", fake_ros), ("std_msgs.msg", fake_messages),
                         ("dori_hardware.motor4_servo_node", fake_driver)):
        monkeypatch.setitem(sys.modules, name, module)
    source = Path(__file__).resolve().parents[2] / "tools/drive/trial_motor4_90.py"
    spec = importlib.util.spec_from_file_location("motor4_trial_under_test", source)
    trial = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(trial)
    monkeypatch.setattr(trial, "time", SimpleNamespace(monotonic=lambda: clock.now))
    monkeypatch.setattr(trial, "signal", SimpleNamespace(SIGTERM=15, signal=lambda *args: None))
    monkeypatch.setenv("ROS_DOMAIN_ID", "87")
    output = tmp_path / "result.json"
    monkeypatch.setattr(sys, "argv", [str(source), "--execute", "--output", str(output)])
    status = trial.main()
    report = json.loads(output.read_text())
    assert report["result"] == expected
    assert status == (0 if expected == "success" else 1)
    assert instances[0].stop_called and not instances[0].guard.owned
    if expected == "success":
        assert report["final"]["position_deg"] == pytest.approx(-90.0)
        assert report["software_current_cutoff"] is False

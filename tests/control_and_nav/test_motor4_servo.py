"""AK45-36 wire units and command gates; no ROS graph or hardware needed."""

import importlib.util
import math
from pathlib import Path
import struct
import sys

import pytest

SOURCE = (Path(__file__).resolve().parents[2] /
          "ros2_ws/src/dori_hardware/dori_hardware/cubemars_servo.py")
SPEC = importlib.util.spec_from_file_location("motor4_servo_codec", SOURCE)
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_servo_feedback_uses_correct_output_units_and_signed_values():
    protocol = module.ServoProtocol()
    state = protocol.feedback(module.EFF | 0x2904, struct.pack(">hhhbB", -1800, 84, -120, 63, 0))
    assert state.position_deg == -180
    assert state.velocity_rad_s == pytest.approx(math.radians(10))
    assert state.current_a == -1.2
    assert state.temperature_c == 63
    assert state.error == 0


def test_reject_other_motor_protocol_boot_error_and_short_frames():
    protocol = module.ServoProtocol()
    data = b"\0" * 8
    for can_id in (4, 0x2904, module.EFF | 0x2901, module.EFF | 0x0904,
                   module.EFF | 0x2C04, module.EFF | module.RTR | 0x2904,
                   module.EFF | module.ERR | 0x2904):
        assert protocol.feedback(can_id, data) is None
    assert protocol.feedback(module.EFF | 0x2904, data[:7]) is None


def test_position_speed_packet_has_half_turn_not_gearbox_multiplied_position():
    packet = module.ServoProtocol().position(-180, 10, 20)
    can_id, length, data = module.FRAME.unpack(packet)
    assert can_id == module.EFF | 0x604
    assert length == 8
    # -180 degrees, 840 electrical RPM, 1680 electrical RPM/s.
    assert struct.unpack(">ihh", data) == (-1800000, 84, 168)
    assert module.FRAME.unpack(module.ServoProtocol().stop()) == (
        module.EFF | 0x304, 4, b"\0" * 8)


@pytest.mark.parametrize("goal,speed,accel", [
    (math.nan, 10, 20), (math.inf, 10, 20), (3201, 10, 20),
    (0, 0, 20), (0, 10, -1), (0, 10000, 20), (0, 0.00001, 20),
])
def test_invalid_wire_commands_fail_before_sending(goal, speed, accel):
    with pytest.raises(ValueError):
        module.ServoProtocol().position(goal, speed, accel)


def ready_guard():
    guard = module.Motor4Guard(-182, 2)
    guard.action_state = 2
    guard.state = module.ServoState(0, 0, 0, 63, 0)
    guard.feedback_at = 10.0
    return guard


def test_startup_estop_wrong_state_and_stale_feedback_reject_motion():
    assert not module.Motor4Guard(-182, 2).accept(-30, 10)
    for action in (None, 0, 1, 3, 4, 5):
        guard = ready_guard()
        guard.action_state = action
        assert not guard.accept(-30, 10.1)
    guard = ready_guard()
    assert not guard.accept(-30, 10.3)
    assert not guard.accept(-30, 9.9)


def test_angle_fault_and_bad_goal_limits():
    guard = ready_guard()
    for target in (-183, 3, math.nan, math.inf):
        assert not guard.accept(target, 10.1)
    guard.state = module.ServoState(0, 0, 0, 63, 5)
    assert not guard.accept(-30, 10.1)
    guard.state = module.ServoState(180, 0, 0, 63, 0)
    assert not guard.accept(-30, 10.1)


def test_watchdog_stops_on_missing_heartbeat_or_feedback_and_never_owns_startup():
    guard = ready_guard()
    assert not guard.needs_stop(30)  # Starting a listener never writes a stop.
    assert guard.accept(-30, 10.1)
    guard.owned = True
    assert not guard.needs_stop(10.2)
    assert guard.needs_stop(10.3)  # Feedback disappeared.
    guard.feedback_at = 10.5
    assert guard.needs_stop(10.5)  # Fresh motor, but dead transform controller.
    assert guard.accept(-30, 10.5)
    assert not guard.needs_stop(10.5)
    guard.action_state = 4
    assert guard.needs_stop(10.5)
    guard.action_state = 2
    guard.faulted = True
    assert not guard.accept(-30, 10.5)

"""Wire/ramp checks without accessing CAN."""
import importlib.util
import math
from pathlib import Path
import sys

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "tools/drive/trial_bldc_180.py"
SPEC = importlib.util.spec_from_file_location("bldc_trial", SOURCE)
trial = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = trial
SPEC.loader.exec_module(trial)


def test_neutral_frame_has_no_gains_and_uses_only_wheel_ids():
    left, right = trial.configuration()
    for motor in (left, right):
        can_id, length, data = trial.FRAME.unpack(trial.command(motor))
        assert can_id in (1, 2) and length == 8
        assert data.hex() == "7fff7ff0000007ff"


def test_positive_joint_motion_respects_calibrated_motor_polarities():
    left, right = trial.configuration()
    assert left.can_id == 2 and right.can_id == 1
    for motor, expected in ((left, bytes.fromhex("9fff")), (right, bytes.fromhex("5fff"))):
        _, _, payload = trial.FRAME.unpack(trial.command(motor, position=math.pi))
        assert payload[:2] == expected
        feedback = bytes([motor.can_id]) + payload[:2] + bytes.fromhex("7ff7ff4100")
        state = trial.decode(motor, motor.can_id, feedback)
        assert state["position"] == pytest.approx(math.pi, abs=0.001)
        assert trial.decode(motor, motor.can_id | 0x80000000, feedback) is None


def test_ramp_is_monotonic_bounded_and_stops_at_180():
    duration = trial.trajectory(0)[2]
    previous = 0.0
    for i in range(1001):
        position, velocity, _ = trial.trajectory(duration * i / 1000)
        assert previous <= position <= math.pi
        assert 0 <= velocity <= math.radians(10)
        previous = position
    assert trial.trajectory(duration)[:2] == (math.pi, 0.0)


@pytest.mark.parametrize("distance", [math.radians(-183.1), math.radians(-0.1), 0.0, math.radians(181.4)])
def test_signed_ramp_returns_to_zero_and_handles_short_moves(distance):
    duration = trial.trajectory(0, distance)[2]
    previous = 0.0
    for i in range(1001):
        position, velocity, _ = trial.trajectory(duration * i / 1000, distance)
        assert min(0, distance) <= position <= max(0, distance)
        assert abs(velocity) <= math.radians(10)
        if distance < 0:
            assert position <= previous and velocity <= 0
        else:
            assert position >= previous and velocity >= 0
        previous = position
    assert trial.trajectory(duration + 1, distance)[:2] == (distance, 0.0)


def test_both_wheels_reach_saved_zero_before_returning_to_distinct_angles():
    plan = trial.motion_plan(trial.configuration(), [181.36507209887844, 183.10093842984674])
    assert [(phase, motor.logical, angle) for phase, motor, angle in plan] == [
        ("zero", 1, 0.0), ("zero", 2, 0.0),
        ("return", 1, 181.36507209887844), ("return", 2, 183.10093842984674)]
    for invalid in ([float("nan"), 180], [181, 186], [181]):
        with pytest.raises(ValueError):
            trial.motion_plan(trial.configuration(), invalid)


def test_speed_comparison_aligns_then_balances_rounds_and_directions():
    motors = trial.configuration()
    plan = trial.comparison_plan(motors, [181.4, 183.1], [10, 15, 15, 10])
    assert [(p, m.logical, d) for p, m, d in plan[:2]] == [
        ("align", 1, 181.4), ("align", 2, 183.1)]
    assert len(plan) == 18
    for index in range(4):
        chunk = plan[2+index*4:6+index*4]
        assert [d for _, _, d in chunk] == [0, 0, 181.4, 183.1]
        assert all(p.startswith(f"round{index+1}_") for p, _, _ in chunk)


def test_first_pass_metrics_distinguish_overshoot_and_later_correction():
    def sample(at, deg):
        return dict(motor=1, received_at=at, position=math.radians(deg), torque=2, temperature=40)
    # An initial entry is insufficient if the motor later leaves the window.
    data = [sample(0.1, 2), sample(9.9, 179.5), sample(10.01, 178),
            sample(10.2, 181.5), sample(11, 180.2)]
    metrics = trial.leg_metrics(data, 1, 0, 0, 11, 0, 180, 10, 15)
    assert metrics["first_entry_s"] == 9.9
    assert metrics["ramp_end_error_deg"] == pytest.approx(-2)
    assert metrics["correction_and_confirmation_s"] == 1
    assert metrics["overshoot_deg"] == pytest.approx(1.5)
    assert not metrics["first_pass"]
    reverse = [sample(0.1, 178), sample(10.01, -0.4), sample(10.5, 0.2)]
    metrics = trial.leg_metrics(reverse, 1, 0, 0, 10.5, 180, 0, 10, 10)
    assert metrics["first_pass"]
    assert metrics["overshoot_deg"] == pytest.approx(0.4)


def test_endpoint_gain_changes_only_after_ramp_and_is_bounded():
    assert trial.settling_gain(45, 60, -20) == 45
    assert trial.settling_gain(45, 60, 0) == 45
    assert trial.settling_gain(45, 60, 0.5) == 52.5
    assert trial.settling_gain(45, 60, 1) == 60
    assert trial.settling_gain(45, 60, 20) == 60


<<<<<<< Updated upstream
@pytest.mark.parametrize("speed", [15, 20, 25])
=======
@pytest.mark.parametrize("speed", [15, 20, 25, 30, 40, 50, 60])
>>>>>>> Stashed changes
@pytest.mark.parametrize("distance", [math.pi, -math.pi])
def test_faster_ramp_preserves_acceleration_and_brakes_at_target(speed, distance):
    duration = trial.trajectory(0, distance, speed)[2]
    assert duration < trial.trajectory(0, math.pi, 10)[2]
    dt = 0.001
    prior_velocity = 0.0
    for i in range(1, math.ceil(duration / dt) + 2):
        position, velocity, _ = trial.trajectory(i * dt, distance, speed)
        assert min(0, distance) <= position <= max(0, distance)
        assert abs(velocity) <= math.radians(speed)
        assert abs(velocity - prior_velocity) / dt <= math.radians(20) + 1e-8
        prior_velocity = velocity
    assert trial.trajectory(duration + 1, distance, speed)[:2] == (distance, 0)


def test_twenty_degree_comparison_keeps_the_original_endpoints():
    plan = trial.comparison_plan(trial.configuration(), [181.365, 183.101], [20, 20])
    assert len(plan) == 10
    for start in (2, 6):
        assert [angle for _, _, angle in plan[start:start+4]] == [0, 0, 181.365, 183.101]
    with pytest.raises(ValueError):
<<<<<<< Updated upstream
        trial.trajectory(1, math.pi, 26)
=======
        trial.trajectory(1, math.pi, 61)
>>>>>>> Stashed changes


def test_five_rounds_per_speed_keep_balanced_order_and_both_directions():
    speeds = [15, 20, 25, 20, 25, 15, 25, 15, 20, 15, 25, 20, 25, 20, 15]
    assert all(speeds.count(s) == 5 for s in (15, 20, 25))
    plan = trial.comparison_plan(trial.configuration(), [181.365, 183.101], speeds)
    assert len(plan) == 62
    for i in range(15):
        assert [angle for _, _, angle in plan[2+i*4:6+i*4]] == [0, 0, 181.365, 183.101]


<<<<<<< Updated upstream
=======
def test_thirty_and_forty_degree_comparison_repeats_each_speed_five_times():
    speeds = [30, 40, 40, 30, 40, 30, 30, 40, 40, 30]
    assert all(speeds.count(s) == 5 for s in (30, 40))
    plan = trial.comparison_plan(trial.configuration(), [181.365, 183.101], speeds)
    assert len(plan) == 42
    for i in range(10):
        assert [(m.logical, angle) for _, m, angle in plan[2+i*4:6+i*4]] == [
            (1, 0), (2, 0), (1, 181.365), (2, 183.101)]


def test_fifty_and_sixty_degree_trials_keep_acceleration_and_five_rounds_each():
    speeds = [50, 60, 60, 50, 60, 50, 50, 60, 60, 50]
    assert all(speeds.count(s) == 5 for s in (50, 60))
    plan = trial.comparison_plan(trial.configuration(), [181.365, 183.101], speeds)
    assert len(plan) == 42
    assert trial.trajectory(0, math.pi, 50)[2] == pytest.approx(6.1)
    assert trial.trajectory(0, math.pi, 60)[2] == pytest.approx(6.0)
    # At 20 deg/s^2, a 180-degree move reaches 60 deg/s only at its midpoint.
    p, v, _ = trial.trajectory(3, math.pi, 60)
    assert math.degrees(p) == pytest.approx(90)
    assert math.degrees(v) == pytest.approx(60)


>>>>>>> Stashed changes
def test_correction_count_ignores_noise_and_counts_distinct_restarts():
    noise = [(i/100, 2 + (0.01 if i % 2 else -0.01)) for i in range(100)]
    assert trial.correction_events(noise, 0) == []
    # Two visible movements, separated by a stationary second.
    points = [(0, 2), (0.1, 1.9), (0.2, 1.7), (0.3, 1.5)]
    points += [(0.3+i/10, 1.5) for i in range(1, 11)]
    points += [(1.4, 1.4), (1.5, 1.2), (1.6, 0.8)]
    events = trial.correction_events(points, 0)
    assert len(events) == 2
    assert events[1]["reason"] == "restart"
    assert all(event["direction"] == -1 for event in events)


def test_correction_count_continuous_move_and_overshoot_reversal():
    continuous = [(i/100, 2 - i/100) for i in range(151)]
    assert len(trial.correction_events(continuous, 0)) == 1
    reversed_move = [(0, 2), (0.1, 1.5), (0.2, -1.3), (0.3, -1.4), (0.4, -0.9)]
    events = trial.correction_events(reversed_move, 0)
    assert len(events) == 2 and events[1]["reason"] == "reversal"
    assert trial.correction_events([(0, 0.8), (0.1, -0.8), (0.2, 0.5)], 0) == []


def test_endpoint_correction_bounds_unwinds_and_respects_polarity():
    effort = 0.0
    for _ in range(1000):
        new = trial.endpoint_integral(effort, math.radians(3), 0.01)
        assert abs(new - effort) <= 0.01 + 1e-12
        effort = new
    assert effort == 4.9
    assert trial.endpoint_integral(effort, 0.0, 0.01) == effort
    for _ in range(600):
        effort = trial.endpoint_integral(effort, math.radians(3), 0.01, moving=True)
    assert effort == 0.0
    for motor in trial.configuration():
        _, _, payload = trial.FRAME.unpack(trial.command(motor, torque_ff=-2))
        encoded = ((payload[6] & 15) << 8) | payload[7]
        assert (encoded < 2047) == (motor.sign > 0)


def test_endpoint_correction_closes_constant_load_offset():
    # Overdamped load model: without integral, a 2-unit load leaves 2.55 deg
    # error at Kp45. Check both directions converge below one degree.
    for sign in (-1, 1):
        position, effort = sign * math.radians(2.55), 0.0
        for _ in range(1500):
            error = -position
            effort = trial.endpoint_integral(effort, error, 0.01)
            velocity = (45 * error + effort + sign * 2.0) / 12.0
            position += velocity * 0.01
        assert abs(math.degrees(position)) < 1.0


@pytest.mark.parametrize("raw, celsius", [(0, -40), (79, 39), (80, 40), (120, 80), (200, 160), (255, 215)])
def test_mit_temperature_offset_and_unsigned_range(raw, celsius):
    motor = trial.configuration()[0]
    feedback = bytes([motor.can_id, 0x7f, 0xff, 0x7f, 0xf7, 0xff, raw, 0])
    state = trial.decode(motor, motor.can_id, feedback)
    assert state["temperature"] == celsius
    assert state["temperature_raw"] == raw
    assert state["raw_feedback"] == feedback.hex()


@pytest.mark.parametrize("raw, should_stop", [(80, False), (119, False), (120, True)])
def test_temperature_guard_uses_celsius(raw, should_stop):
    motor = trial.configuration()[0]
    frame = trial.FRAME.pack(motor.can_id, 8, bytes([motor.can_id, 0x7f, 0xff, 0x7f, 0xf7, 0xff, raw, 0]))

    class FakeBus:
        def recvmsg(self, _size):
            if self.frames:
                return self.frames.pop(), [], 0, None
            raise BlockingIOError()

    runner = object.__new__(trial.Trial)
    runner.bus = FakeBus()
    runner.bus.frames = [frame]
    runner.by_id = {motor.can_id: motor}
    runner.states, runner.seen, runner.samples = {}, {}, []
    if should_stop:
        with pytest.raises(RuntimeError, match="fault/temperature"):
            runner.receive()
    else:
        runner.receive()
    assert runner.states[motor.logical]["temperature"] == raw - 40
    runner.bus.frames = [frame]
    runner.receive(check_faults=False)  # Stop/observe can record an existing fault.


@pytest.mark.parametrize("position", [math.nan, math.inf, 20.0])
def test_out_of_range_goal_is_rejected(position):
    with pytest.raises(ValueError):
        trial.command(trial.configuration()[0], position=position)

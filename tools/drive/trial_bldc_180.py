#!/usr/bin/env python3
"""Move logical BLDC 1 and 2 +180 degrees from captured references, sequentially.

Uses the repository's calibrated MIT ranges, signs and position gains. No
encoder-zero command, mode change, or CAN ID 4 command is sent. The default
prints configuration only; --execute performs the bounded physical trial.
"""
import argparse
from collections import deque
import dataclasses
import json
import math
import os
from pathlib import Path
import select
import signal
import socket
import struct
import time
import xml.etree.ElementTree as ET

FRAME = struct.Struct("=IB3x8s")
ROOT = Path(__file__).resolve().parents[2]
# Existing transform_params.yaml BLDC settling threshold; the raw velocity
# estimate fluctuates while stationary encoder positions remain unchanged.
SETTLE_VELOCITY = 0.35
# No larger than the existing right/left near-target effort settings (4.9/5.0).
ENDPOINT_EFFORT_LIMIT = 4.9
ENDPOINT_EFFORT_RATE = 1.0


@dataclasses.dataclass(frozen=True)
class Motor:
    logical: int
    can_id: int
    sign: float
    offset: float
    pmin: float
    pmax: float
    vmin: float
    vmax: float
    tmin: float
    tmax: float
    kp: float
    kd: float


def configuration():
    root = ET.parse(ROOT / "ros2_ws/src/dori_hardware/config/cubemars_mit.urdf.xacro").getroot()
    hardware = root.find("ros2_control/hardware")
    settings = {p.attrib["name"]: p.text for p in hardware.findall("param")}
    if settings["protocol_mode"] != "mit" or settings["can_interface"] != "can1":
        raise ValueError("Expected calibrated MIT hardware on can1")
    joints = {j.attrib["name"]: j for j in root.findall("ros2_control/joint")}
    motors = []
    for logical, name, expected_id in ((1, "left_wheel_joint", 2), (2, "right_wheel_joint", 1)):
        p = {v.attrib["name"]: float(v.text) for v in joints[name].findall("param")}
        if p["can_id"] != expected_id or p["direction_sign"] not in (-1, 1):
            raise ValueError("Unexpected wheel ID/direction mapping")
        motors.append(Motor(logical, expected_id, p["direction_sign"], p["enc_off"],
                            p["mit_p_min"], p["mit_p_max"], p["mit_v_min"], p["mit_v_max"],
                            p["mit_t_min"], p["mit_t_max"], p["mit_pos_kp"], p["mit_pos_kd"]))
    return motors


def quantize(value, minimum, maximum, bits):
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("MIT command outside calibrated wire range")
    return int((value - minimum) * ((1 << bits) - 1) / (maximum - minimum))


def command(motor, position=0.0, velocity=0.0, kp=0.0, kd=0.0, torque_ff=0.0):
    p = quantize(position * motor.sign + motor.offset, motor.pmin, motor.pmax, 16)
    v = quantize(velocity * motor.sign, motor.vmin, motor.vmax, 12)
    k = quantize(kp, 0, 500, 12)
    d = quantize(kd, 0, 5, 12)
    torque = quantize(torque_ff * motor.sign, motor.tmin, motor.tmax, 12)
    payload = bytes((p >> 8, p & 255, v >> 4, ((v & 15) << 4) | (k >> 8),
                     k & 255, d >> 4, ((d & 15) << 4) | (torque >> 8), torque & 255))
    return FRAME.pack(motor.can_id, 8, payload)


def decode(motor, can_id, data):
    if can_id != motor.can_id or len(data) != 8 or data[0] != motor.can_id:
        return None
    p = (data[1] << 8) | data[2]
    v = (data[3] << 4) | (data[4] >> 4)
    t = ((data[4] & 15) << 8) | data[5]
    position = (p * (motor.pmax - motor.pmin) / 65535 + motor.pmin - motor.offset) * motor.sign
    return dict(position=position,
                velocity=(v * (motor.vmax - motor.vmin) / 4095 + motor.vmin) * motor.sign,
                torque=(t * (motor.tmax - motor.tmin) / 4095 + motor.tmin) * motor.sign,
                # AK driver manual V1.0.18, p.68: MIT temperature = byte - 40.
                temperature=data[6] - 40, temperature_raw=data[6], error=data[7],
                raw_feedback=data.hex())


def trajectory(elapsed, distance=math.pi, speed_deg_s=10.0):
    if not math.isfinite(distance):
        raise ValueError("Trajectory distance must be finite")
    if distance == 0:
        return 0.0, 0.0, 0.0
    direction = 1.0 if distance > 0 else -1.0
    distance = abs(distance)
    if not math.isfinite(speed_deg_s) or not 0 < speed_deg_s <= 25:
        raise ValueError("Trial speed must be within 0..25 degrees/s")
    speed, accel = math.radians(speed_deg_s), math.radians(20)
    ta = min(speed / accel, math.sqrt(distance / accel))
    speed = accel * ta
    duration = distance / speed + ta
    if elapsed <= 0:
        return 0.0, 0.0, duration
    if elapsed < ta:
        return direction * 0.5 * accel * elapsed ** 2, direction * accel * elapsed, duration
    if elapsed < duration - ta:
        return direction * (0.5 * accel * ta ** 2 + speed * (elapsed - ta)), direction * speed, duration
    if elapsed < duration:
        remaining = duration - elapsed
        return direction * (distance - 0.5 * accel * remaining ** 2), direction * accel * remaining, duration
    return direction * distance, 0.0, duration


def motion_plan(motors, round_trip_degrees=None):
    if round_trip_degrees is None:
        return [("outbound", m, 180.0) for m in motors]
    if len(round_trip_degrees) != len(motors) or any(
            not math.isfinite(angle) or not 0 <= angle <= 185 for angle in round_trip_degrees):
        raise ValueError("Return angles must be finite and within 0..185 degrees")
    return ([("zero", m, 0.0) for m in motors] +
            [("return", m, angle) for m, angle in zip(motors, round_trip_degrees)])


def comparison_plan(motors, return_degrees, speeds):
    if not 2 <= len(speeds) <= 15 or any(speed not in (10, 15, 20, 25) for speed in speeds):
        raise ValueError("Comparison requires two to fifteen rounds at 10, 15, 20 or 25 degrees/s")
    base = motion_plan(motors, return_degrees)
    # Align to the same endpoints before the measured rounds begin.
    plan = [("align", m, angle) for m, angle in zip(motors, return_degrees)]
    for index, _ in enumerate(speeds, 1):
        plan.extend((f"round{index}_{phase}", m, angle) for phase, m, angle in base)
    return plan


def correction_events(points, target_deg):
    """Count observable post-ramp correction movements from (time, degrees).

    Ignore <0.2-degree excursions and motion entirely within the arrival
    window. A half-second window spanning <=0.03 degree is a stop. Continuing
    motion counts once; a new >=0.2-degree reversal counts as a new movement.
    These are physical movement episodes, not 100 Hz PI update commands.
    """
    if not points or all(abs(p - target_deg) <= 1 for _, p in points):
        return []
    window = deque()
    anchor_at, anchor = points[0]
    peak_at, peak = anchor_at, anchor
    moving = False
    direction = 0
    events = []
    for stamp, position in points:
        window.append((stamp, position))
        # Retain a sample at or before the 0.5-second boundary.
        while len(window) > 1 and window[1][0] <= stamp - 0.5:
            window.popleft()
        if not moving:
            delta = position - anchor
            if abs(delta) >= 0.2:
                if max(abs(anchor-target_deg), abs(position-target_deg)) > 1:
                    direction = 1 if delta > 0 else -1
                    events.append(dict(start_s=anchor_at, detected_s=stamp,
                                       from_deg=anchor, to_deg=position, direction=direction,
                                       reason="post_ramp" if not events else "restart"))
                    moving = True
                    peak_at, peak = stamp, position
                else:
                    anchor_at, anchor = stamp, position
        else:
            events[-1]["end_s"], events[-1]["to_deg"] = stamp, position
            if direction * (position - peak) > 0:
                peak_at, peak = stamp, position
            elif direction * (position - peak) <= -0.2:
                if max(abs(peak-target_deg), abs(position-target_deg)) > 1:
                    events[-1]["end_s"], events[-1]["to_deg"] = peak_at, peak
                    direction *= -1
                    events.append(dict(start_s=peak_at, detected_s=stamp, end_s=stamp,
                                       from_deg=peak, to_deg=position, direction=direction,
                                       reason="reversal"))
                    peak_at, peak = stamp, position
            span = max(p for _, p in window) - min(p for _, p in window)
            if stamp-window[0][0] >= 0.5 and span <= 0.03:
                moving = False
                anchor_at, anchor = stamp, position
    return events


def write_report(path, report):
    """Compact atomic checkpoints avoid long CAN pauses and partial reads."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, separators=(",", ":")) + "\n")
    temporary.replace(path)


def leg_metrics(samples, motor_id, reference_rad, started, ended, start_deg, target_deg,
                duration, speed):
    points = [s for s in samples if s["motor"] == motor_id and started <= s["received_at"] <= ended]
    after_ramp = [s for s in points if s["received_at"] >= started + duration]
    if not after_ramp:
        raise ValueError("No feedback after the planned deceleration end")
    relative = lambda s: math.degrees(s["position"] - reference_rad)
    first = after_ramp[0]
    first_entry = next((s for s in points if abs(relative(s) - target_deg) <= 1), None)
    direction = 1 if target_deg >= start_deg else -1
    corrections = correction_events([(s["received_at"]-started, relative(s)) for s in after_ramp], target_deg)
    trace, previous = [], -math.inf
    for s in points:
        if s["received_at"] - previous >= 0.05 or s is points[-1]:
            trace.append([s["received_at"] - started, relative(s), s["torque"], s["temperature"]])
            previous = s["received_at"]
    return dict(motor=motor_id, speed_deg_s=speed, start_deg=start_deg, target_deg=target_deg,
                planned_duration_s=duration, elapsed_s=ended-started,
                correction_and_confirmation_s=max(0, ended-started-duration),
                ramp_end_error_deg=relative(first)-target_deg,
                ramp_end_feedback_delay_s=first["received_at"]-started-duration,
                first_entry_s=None if first_entry is None else first_entry["received_at"]-started,
                first_pass=all(abs(relative(s)-target_deg) <= 1 for s in after_ramp),
                correction_count=len(corrections), correction_events=corrections,
                overshoot_deg=max(0, max(direction*(relative(s)-target_deg) for s in points)),
                reached_deg=relative(points[-1]),
                start_temperature_c=points[0]["temperature"], end_temperature_c=points[-1]["temperature"],
                peak_abs_effort=max(abs(s["torque"]) for s in points),
                trace_columns=["elapsed_s", "relative_deg", "effort", "temperature_c"], trace=trace)


def settling_gain(normal, final, elapsed_after_ramp):
    """Blend endpoint stiffness over one second, without changing the target."""
    return normal + (final - normal) * min(1.0, max(0.0, elapsed_after_ramp))


def endpoint_integral(value, error_rad, dt, moving=False):
    """Bounded, slew-limited friction correction in configured MIT torque units.

    Only integrate after the position ramp, or for an inactive held wheel.
    During travel, smoothly unwind the stored correction instead of carrying
    reverse-direction holding effort into the next move. No encoder/goal bias.
    """
    dt = min(0.05, max(0.0, dt))
    if moving:
        change = -value
    elif abs(error_rad) <= math.radians(0.2):
        change = 0.0
    else:
        change = 20.0 * error_rad * dt
    change = max(-ENDPOINT_EFFORT_RATE * dt, min(ENDPOINT_EFFORT_RATE * dt, change))
    return max(-ENDPOINT_EFFORT_LIMIT, min(ENDPOINT_EFFORT_LIMIT, value + change))


class Trial:
    def __init__(self, motors):
        self.motors = motors
        self.by_id = {m.can_id: m for m in motors}
        self.bus = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        filters = b"".join(struct.pack("=II", m.can_id, 0xC00007FF) for m in motors)
        self.bus.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER, filters)
        self.bus.bind(("can1",))
        self.bus.setblocking(False)
        self.states, self.seen, self.enabled = {}, {}, set()
        self.samples = []

    def send(self, frame):
        deadline = time.monotonic() + 0.01
        while True:
            try:
                if self.bus.send(frame) != FRAME.size:
                    raise OSError("Short CAN write")
                return
            except OSError as error:
                if error.errno not in (4, 11, 105) or time.monotonic() >= deadline:
                    raise
                select.select([], [self.bus], [], 0.001)

    def special(self, motor, last_byte):
        if last_byte not in (0xFC, 0xFD):
            raise ValueError("Only enable/disable permitted, never encoder reset")
        self.send(FRAME.pack(motor.can_id, 8, b"\xff" * 7 + bytes([last_byte])))

    def receive(self, check_faults=True):
        for _ in range(400):
            try:
                frame, _, flags, _ = self.bus.recvmsg(FRAME.size)
            except BlockingIOError:
                break
            if len(frame) != FRAME.size or flags & socket.MSG_DONTROUTE:
                continue
            can_id, size, data = FRAME.unpack(frame)
            motor = self.by_id.get(can_id)
            if motor is None:
                continue
            state = decode(motor, can_id, data[:size])
            if state is None:
                continue
            state["received_at"] = time.monotonic()
            self.states[motor.logical] = state
            self.seen[motor.logical] = self.seen.get(motor.logical, 0) + 1
            self.samples.append(dict(motor=motor.logical, **state))
            if check_faults and (state["error"] or state["temperature"] >= 80):
                raise RuntimeError(f"Motor {motor.logical} fault/temperature: {state}")

    def fresh(self):
        now = time.monotonic()
        return all(m.logical in self.states and
                   now - self.states[m.logical]["received_at"] < 0.25 for m in self.motors)

    def position_stable(self, motor_id):
        cutoff = time.monotonic() - 0.2
        recent = [s["position"] for s in self.samples[-100:]
                  if s["motor"] == motor_id and s["received_at"] >= cutoff]
        return len(recent) >= 10 and max(recent) - min(recent) <= math.radians(0.5)

    def measured_velocity(self, motor_id):
        recent = [s for s in self.samples[-100:] if s["motor"] == motor_id]
        if not recent:
            return 0.0
        last = recent[-1]
        earlier = [s for s in recent if last["received_at"] - s["received_at"] >= 0.05]
        if not earlier:
            return 0.0
        first = earlier[-1]
        return (last["position"] - first["position"]) / (last["received_at"] - first["received_at"])

    def stop(self):
        errors = []
        # Bounded damping phase, then explicitly disable only the two test IDs.
        for _ in range(10):
            for m in self.motors:
                if m.logical in self.enabled:
                    try:
                        self.send(command(m, kp=0.0, kd=3.0))
                    except OSError as error:
                        errors.append(str(error))
            try:
                # Already stopping: keep telemetry without counting a repeated
                # temperature/fault observation as a failed stop transmission.
                self.receive(check_faults=False)
            except OSError as error:
                errors.append(str(error))
            time.sleep(0.01)
        for _ in range(3):
            for m in self.motors:
                if m.logical in self.enabled:
                    try:
                        self.special(m, 0xFD)
                    except OSError as error:
                        errors.append(str(error))
            time.sleep(0.01)
        return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--execute", action="store_true")
    action.add_argument("--observe", action="store_true", help="Receive for one second without transmitting")
    action.add_argument("--query-disabled", action="store_true",
                        help="Request feedback with zero gains while keeping the wheels disabled")
    parser.add_argument("--position-kp", type=float, choices=(30.0, 45.0),
                        help="Use the existing normal (30) or precise (45) transform position gain")
    parser.add_argument("--settle-kp", type=float, choices=(45.0, 60.0),
                        help="Ramp to this position gain over one second after each motion ends")
    parser.add_argument("--position-tolerance-deg", type=float, choices=(1.0,), default=1.0,
                        help="Endpoint tolerance is one degree for every motor")
    parser.add_argument("--speed-deg-s", type=float, choices=(10.0, 15.0, 20.0, 25.0), default=15.0)
    parser.add_argument("--hold-position", action="store_true",
                        help="Continue closed-loop holding after completion until interrupted")
    parser.add_argument("--reference-file", type=Path, help="Resume from previously captured trial zeros")
    parser.add_argument("--resume-file", type=Path,
                        help="Continue the unfinished legs of the same motion plan and saved reference")
    parser.add_argument("--round-trip-deg", type=float, nargs=2, metavar=("MOTOR1", "MOTOR2"),
                        help="Move both wheels to the saved zero, then to these relative angles")
    parser.add_argument("--compare-speeds", type=float, nargs="+", choices=(10.0, 15.0, 20.0, 25.0),
                        help="Run identical round trips in this speed order, preceded by endpoint alignment")
    parser.add_argument("--output", type=Path, default=Path("/tmp/dori_bldc_180_trial.json"))
    args = parser.parse_args()
    motors = configuration()
    if args.round_trip_deg is not None and (not args.execute or not args.reference_file):
        parser.error("--round-trip-deg requires --execute and --reference-file")
    if args.hold_position and not args.execute:
        parser.error("--hold-position requires --execute")
    plan = motion_plan(motors, args.round_trip_deg)
    if args.compare_speeds:
        if not args.execute or args.round_trip_deg is None or not args.reference_file or args.resume_file:
            parser.error("--compare-speeds requires execute, reference and round trip; cannot resume")
        plan = comparison_plan(motors, args.round_trip_deg, args.compare_speeds)
    completed_before = []
    if args.resume_file:
        if not args.execute or not args.reference_file:
            parser.error("--resume-file requires --execute and --reference-file")
        prior = json.loads(args.resume_file.read_text())
        saved_reference = json.loads(args.reference_file.read_text())["reference"]
        expected_plan = [dict(phase=phase, motor=m.logical, target_deg=angle) for phase, m, angle in plan]
        if prior["planned_moves"] != expected_plan or prior["reference"] != saved_reference:
            parser.error("Resume report must have the same targets, order, and original zero references")
        completed_before = prior["completed"]
        if len(completed_before) >= len(plan):
            parser.error("Resume report has no unfinished legs")
        for reached, expected in zip(completed_before, expected_plan):
            if any(reached[k] != v for k, v in expected.items()) or abs(
                    reached["relative_deg"] - expected["target_deg"]) > args.position_tolerance_deg:
                parser.error("Resume report contains a leg outside the requested endpoint tolerance")
    if args.query_disabled:
        saved = json.loads(args.reference_file.read_text())["reference"] if args.reference_file else {}
        for m in motors:
            if saved and (saved[str(m.logical)]["can_id"] != m.can_id or
                          not math.isfinite(saved[str(m.logical)]["angle_deg"])):
                raise ValueError("Reference file does not match these motors")
        trial = Trial(motors)
        try:
            for _ in range(10):
                for m in motors:
                    trial.special(m, 0xFD)
                    trial.send(command(m))  # Zero gains; never send enable or reset.
                time.sleep(0.02)
                trial.receive(check_faults=False)
            readings = {}
            for logical, state in trial.states.items():
                readings[logical] = dict(state, angle_deg=math.degrees(state["position"]))
                if saved:
                    readings[logical]["relative_deg"] = (math.degrees(state["position"])
                                                         - saved[str(logical)]["angle_deg"])
            print(json.dumps(dict(last_feedback=readings, received=trial.seen,
                                  enable_command_sent=False), indent=2))
            return 0 if trial.fresh() else 1
        finally:
            try:
                for m in motors:
                    trial.special(m, 0xFD)
            finally:
                trial.bus.close()
    if args.observe:
        trial = Trial(motors)
        try:
            until = time.monotonic() + 1.0
            while time.monotonic() < until:
                trial.receive(check_faults=False)
                time.sleep(0.01)
            print(json.dumps(dict(last_feedback=trial.states, received=trial.seen,
                                  transmitted_frames=0), indent=2))
        finally:
            trial.bus.close()
        return 0
    if not args.execute:
        print(json.dumps([dataclasses.asdict(m) for m in motors], indent=2))
        return 0

    def interrupt(_sig, _frame):
        raise KeyboardInterrupt("Trial interrupted")

    signal.signal(signal.SIGTERM, interrupt)
    report = dict(result="not_started", motors=[dataclasses.asdict(m) for m in motors],
                  reference={}, completed=list(completed_before), encoder_zero_command_sent=False,
                  resumed_from=str(args.resume_file) if args.resume_file else None,
                  temperature_encoding="unsigned_byte_minus_40_celsius",
                  planned_moves=[dict(phase=phase, motor=m.logical, target_deg=angle)
                                 for phase, m, angle in plan],
                  position_kp={m.logical: args.position_kp if args.position_kp is not None else m.kp
                               for m in motors},
                  settle_kp=args.settle_kp,
                  position_tolerance_deg=args.position_tolerance_deg,
                  speed_deg_s=args.speed_deg_s, pid=os.getpid(),
                  comparison_speeds=args.compare_speeds, legs=[],
                  correction_definition=dict(minimum_movement_deg=0.2, stop_window_s=0.5,
                                             stopped_span_deg=0.03, reversal_is_new=True,
                                             ignore_motion_entirely_within_one_degree=True),
                  endpoint_integral_limit=ENDPOINT_EFFORT_LIMIT,
                  endpoint_integral_rate=ENDPOINT_EFFORT_RATE,
                  position_kd=3.0)
    trial = Trial(motors)
    result = 1
    try:
        for m in motors:
            trial.send(command(m))  # Neutral setpoint before enabling.
            trial.enabled.add(m.logical)
            trial.special(m, 0xFC)
            trial.send(command(m, kd=3.0))
        started = time.monotonic()
        stationary_since = None
        while time.monotonic() - started < 2.0:
            for m in motors:
                trial.send(command(m, kd=3.0))
            trial.receive()
            if (trial.fresh() and all(trial.seen.get(m.logical, 0) >= 20 and
                    abs(trial.states[m.logical]["velocity"]) < SETTLE_VELOCITY and
                    trial.position_stable(m.logical) for m in motors)):
                if stationary_since is None:
                    stationary_since = time.monotonic()
                elif time.monotonic() - stationary_since >= 0.2:
                    break
            else:
                stationary_since = None
            time.sleep(0.01)
        if not trial.fresh() or any(trial.seen.get(m.logical, 0) < 20 for m in motors):
            raise RuntimeError(f"No fresh MIT feedback from both motors; IDs seen={list(trial.states)}")
        if stationary_since is None or time.monotonic() - stationary_since < 0.2:
            raise RuntimeError("Wheels did not settle before reference capture")
        reference = {m.logical: trial.states[m.logical]["position"] for m in motors}
        if args.reference_file:
            previous = json.loads(args.reference_file.read_text())["reference"]
            for m in motors:
                saved = previous[str(m.logical)]
                if saved["can_id"] != m.can_id or not math.isfinite(saved["angle_deg"]):
                    raise RuntimeError("Reference file does not match these motors")
                reference[m.logical] = math.radians(saved["angle_deg"])
        for m in motors:
            if abs(trial.states[m.logical]["velocity"]) > SETTLE_VELOCITY:
                raise RuntimeError(f"Motor {m.logical} moving before reference capture")
            for _, planned_motor, angle in plan:
                if planned_motor == m:
                    raw_target = (reference[m.logical] + math.radians(angle)) * m.sign + m.offset
                    if not m.pmin < raw_target < m.pmax:
                        raise RuntimeError(f"Motor {m.logical} target crosses MIT encoder boundary")
            report["reference"][m.logical] = dict(angle_deg=math.degrees(reference[m.logical]),
                                                   can_id=m.can_id, relative_zero_deg=0.0)
        print("REFERENCES " + json.dumps(report["reference"]), flush=True)
        report["result"] = "running"
        write_report(args.output, report)
        goals = {m.logical: trial.states[m.logical]["position"] for m in motors}
        gains = dict(report["position_kp"])
        corrections = {m.logical: 0.0 for m in motors}
        for phase, active, target_deg in plan[len(completed_before):]:
            leg_speed = args.speed_deg_s
            if args.compare_speeds and phase.startswith("round"):
                leg_speed = args.compare_speeds[int(phase.split("_")[0][5:]) - 1]
            leg_start = trial.states[active.logical]["position"]
            distance = reference[active.logical] + math.radians(target_deg) - leg_start
            if abs(distance) > math.radians(190):
                raise RuntimeError("Remaining travel outside the authorized interval")
            print(f"START {phase} motor {active.logical}, CAN {active.can_id}: "
                  f"target {target_deg:.3f}, remaining {math.degrees(distance):.2f} deg, speed {leg_speed}", flush=True)
            started = last_print = time.monotonic()
            sample_begin = len(trial.samples)
            last_update = started
            settled_at = None
            while True:
                now = time.monotonic()
                elapsed = now - started
                dt, last_update = now - last_update, now
                displacement, velocity, duration = trajectory(elapsed, distance, leg_speed)
                goals[active.logical] = leg_start + displacement
                if args.settle_kp is not None:
                    gains[active.logical] = settling_gain(report["position_kp"][active.logical],
                                                          args.settle_kp, elapsed - duration)
                trial.receive()
                if not trial.fresh():
                    raise RuntimeError("Wheel feedback expired")
                for m in motors:
                    state = trial.states[m.logical]
                    delta = state["position"] - reference[m.logical]
                    if not math.radians(-5) <= delta <= math.radians(185):
                        raise RuntimeError(f"Motor {m.logical} left authorized interval")
                    if abs(trial.measured_velocity(m.logical)) > 1.0 or abs(state["velocity"]) > 3.0:
                        raise RuntimeError(f"Motor {m.logical} exceeded trial speed threshold")
                    if abs(goals[m.logical] - state["position"]) > math.radians(25):
                        raise RuntimeError(f"Motor {m.logical} not following the position ramp")
                    corrections[m.logical] = endpoint_integral(
                        corrections[m.logical], goals[m.logical] - state["position"], dt,
                        moving=m == active and elapsed < duration)
                    trial.send(command(m, goals[m.logical], velocity if m == active else 0.0,
                                       gains[m.logical], 3.0, corrections[m.logical]))
                state = trial.states[active.logical]
                relative = math.degrees(state["position"] - reference[active.logical])
                if now - last_print >= (5.0 if args.compare_speeds else 1.0):
                    print(f"motor={active.logical} relative={relative:.2f} deg "
                          f"speed={math.degrees(state['velocity']):.2f} deg/s "
                          f"error={state['error']}", flush=True)
                    last_print = now
                at_goal = (elapsed >= duration and abs(relative - target_deg) <= args.position_tolerance_deg and
                           abs(state["velocity"]) < SETTLE_VELOCITY and
                           trial.position_stable(active.logical))
                if at_goal:
                    if settled_at is None:
                        settled_at = now
                    elif now - settled_at >= 0.5:
                        report["completed"].append(dict(phase=phase, motor=active.logical,
                                                        target_deg=target_deg, relative_deg=relative))
                        metrics = leg_metrics(trial.samples[sample_begin:], active.logical,
                                              reference[active.logical], started, time.monotonic(),
                                              math.degrees(leg_start-reference[active.logical]),
                                              target_deg, duration, leg_speed)
                        report["legs"].append(dict(phase=phase, **metrics))
                        print(f"REACHED {phase} motor {active.logical}: {relative:.2f} deg", flush=True)
                        if args.compare_speeds:
                            print("METRICS " + json.dumps({k: v for k, v in metrics.items()
                                                          if k not in ("trace", "trace_columns", "correction_events")}), flush=True)
                            # Small checkpoints: do not block CAN on a large raw-frame JSON dump.
                            write_report(args.output, report)
                            trial.samples = trial.samples[-1000:]
                        break
                else:
                    settled_at = None
                if elapsed > duration + 15:
                    raise RuntimeError(f"Motor {active.logical} timed out")
                time.sleep(0.01)
        report["result"] = "success"
        result = 0
        if args.hold_position:
            # Holding is explicit: keep the same feedback/fault checks live,
            # and let SIGINT/SIGTERM enter the normal damping/disable cleanup.
            report["result"] = "holding"
            last_update = time.monotonic()
            settled_since = None
            announced = False
            while True:
                now = time.monotonic()
                dt, last_update = now - last_update, now
                trial.receive()
                if not trial.fresh():
                    raise RuntimeError("Wheel feedback expired while holding")
                settled = True
                for m in motors:
                    state = trial.states[m.logical]
                    error = goals[m.logical] - state["position"]
                    relative = math.degrees(state["position"] - reference[m.logical])
                    if not -5 <= relative <= 185 or abs(error) > math.radians(5):
                        raise RuntimeError(f"Motor {m.logical} lost holding position")
                    if abs(trial.measured_velocity(m.logical)) > 1.0 or abs(state["velocity"]) > 3.0:
                        raise RuntimeError(f"Motor {m.logical} exceeded holding speed threshold")
                    corrections[m.logical] = endpoint_integral(corrections[m.logical], error, dt)
                    trial.send(command(m, goals[m.logical], 0.0, gains[m.logical], 3.0,
                                       corrections[m.logical]))
                    settled = settled and abs(error) <= math.radians(1) and trial.position_stable(m.logical)
                if settled:
                    if settled_since is None:
                        settled_since = now
                    elif not announced and now - settled_since >= 1.0:
                        report["holding_feedback"] = {
                            m.logical: dict(relative_deg=math.degrees(trial.states[m.logical]["position"]
                                                                       - reference[m.logical]),
                                            target_deg=math.degrees(goals[m.logical] - reference[m.logical]),
                                            **trial.states[m.logical]) for m in motors}
                        report["samples"] = trial.samples
                        write_report(args.output, report)
                        print("HOLDING " + json.dumps(report["holding_feedback"]), flush=True)
                        announced = True
                else:
                    settled_since = None
                # Keep the live controller's history bounded during long holds.
                if announced and len(trial.samples) > 1000:
                    trial.samples = trial.samples[-1000:]
                time.sleep(0.01)
    except (Exception, KeyboardInterrupt) as error:
        report.update(result="aborted", reason=str(error))
        print(f"ABORT: {error}", flush=True)
    finally:
        stop_errors = trial.stop()
        report["stop_errors"] = stop_errors
        if stop_errors:
            report["result"] = "aborted"
            result = 1
        report["last_feedback"] = trial.states
        report["samples"] = trial.samples
        write_report(args.output, report)
        print(json.dumps({k: v for k, v in report.items() if k not in ("samples", "legs")}), flush=True)
        trial.bus.close()
    return result


if __name__ == "__main__":
    raise SystemExit(main())

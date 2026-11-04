#!/usr/bin/env python3
"""Bounded Servo move or A/B round trip using the production ID 4 bridge.

Requires --execute and isolated ROS_DOMAIN_ID=87. No other motor driver is
launched. Return to 0 or a -270 target allows 272 degrees, a -180 target allows 182 degrees,
and other single moves allow 92 degrees.
--round-trip-180 runs -180 then 0.
--relative-deg moves +/-90 from measured feedback, with temporary trial limits.
The encoder is never zeroed. A fault aborts the sequence without a return move.
"""

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import signal
import time

import rclpy
from std_msgs.msg import Float64, Int32

from dori_hardware.motor4_servo_node import Motor4ServoNode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    motion = parser.add_mutually_exclusive_group()
    motion.add_argument("--target-deg", type=float, choices=(0.0, -90.0, -180.0, -270.0), default=-90.0)
    motion.add_argument("--round-trip-180", action="store_true")
    motion.add_argument("--relative-deg", type=float, choices=(-90.0, 90.0))
    parser.add_argument("--output", type=Path, default=Path("/tmp/dori_motor4_90_trial.json"))
    args = parser.parse_args()
    if not args.execute or os.environ.get("ROS_DOMAIN_ID") != "87":
        parser.error("Requires --execute and isolated ROS_DOMAIN_ID=87")

    def interrupt(_signal, _frame):
        raise KeyboardInterrupt("Trial interrupted")

    signal.signal(signal.SIGTERM, interrupt)
    relative = args.relative_deg is not None
    return_zero = not relative and not args.round_trip_180 and args.target_deg == 0.0
    # Relative trials first receive feedback without ownership, then narrow
    # limits to the measured start/target before any command is permitted.
    minimum, maximum, travel_limit = -94.0, 2.0, 92.0
    if relative:
        minimum, maximum = -3200.0, 3200.0
    elif return_zero:
        minimum, travel_limit = -274.0, 272.0
    elif args.round_trip_180:
        minimum, travel_limit = -182.0, 182.0
    elif args.target_deg in (-180.0, -270.0):
        minimum = args.target_deg - 2.0
        travel_limit = -args.target_deg + 2.0
    rclpy.init(args=["--ros-args", "-p", f"minimum_deg:={minimum}", "-p", f"maximum_deg:={maximum}"])
    node = Motor4ServoNode()
    targets = [] if relative else ([-180.0, 0.0] if args.round_trip_180 else [args.target_deg])
    report = dict(result="not_started", can_id=4, requested_targets_deg=targets, legs=[],
                  requested_delta_deg=args.relative_deg,
                  speed_limit_deg_s=10.0, acceleration_deg_s2=20.0,
                  software_current_cutoff=False, samples=[])
    result = 1

    def record(phase):
        state = node.guard.state
        if state is not None:
            report["samples"].append(dict(phase=phase, time=time.monotonic(), **asdict(state)))

    try:
        deadline = time.monotonic() + 2.0
        initial = []
        previous_feedback = None
        while time.monotonic() < deadline and len(initial) < 25:
            rclpy.spin_once(node, timeout_sec=0.02)
            if node.guard.feedback_at != previous_feedback and node.guard.state is not None:
                previous_feedback = node.guard.feedback_at
                state = node.guard.state
                if state.error or node.guard.faulted:
                    raise RuntimeError("Motor fault before motion")
                initial_minimum = -272 if return_zero else -92
                if ((not relative and not initial_minimum <= state.position_deg <= 2) or
                        abs(state.velocity_rad_s) > 0.03):
                    raise RuntimeError("Expected stationary motor in the A/half-turn test interval")
                if state.temperature_c >= 80:
                    raise RuntimeError("Initial temperature outside trial limits")
                initial.append(state.position_deg)
                record("before")
        if len(initial) < 25 or max(initial) - min(initial) > 0.5:
            raise RuntimeError("Insufficient stable feedback before motion")

        start = node.guard.state.position_deg
        if not relative and args.target_deg == -270.0 and abs(start) > 2:
            raise RuntimeError("270-degree outbound trial must start near 0 degrees")
        if return_zero:
            node.guard.minimum = min(start, 0.0) - 2
            node.guard.maximum = max(start, 0.0) + 2
        if relative:
            target = start + args.relative_deg
            if min(start, target) - 2 < -3200 or max(start, target) + 2 > 3200:
                raise RuntimeError("Relative move exceeds Servo feedback range")
            node.guard.minimum = min(start, target) - 2
            node.guard.maximum = max(start, target) + 2
            targets.append(target)
        if args.round_trip_180 and abs(start) > 2:
            raise RuntimeError("180-degree round trip must start at A near 0 degrees")
        report.update(start_deg=start, target_deg=targets[-1])
        node.action(Int32(data=2))
        if not node.guard.ready(time.monotonic()):
            raise RuntimeError("Motor guard not ready")
        report["result"] = "running"
        for leg, target in enumerate(targets, 1):
            leg_start = node.guard.state.position_deg
            distance = abs(target - leg_start)
            if not 2 < distance <= travel_limit:
                raise RuntimeError("Target outside authorized travel distance")
            low, high = min(leg_start, target) - 2, max(leg_start, target) + 2
            print(f"LEG {leg}: ID 4 Servo {leg_start:.1f} -> {target:.1f} deg, speed setting 10 deg/s", flush=True)
            started = time.monotonic()
            last_command = last_print = started
            settled_at = None
            node.command(Float64(data=target))
            while True:
                rclpy.spin_once(node, timeout_sec=0.01)
                now = time.monotonic()
                state = node.guard.state
                record(f"leg_{leg}")
                if node.guard.faulted or not node.guard.ready(now) or not node.guard.owned:
                    raise RuntimeError("Motor fault, stale feedback, or lost command ownership")
                if state.position_deg < low or state.position_deg > high:
                    raise RuntimeError("Motor left permitted travel interval")
                if abs(math.degrees(state.velocity_rad_s)) > 20:
                    raise RuntimeError("Motor exceeded trial speed threshold")
                if state.temperature_c >= 80:
                    raise RuntimeError("Motor exceeded temperature threshold")
                # Current remains telemetry. Actuator current-limit settings
                # are separate and are not changed by this trial runner.
                if now - started > distance / 10.0 + 8.0:
                    raise RuntimeError("Trial leg timed out")
                if now - started > 3 and abs(state.position_deg - leg_start) < 1:
                    raise RuntimeError("No measurable progress within 3 seconds")
                if now - last_command >= 0.05:
                    node.command(Float64(data=target))
                    last_command = now
                if now - last_print >= 1.0:
                    print(f"leg={leg} position={state.position_deg:.1f} deg "
                          f"speed={math.degrees(state.velocity_rad_s):.2f} deg/s "
                          f"current={state.current_a:.2f} A error={state.error}", flush=True)
                    last_print = now
                if abs(state.position_deg - target) <= 1.0 and abs(state.velocity_rad_s) < 0.03:
                    if settled_at is None:
                        settled_at = now
                    elif now - settled_at >= 0.5:
                        report["legs"].append(dict(target_deg=target, reached_deg=state.position_deg,
                                                   elapsed_sec=now - started))
                        print(f"REACHED: {state.position_deg:.1f} deg, leg {leg}", flush=True)
                        break
                else:
                    settled_at = None
        report["result"] = "reached"
    except (Exception, KeyboardInterrupt) as error:
        report.update(result="aborted", reason=str(error))
        print(f"ABORT: {error}", flush=True)
    finally:
        # ID 4 zero-speed command, including exception/interruption paths.
        node.stop()
        node.action(Int32(data=0))
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.02)
            record("stopped")
        final = node.guard.state
        report["stop_pending"] = node.stop_pending
        if final is not None:
            report["final"] = asdict(final)
            if "start_deg" in report:
                report["actual_delta_deg"] = final.position_deg - report["start_deg"]
        fresh = node.guard.feedback_at is not None and time.monotonic() - node.guard.feedback_at < 0.25
        if (report["result"] == "reached" and fresh and not node.stop_pending and
                not node.guard.faulted and final is not None and final.error == 0 and
                abs(final.position_deg - report["target_deg"]) <= 1 and
                abs(final.velocity_rad_s) < 0.03):
            report["result"] = "success"
            result = 0
        elif report["result"] == "reached":
            report.update(result="aborted", reason="Post-stop position/speed verification failed")
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({key: value for key, value in report.items() if key != "samples"}), flush=True)
        node.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return result


if __name__ == "__main__":
    raise SystemExit(main())

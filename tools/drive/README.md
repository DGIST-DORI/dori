# Drive measurement tools

These tools record/analyze the existing calibrated drive path. Run them from
the repository root after sourcing the environment in [AMM 20-12](../../docs/user/DORI-AMM.md).
Hardware preparation and actual robot launch are described in AMM 20-30/40-10.
The ROS workspace is `ros2_ws`; maps live at the repository root under `maps`.

- `record_manual_drive.py`: record manual-input response.
- `record_lidar_goal_response.py`: record the LiDAR/navigation response.
- `check_sensor_timing.py`: inspect sensor timing.
- `analyze_manual_drive.py`, `fit_drive_response.py`: analyze recorded response.
- `inspect_cubemars.py`: receive-only AK45-36 feedback inspection, defaulting to
  CAN ID 4 on `can1`. For example,
  `python3 tools/drive/inspect_cubemars.py --output /tmp/motor4-inspection.json`.
  It transmits no CAN frames and does not enable, zero or switch the motor.
  It reports `unknown` on missing, insufficient or mixed feedback; a silent
  motor must not be assumed to be in MIT mode. Its position is the protocol
  reading, not an automatically saved A calibration. The decoder follows the
  [AK driver manual V1.0.18](https://www.cubemars.com/data/cms/202605/ak-series-driver-manual-v1-0-18-for-ak-2-0-robotic-actuator.pdf).
  If SocketCAN is not configured, `--serial /dev/serial/by-id/<CANable2-device>`
  uses the adapter directly, verifying USB ID `16d0:117e` first. This opens the
  adapter at 1 Mbit/s, receives frames, then closes the channel; do not run it
  while another program owns that adapter. It still sends no CAN motor commands.

## Wheel BLDC 1 and 2

`trial_bldc_180.py --execute --position-kp 45` captures each current logical
joint angle and moves each wheel +180 degrees sequentially at 15 degrees/s
with 20 degrees/s² acceleration. `--speed-deg-s 10` selects the earlier speed.
<<<<<<< Updated upstream
`--speed-deg-s 20` or `--speed-deg-s 25` selects a faster trial with the same
=======
`--speed-deg-s` also accepts 20, 25, 30, 40, 50 and 60 for faster trials with the same
>>>>>>> Stashed changes
acceleration, gains, position tolerance and bounded endpoint correction.
Logical motor 1 is CAN ID 2 with positive direction; logical motor 2 is CAN ID 1
with negative direction. It uses the repository's MIT ranges and does not send
an encoder reset or command CAN ID 4. `--observe` only receives for one second.
The default without either action prints configuration without accessing CAN.

Use `--reference-file <previous-report.json>` to continue toward the same
original targets after an interrupted trial; choose a different `--output`
file to preserve the original references. The precise gain is the existing
transform Kp 45, with trial damping Kd 3. Every motor's position arrival
tolerance is now **1 degree**, including both BLDCs, DXL motor 3, Servo motor 4,
and A/B pose detection in `transform_params.yaml`. The motor 4 trial applies
the same tolerance to its post-stop check. Travel bounds and velocity checks
are separate from position arrival tolerance.

`--round-trip-deg <motor1-angle> <motor2-angle>` with `--execute` and
`--reference-file` moves both wheels to the original saved zero before
returning them to the specified relative angles. Negative travel uses the
same speed and acceleration limits. The trial accepts only
`--position-tolerance-deg 1`; reports retain the actual achieved angles.
`--settle-kp 60` optionally blends endpoint Kp to 60 over one second after
the motion ramp. A bounded endpoint integral compensates residual position
error without shifting the encoder reference or target. The correction is
limited to 4.9 configured MIT effort units, with a slew limit of 1 unit/s;
it unwinds during travel. Both stored zero references and distinct return
targets are preserved. `--resume-file <interrupted-report.json>` continues
unfinished legs only after validating the identical plan, zero references,
and the completed legs against the requested tolerance.

`--hold-position` continues feedback control after the final targets are
reached. SIGINT/SIGTERM, a motor fault, stale feedback, excessive temperature
or loss of holding position invokes damping and disable cleanup. The report
records the holding process PID and measured angles. Without this option,
the trial disables the motors and external load can shift their positions.
Use passive `--observe` while a controller is holding position.

On 2026-11-05 the 15-degree/s round trip reached the original zero at -0.97
and +0.92 degrees, then returned to the requested 181.365/183.101-degree
targets. Confirmed holding readings were 181.43 and 182.22 degrees, within
one degree on both motors; error codes were zero. The test used Kp45 during
travel, endpoint Kp60, Kd3 and the bounded integral correction.

For a controlled speed comparison, add `--compare-speeds 10 15 15 10` to
the same `--round-trip-deg`, reference, Kp45, endpoint Kp60 and hold command.
The runner first aligns both endpoints, then repeats the same round trip
with only the cruise speed changed. Per-leg records include the error at
commanded deceleration end, time spent correcting and confirming arrival,
first entry into the one-degree window, overshoot and motor temperature.
"First pass" requires all feedback from deceleration end through arrival
confirmation to stay within one degree. Records include a 20 Hz trace;
alignment legs are excluded from comparison statistics.
`analyze_bldc_speed_comparison.py <report.json> --output-dir <directory>`
exports per-move CSV data, grouped JSON statistics, and a comparison plot.
The report also counts observable correction movements after deceleration:
a movement of at least 0.2 degrees outside the arrival window counts once;
another movement after a 0.5-second stop (position span at most 0.03 degrees)
or a reversal of at least 0.2 degrees counts again. This is not the number of
100 Hz control updates. Sub-threshold correction may still occur with count
zero, so use the separate first-pass flag when assessing direct arrival.
For five round trips at each of 15, 20 and 25 degrees/s, use
`--compare-speeds 15 20 25 20 25 15 25 15 20 15 25 20 25 20 15`.
This interleaved schedule produces 60 measured one-way moves, five per
motor, speed and direction. The analysis additionally exports `rounds.csv`
with each round's times and correction counts, and arrival-time standard
deviations in `summary.json`. Missing counts in older reports remain unknown.
<<<<<<< Updated upstream
=======
To add five rounds each at 30 and 40 degrees/s, use
`--compare-speeds 30 40 40 30 40 30 30 40 40 30` with a new output file and
the same reference and return targets. Keep acceleration at 20 degrees/s²,
gains, correction counting and arrival criteria unchanged. The moving motor's
encoder-derived speed limit is the larger of 1 rad/s and 1.5 times the selected
speed (60, 75 and 90 degrees/s at the 40, 50 and 60-degree/s settings); inactive and held wheels
retain the 1 rad/s limit. Raw velocity, tracking, temperature and fault checks
remain unchanged. Use `--baseline-report` with the
archived 15/20/25 report to combine all five speeds without duplicating trials.
Repeat `--baseline-report` for multiple archived sources; source file names
remain attached to each measured leg and round.
For five rounds each at 50 and 60 degrees/s, use
`--compare-speeds 50 60 60 50 60 50 50 60 60 50`. With the same 20 degrees/s²
acceleration, a 180-degree move takes 6.1 seconds at 50 degrees/s and 6.0
seconds at 60 degrees/s before endpoint correction. The 60-degree/s profile
is triangular for exactly 180 degrees; it reaches peak speed at the midpoint.
>>>>>>> Stashed changes
Use `--compare-speeds 20 20` for two 20-degree/s rounds. The analysis tool's
`--baseline-report <earlier-comparison.json>` includes the earlier 10/15 data
and retains each move's source file; plots label the actual test order.

`--query-disabled --reference-file <report.json>` requests fresh feedback
using disable and zero-gain commands, without enabling or resetting either
motor. It reports relative angles even when a disabled motor no longer
publishes automatically. Use it only when no other controller owns the wheels.

MIT feedback temperature is `uint8(data[6]) - 40` °C (manual V1.0.18,
p.68); raw `0x50` (80) means 40 °C. Servo feedback uses signed int8 °C
directly. This distinction applies to the inspection tool, the BLDC trial,
and the ROS hardware driver's temperature state.

## Transform motor 4 (AK45-36)

Motor 4 uses CAN ID 4 in **Servo mode**. On 2026-11-04 the passive inspection
received 250 extended `0x2904` frames in five seconds, with position 0.0 degrees
and error 0. The replacement is excluded from Dynamixel commands and polling.
`system_real.launch.py` starts `motor4_servo_node` with
[`motor4_servo.yaml`](../../ros2_ws/src/dori_hardware/config/motor4_servo.yaml).
It publishes `/motor4/joint_states` and accepts output-shaft degrees on
`/motor4/position_cmd`; `/motor4/stop` requests zero speed.

The configured A reference is 0 degrees and B is -180 degrees, preserving the
old negative direction and the existing sequence order. The six motor 4 motion
steps are now -30 degrees each, and reverse for B to A. This direction is an
implementation assumption; physical travel has not been tested. To change it,
keep the transform travel, B reference and hardware angle limits consistent.
See [`transform_params.yaml`](../../ros2_ws/src/dori_control/config/transform_params.yaml).

Startup sends no motor command. Position commands require transform action
state 2, fresh fault-free feedback and an in-range target. The default speed is
10 degrees/s with acceleration 20 degrees/s². Loss of feedback or controller
heartbeat stops the owned motor and latches a system error. `read_only:=true`
disables all CAN transmission for reception checks.
Unchanged goals are also refreshed on CAN, rate-limited to 20 Hz, so the motor's
own communications timeout is not triggered while the ROS controller is alive.
Zero-speed stop ends active position holding; external load can change the
resting position once the motor's communications timeout expires.

`trial_motor4_90.py --execute --target-deg 0` performs a bounded return to A
(`--target-deg -90` tests the halfway position), after sourcing ROS and the
workspace and setting `ROS_DOMAIN_ID=87 ROS_LOCALHOST_ONLY=1`. It starts only
the dedicated motor 4 bridge, allows at most 92 degrees of travel and records
feedback to `/tmp/dori_motor4_90_trial.json` (override with `--output`). The
trial records current without a software current cutoff or exposure budget.
Motor faults, stale feedback, temperature, speed, travel and timeout checks
remain active. This does not alter the actuator's internal current limit or
command a fixed maximum torque. The 2026-11-04 return test reached 0 degrees
and rested at -0.9 degrees after stopping, with no motor error.
`--round-trip-180` instead runs -180 then 0 from A, allowing 182 degrees per
leg. It confirms each endpoint before reversing and aborts the entire sequence
on a fault. The
2026-11-04 round trip reached -180.0 and 0.0 degrees, then rested at -0.3 degrees
with no motor error.

If the adapter is present but `can1` is missing, identify its current
`/dev/serial/by-id` path and run `slcand` on that path (administrator access):

```bash
sudo slcand -o -s8 -t hw -S 3000000 /dev/serial/by-id/<CANable2-device> can1
sudo ip link set can1 up
```

Validation covers the protocol/command guard, repeated A/B target planning and
both transform nodes using simulated feedback. The integration check launches
no hardware drivers:

```bash
source /opt/ros/humble/setup.bash
source ros2_ws/install/local_setup.bash
ROS_DOMAIN_ID=86 ROS_LOCALHOST_ONLY=1 /usr/bin/python3 tests/integration/check_motor4_transform.py
```

Inspect each tool's `--help` before use. Recording a commanded drive experiment
requires the physical acceptance procedure; it is outside P0/P2 validation.
Calibration values and TTA behavior were not retuned by the package refactor.

[Package ownership](../../docs/dev/package-ownership.md) ·
[Validation scope](../../docs/dev/refactor-validation.md) ·
[Map handling](../../maps/README.md)

Runtime logs, local calibration overrides and build outputs remain outside Git.

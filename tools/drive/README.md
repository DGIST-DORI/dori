# Drive measurement tools

These tools record/analyze the existing calibrated drive path. Run them from
the repository root after sourcing the environment in [AMM 20-12](../../docs/user/DORI-AMM.md).
Hardware preparation and actual robot launch are described in AMM 20-30/40-10.
The ROS workspace is `ros2_ws`; maps live at the repository root under `maps`.

- `record_manual_drive.py`: record manual-input response.
- `record_lidar_goal_response.py`: record the LiDAR/navigation response.
- `check_sensor_timing.py`: inspect sensor timing.
- `analyze_manual_drive.py`, `fit_drive_response.py`: analyze recorded response.

Inspect each tool's `--help` before use. Recording a commanded drive experiment
requires the physical acceptance procedure; it is outside P0/P2 validation.
Calibration values and TTA behavior were not retuned by the package refactor.

[Package ownership](../../docs/dev/package-ownership.md) ·
[Validation scope](../../docs/dev/refactor-validation.md) ·
[Map handling](../../maps/README.md)

Runtime logs, local calibration overrides and build outputs remain outside Git.

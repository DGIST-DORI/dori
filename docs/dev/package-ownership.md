# DORI package names and ownership

**Status:** canonical after the 2026-10-27 namespace migration (AMM R3).
The workspace contains **24 ROS packages**. All nine former `robot_*` packages
have been renamed or merged into existing `dori_*` packages. Hardware calibration,
functional executable names and operational topic paths remain unchanged.

## Migration map

| Previous package | Current package | Responsibility |
|---|---|---|
| `robot_bringup` | `dori_hardware` | Physical launch, CAN/servo/IMU configuration and controller setup |
| `robot_drive` | `dori_drive` | Wheel control, normalized command scaling, watchdogs and diagnostic tools |
| `robot_error` | `dori_diagnostics` | Hardware/system error handling |
| `robot_input` | `dori_input` | Joystick, keyboard and explicitly selected virtual input tools |
| `robot_supervisor` | `dori_supervisor` | Manual/AUTO authority, emergency stop and transform gating |
| `robot_transform` | `dori_transform` | Physical transformation, stabilization and gimbal control |
| `robot_msgs` | `dori_msgs` | Five physical-control messages alongside four HRI/navigation actions |
| `robot_mapping` | `dori_mapping` | Metric LiDAR odometry, extrinsics and Cartographer configuration |
| `robot_navigation` | `dori_navigation` | Nav2 plugin/configuration, TTA bridge, map viewer and public action adapters |

`dori_hardware` now directly owns `system_real.launch.py`,
`system_real_with_imu.launch.py` and their configuration. Keeping these below
`dori_bringup` avoids a `bringup -> hardware -> bringup` package dependency cycle.
The old mapping wrapper was replaced with the actual odometry launch to prevent
self-inclusion after the merge.

`dori_navigation` is an `ament_cmake` package using `ament_cmake_python`. It
installs the native planner, the `dori_navigation` and `dori_web` Python modules,
and the `nav2_adapter`, `named_goal_adapter`, and `web_viewer.py` executables.
There is no second setup.py/resource identity for that package.

## Remaining package boundaries

| Package | Responsibility |
|---|---|
| `dori_bringup` | Top-level launch composition, HRI, optional perception and dashboard |
| `dori_bt` | BehaviorTree.CPP v3 session coordinator and ROS action clients |
| `dori_core` | Shared Python application contracts |
| `dori_dashboard` | Dashboard API, ROS/WebSocket composition and installed web assets |
| `dori_hri` | Wake word, STT, TTS and emotion I/O |
| `dori_llm` | Intent processing, knowledge and optional external LLM/RAG |
| `dori_observability` | Runtime metrics |
| `dori_perception` | Python person/gesture/expression/landmark processing |
| `dori_perception_camera` | Native camera adapter |

Device/vendor packages retain their established names: `cubemars_hardware`,
`imu_serial`, `sllidar_ros2`, `dynamixel_sdk`, `dynamixel_sdk_custom_interfaces`,
`dynamixel_sdk_examples`. ROS/Nav2 contract identifiers `robot_state_publisher`,
`robot_description`, `robot_base_frame`, `robot_radius`, `robot_model_type` are
external API names and must not be branded or renamed.

## Upgrade contract

- C++ headers/namespaces and Python imports now use the current package names.
  For example, `dori_msgs/msg/MitCommand` replaces the former motor message type.
  Fields are unchanged, but the DDS type identity changes; all clients using
  these custom messages must be rebuilt and restarted together.
- `/auto/cmd_vel`, `/drive/cmd_vel`, `/bldc_mit_speed_cmd`, `/dori/nav/*`, node
  names and drive calibration values remain stable.
- Helpers are `scripts/dori_stack.py`, `scripts/run_dori_control.sh`,
  `dori_bringup/dori_dev.launch.py`; the repository environment variable is
  `DORI_WS` and the mode argument of `robot.launch.py` is `dori_mode`.
- No old ROS package alias or old generated interface is installed. Historical
  evidence/legacy documentation intentionally retains the names it actually tested.
- Stop the affected stack, run `scripts/build.sh --clean`, source
  `scripts/env.sh` in a fresh shell, then follow [AMM 20-15](../user/DORI-AMM.md).
  The clean build archives old build/install/log artifacts under `.state`.

Acceptance checks cover the source/install package inventory, acyclic manifest
dependencies, native message serialization, merged navigation assets, launch
arguments and actual ROS drive/HRI/Nav2/web/mapping flows.

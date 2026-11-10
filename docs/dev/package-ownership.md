# DORI package ownership — R4

Canonical after the 2026-10-28 package consolidation. The workspace contains
**21 unique ROS packages**. Hardware calibration, runtime node/executable names,
topics, and `dori_msgs` messages/actions are unchanged by this consolidation.

## Consolidation map

| Previous package/component                                                            | Current owner                                 |
| ------------------------------------------------------------------------------------- | --------------------------------------------- |
| `dori_drive`, `dori_input`                                                            | `dori_control`                                |
| `dori_transform` transform manager/controller, fake joint state, transform parameters | `dori_control`                                |
| `dori_transform` DXL bridge/state publisher and DXL parameters                        | `dori_hardware`                               |
| `imu_serial` Python nodes                                                             | `dori_hardware`                               |
| `dori_error`                                                                          | `dori_diagnostics`                            |
| `cubemars_hardware`                                                                   | Same ROS identity; source under `third_party` |

`dori_control` installs 10 native executables, its headers under
`include/dori_control`, and drive/kinematics/odometry/transform configuration.
`dori_hardware` is an `ament_cmake` + `ament_cmake_python` package. It installs three
DXL executables (`dxl_driver_node`, `dxl_bridge_node`, `dxl_state_publisher_node`)
and five Python entry points: `motor4_servo_node`, `imu_node`, `body_pitch_node`,
`body_stabilizer_node`, `servo3_pitch_follower_node`. Python imports use
`dori_hardware.<module>`; there is no separate `imu_serial` package registration.

Physical system launch stays in `dori_hardware`. It depends on `dori_control`,
`dori_supervisor`, `dori_diagnostics` and device drivers. `dori_bringup` composes
that system with navigation/HRI/web. Lower packages do not depend on bringup.
`dori_navigation` reads kinematics from `dori_control`.

## Launch ownership

ROS 2 recommends grouping related nodes/configuration into reusable launch files
and including them from a short top-level launch. Each package installs its own
files from `launch/` to `share/<package>/launch`; launch files do not all belong in
bringup. See the official Humble documentation on
[large-project organization](https://github.com/ros2/ros2_documentation/blob/humble/source/Tutorials/Intermediate/Launch/Using-ROS2-Launch-For-Large-Projects.rst)
and [package integration](https://github.com/ros2/ros2_documentation/blob/humble/source/Tutorials/Intermediate/Launch/Launch-system.rst).

In DORI, `dori_bringup/launch/bringup.launch.py` is the standard user entrypoint.
It selects `robot.launch.py` by default or `desktop.launch.py` explicitly. These
profiles own deployment settings, subsystem composition and session readiness.
`visitor_mode` defaults to `true`, including standalone interaction. Loading a
map does not require changing it.

The launch audit found all five formerly `real`-named launch files in active use.
They are renamed by responsibility, with no compatibility aliases:

| Owner | Previous file | Current file | Responsibility and caller |
| --- | --- | --- | --- |
| `dori_hardware` | `real_hardware.launch.py` | `hardware.launch.py` | CAN/serial preflight and actuator/IMU configuration used by `robot.launch.py`; disables test inputs and wheel odometry |
| `dori_hardware` | `system_real_with_imu.launch.py` | `body_control.launch.py` | Actuation plus IMU/pitch estimation, stabilization and servo follower; included by `hardware.launch.py` and used by `scripts/run_dori_control.sh` |
| `dori_hardware` | `system_real.launch.py` | `actuation.launch.py` | Motor drivers, drive/transform controllers, safety supervisor and optional test inputs; included by `body_control.launch.py` |
| `dori_navigation` | `real_nav2.launch.py` | `nav2.launch.py` | Nav2 localization/lifecycle, drive bridge and DORI adapters; used by `robot.launch.py` and `scripts/run_navigation.sh` |
| `dori_navigation` | `real_navigation.launch.py` | `navigation_adapters.launch.py` | DORI public navigation actions backed by Nav2; included by `nav2.launch.py` |
| `dori_navigation/config` | `nav2_real.yaml` | `nav2_params.yaml` | Default Nav2 parameters, loaded by `nav2.launch.py` |

The three hardware layers are intentional: control-only operation and full robot
deployment reuse the same calibrated nodes. They stay in `dori_hardware` because
they compose the physical control subsystem. `hardware.launch.py` does not start
LiDAR, perception, navigation or HRI; the complete robot belongs to bringup.
The navigation launch files stay in `dori_navigation` with their adapters,
configuration and lifecycle logic.

Reusable application launches moved out of bringup:

| File | Previous owner | Current owner | Composition |
| --- | --- | --- | --- |
| `voice.launch.py` | `dori_bringup` | `dori_hri` | STT, LLM and TTS |
| `interaction.launch.py` | `dori_bringup` | `dori_bt` | Behavior tree executor and HRI emotion publisher |
| `perception.launch.py` | `dori_bringup` | `dori_perception` | Camera adapter, person detection and optional vision features |

Both deployment profiles include these same subsystem launches. Their package
manifests declare the launched packages as runtime dependencies; lower packages
do not import or depend on `dori_bringup`. Bringup passes deployment settings to
them as launch arguments.

The remaining launch locations already match their responsibilities:
`dori_control/launch/odometry.launch.py` is a standalone wheel-odometry utility;
`dori_mapping/launch/lidar_odometry.launch.py` is included by robot bringup;
`dori_mapping/launch/lidar_only_cartographer.launch.py` is the standalone mapping
workflow; `dori_dashboard/launch/dashboard.launch.py` composes the app services
for both profiles. They remain in place.

Rebuild the changed packages and source the overlay before using the new names.
Installation removes the old launch/config paths from existing overlays, also
when they are dangling symlinks. External commands referencing the previous
names must be updated; normal `ros2 launch dori_bringup bringup.launch.py ...`
commands continue to work.

## Package inventory

| Package                           | Responsibility                                                       |
| --------------------------------- | -------------------------------------------------------------------- |
| `dori_bringup`                    | Top-level launch composition                                         |
| `dori_control`                    | Drive, input and transformation control                              |
| `dori_hardware`                   | Physical launch/checks, DXL driver/bridges, CAN motor4, IMU and pitch |
| `dori_supervisor`                 | Manual/AUTO authority, stop and transform gating                     |
| `dori_diagnostics`                | Hardware/system error logging                                        |
| `dori_mapping`                    | LiDAR odometry, extrinsics and Cartographer                          |
| `dori_navigation`                 | Nav2 plugin/configuration, TTA bridge, public actions and map web UI |
| `dori_msgs`                       | Five control messages and four actions                               |
| `dori_bt`                         | HRI BehaviorTree.CPP v3 coordinator                                  |
| `dori_hri`                        | Wake word, STT, TTS and emotion I/O                                  |
| `dori_llm`                        | Intent, knowledge and optional LLM/RAG                               |
| `dori_core`                       | Shared application contracts                                         |
| `dori_dashboard`                  | HTTP API, ROS/WebSocket composition and installed dashboard          |
| `dori_observability`              | Runtime metrics                                                      |
| `dori_perception`                 | Person, gesture, expression and landmark processing                  |
| `dori_perception_camera`          | Optional native RealSense camera adapter                             |
| `cubemars_hardware`               | MIT CAN hardware plugin and CAN fault regression test                |
| `sllidar_ros2`                    | LiDAR device driver                                                  |
| `dynamixel_sdk`                   | Dynamixel SDK                                                        |
| `dynamixel_sdk_custom_interfaces` | Dynamixel interfaces                                                 |
| `dynamixel_sdk_examples`          | Upstream SDK examples only; not used by physical bringup              |

## Upgrade contract and validation

Update external launch package lookups, C++ include/namespace references and IMU
Python imports. Removed package names have no compatibility aliases. Existing
`dori_msgs` clients retain their DDS type identity. Clients still on the older
`robot_msgs` identity must follow the earlier message migration and rebuild.

Standard ROS/Nav2 identifiers such as `robot_state_publisher`,
`robot_description`, `robot_base_frame`, `robot_radius` and `robot_model_type`
remain unchanged. `/auto/cmd_vel` and `/drive/cmd_vel` remain normalized joystick
inputs; `/nav/cmd_vel` remains SI velocity input to the TTA bridge.

Launch with `ros2 launch` or the wrappers under `scripts/`, save maps with
`nav2_map_server map_saver_cli`, and use documented ROS/Web commands to stop.
Follow [AMM 20-15](../user/DORI-AMM.md) to archive old build/install/log artifacts
and create a clean overlay. [P0/P2 validation](refactor-validation.md) covers the
21-package graph, installed interfaces/executables/assets and launch resolution.
The existing full runtime regression suite still requires P1 migration work.

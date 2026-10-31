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
`dori_hardware` is an `ament_cmake` + `ament_cmake_python` package. It installs two
DXL executables and four Python entry points: `imu_node`, `body_pitch_node`,
`body_stabilizer_node`, `servo3_pitch_follower_node`. Python imports use
`dori_hardware.<module>`; there is no separate `imu_serial` package registration.

Physical system launch stays in `dori_hardware`. It depends on `dori_control`,
`dori_supervisor`, `dori_diagnostics` and device drivers. `dori_bringup` composes
that system with navigation/HRI/web. Lower packages do not depend on bringup.
`dori_navigation` reads kinematics from `dori_control`.

## Package inventory

| Package                           | Responsibility                                                       |
| --------------------------------- | -------------------------------------------------------------------- |
| `dori_bringup`                    | Top-level launch composition                                         |
| `dori_control`                    | Drive, input and transformation control                              |
| `dori_hardware`                   | Physical launch, DXL bridges, IMU and body/pitch processing          |
| `dori_supervisor`                 | Manual/AUTO authority, stop and transform gating                     |
| `dori_diagnostics`                | Hardware/system error logging                                        |
| `dori_mapping`                    | LiDAR odometry, extrinsics and Cartographer                          |
| `dori_navigation`                 | Nav2 plugin/configuration, TTA bridge, public actions and map web UI |
| `dori_msgs`                       | Five control messages and four actions                               |
| `dori_bt`                         | HRI BehaviorTree.CPP v4 coordinator                                  |
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
| `dynamixel_sdk_examples`          | Physical servo driver                                                |

## Upgrade contract and validation

Update external launch package lookups, C++ include/namespace references and IMU
Python imports. Removed package names have no compatibility aliases. Existing
`dori_msgs` clients retain their DDS type identity. Clients still on the older
`robot_msgs` identity must follow the earlier message migration and rebuild.

Standard ROS/Nav2 identifiers such as `robot_state_publisher`,
`robot_description`, `robot_base_frame`, `robot_radius` and `robot_model_type`
remain unchanged. `/auto/cmd_vel` and `/drive/cmd_vel` remain normalized joystick
inputs; `/nav/cmd_vel` remains SI velocity input to the TTA bridge.

Root scripts/preflight remain deleted. Launch with `ros2 launch`, save maps with
`nav2_map_server map_saver_cli`, and use documented ROS/Web commands to stop.
Follow [AMM 20-15](../user/DORI-AMM.md) to archive old build/install/log artifacts
and create a clean overlay. [P0/P2 validation](refactor-validation.md) covers the
21-package graph, installed interfaces/executables/assets and launch resolution.
The existing full runtime regression suite still requires P1 migration work.

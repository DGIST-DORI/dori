# Source provenance — 2026-09-08

- `src/robot_*`, `src/cubemars_hardware`, `src/DynamixelSDK`, `src/imu_serial`: `/home/dori/ros2_ws/src` at consolidation time. Includes the stable Dynamixel FTDI port fix. Desktop `src_1` is an older copy and was not used.
- `src/sllidar_ros2`: `/home/dori/Downloads/jetson_real_nav_smoke/.deps/sllidar_ws/src/sllidar_ros2`. Vendor source and license retained; prior build artifacts excluded.
- `src/robot_mapping`: `/home/dori/Downloads/lidar_only_slam_2026-07-24/lidar_only_slam`. Packaged for colcon; added wheel-odometry TF ownership mode.
- `src/robot_navigation`: `/home/dori/Downloads/jetson_remote_ros_bundle_2026-08-11/ros2_2d_slam`. Packaged for colcon; added real-sensor launch, removed external API-key file lookup.
- `tools/nav2_smoke`: `/home/dori/Downloads/jetson_real_nav_smoke`, without `.deps`, generated files or archives.
- `scripts/run_robot_control.sh`: desktop integrated launcher, changed to the new workspace and stable DXL device ID.

`docs/legacy` contains historical instructions with old host paths; use the root README for current commands. Original directories have not been deleted.

## Navigation integration update

- New archive: `/home/dori/Downloads/isaac_nav_llm_bundle_2026-09-08.zip`.
- Extracted original: `/home/dori/Downloads/isaac_nav_llm_bundle_2026-09-08`.
- Updated `robot_navigation` scripts, prompts, Isaac launch/config and `keyboard_Drive` assets from this bundle; real hardware launch and protocol bridges adapted in this workspace.
- Pre-update backup: `backups/before_nav_bundle_2026-09-08.tar.gz`.
- Canonical runtime instructions are now the root README and CONTRACTS.md. Historical docs under legacy and old launch-argument captures may describe earlier versions.

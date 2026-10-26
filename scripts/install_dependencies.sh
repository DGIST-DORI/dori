#!/usr/bin/env bash
# Resolve dependencies for the physical robot packages only.
set -eo pipefail
ROBOT_WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source /opt/ros/humble/setup.bash
cd "$ROBOT_WS"
rosdep install --from-paths src/robot_bringup src/robot_drive src/robot_error \
  src/robot_input src/robot_mapping src/robot_msgs src/robot_navigation \
  src/robot_supervisor src/robot_transform src/cubemars_hardware \
  src/imu_serial src/sllidar_ros2 src/DynamixelSDK \
  --ignore-src --rosdistro humble -r -y

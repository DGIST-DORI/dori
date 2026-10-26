#!/usr/bin/env bash
set -eo pipefail
ROBOT_WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Build only the real-robot dependency closure against the ROS underlay.
unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH LD_LIBRARY_PATH
source /opt/ros/humble/setup.bash
cd "$ROBOT_WS"
exec colcon build --symlink-install --parallel-workers 2 --packages-up-to robot_bringup robot_mapping robot_navigation "$@"

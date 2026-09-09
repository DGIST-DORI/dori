#!/usr/bin/env bash
set -eo pipefail
ROBOT_WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Build in a clean underlay; do not capture ros2_ws/Downloads in setup.bash.
unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH LD_LIBRARY_PATH
source /opt/ros/humble/setup.bash
cd "$ROBOT_WS"
exec colcon build --symlink-install --parallel-workers 2 "$@"

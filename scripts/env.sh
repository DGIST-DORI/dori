#!/usr/bin/env bash
# Source from launch helpers. No other workspace overlay is needed.
ROBOT_WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH LD_LIBRARY_PATH
source /opt/ros/humble/setup.bash
if [[ ! -f "$ROBOT_WS/install/setup.bash" ]]; then
    echo "Build first: $ROBOT_WS/scripts/build.sh" >&2
    return 1
fi
source "$ROBOT_WS/install/setup.bash"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

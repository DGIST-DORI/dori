#!/usr/bin/env bash
set -euo pipefail

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-73}"
export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-1}"
export ROS2CLI_NO_DAEMON=1

set +u
source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"
set -u

echo "Lifecycle states"
for node in /map_server /amcl /planner_server /controller_server /bt_navigator; do
  timeout 4 ros2 lifecycle get "$node" || true
done
echo
echo "Map metadata from live /map"
timeout 5 ros2 topic echo --once /map --field info || true
echo
echo "Input topics"
ros2 topic info /scan --verbose || true
ros2 topic info /odom --verbose || true
echo
echo "Real C1 frame-rate, delivery and latency (20 seconds)"
python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/monitor_scan_pipeline.py" --duration 20

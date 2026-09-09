#!/usr/bin/env bash
set -euo pipefail
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-73}"
export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-1}"
export ROS2CLI_NO_DAEMON=1
if [[ $# -ne 1 ]]; then
  echo "Usage: $0 'goal name'" >&2
  exit 2
fi
set +u
source "/opt/ros/${ROS_DISTRO:-humble}/setup.bash"
set -u
ros2 topic pub --once /named_goal std_msgs/msg/String "{data: '$1'}"

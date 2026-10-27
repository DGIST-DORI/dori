#!/usr/bin/env bash
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
exec /usr/bin/python3 "$ROBOT_WS/ros2_ws/src/robot_navigation/scripts/web_viewer.py" "$@"

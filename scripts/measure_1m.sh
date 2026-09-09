#!/usr/bin/env bash
# Starts real control + joystick + lidar + wheel odometry. User drives manually.
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
exec /usr/bin/python3 "$ROBOT_WS/scripts/robot_stack.py" measure "$@"

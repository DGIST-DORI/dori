#!/usr/bin/env bash
# One entry point: hardware, LiDAR odometry, navigation and both web viewers.
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
exec /usr/bin/python3 "$ROBOT_WS/scripts/autonomy.py" "$@"

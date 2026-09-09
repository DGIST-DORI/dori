#!/usr/bin/env bash
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
exec ros2 launch robot_navigation real_nav2.launch.py "$@"

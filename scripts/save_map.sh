#!/usr/bin/env bash
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
map_prefix="${1:-$ROBOT_WS/maps/robot_map}"
mkdir -p "$(dirname "$map_prefix")"
exec ros2 run nav2_map_server map_saver_cli -f "$map_prefix"

#!/usr/bin/env bash
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
map_prefix="${1:-$DORI_WS/maps/dori_map}"
mkdir -p "$(dirname "$map_prefix")"
# Cartographer can take longer than the upstream 2 s default to publish a map.
# Volatile durability accepts both volatile and transient-local publishers.
exec ros2 run nav2_map_server map_saver_cli -f "$map_prefix" -t /map \
    --free 0.25 --occ 0.65 --ros-args \
    -p save_map_timeout:=60.0 \
    -p map_subscribe_transient_local:=false

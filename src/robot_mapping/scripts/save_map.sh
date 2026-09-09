#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 /absolute/or/relative/map_prefix" >&2
    exit 1
fi

set +u
source /opt/ros/humble/setup.bash
set -u

ros2 run nav2_map_server map_saver_cli -f "$1"

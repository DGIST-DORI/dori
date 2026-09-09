#!/usr/bin/env bash
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
# Existing C1 driver is reused. Start it with run_lidar.sh in another terminal.
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/lidar_only_slam_mapping.lock"
flock -n 9 || { echo 'Mapping is already running.' >&2; exit 1; }
exec ros2 launch robot_mapping lidar_only_cartographer.launch.py \
    start_lidar_driver:=false use_wheel_odometry:=true "$@"

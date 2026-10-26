#!/usr/bin/env bash
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
[[ -r /dev/slamtec_c1 && -w /dev/slamtec_c1 ]] || {
    echo 'Check C1 connection and /dev/slamtec_c1 permissions.' >&2; exit 1;
}
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/lidar-c1-${UID}.lock"
flock -n 9 || { echo 'C1 launcher is already running.' >&2; exit 1; }
exec ros2 launch sllidar_ros2 sllidar_c1_launch.py \
    serial_port:=/dev/slamtec_c1 serial_baudrate:=460800 frame_id:=laser scan_mode:=Standard "$@"

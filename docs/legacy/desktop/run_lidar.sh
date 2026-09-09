#!/usr/bin/env bash
# RPLIDAR C1 driver only. Publishes sensor_msgs/msg/LaserScan on /scan.
set -eo pipefail
source /opt/ros/humble/setup.bash
source /home/dori/Downloads/jetson_real_nav_smoke/.deps/sllidar_ws/install/setup.bash
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
[[ -r /dev/slamtec_c1 && -w /dev/slamtec_c1 ]] || {
    echo '라이다 연결 및 /dev/slamtec_c1 접근 권한을 확인하세요.' >&2
    exit 1
}
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/lidar-c1-${UID}.lock"
flock -n 9 || { echo '라이다 실행 스크립트가 이미 실행 중입니다.' >&2; exit 1; }
exec ros2 launch sllidar_ros2 sllidar_c1_launch.py \
    serial_port:=/dev/slamtec_c1 serial_baudrate:=460800 \
    frame_id:=laser scan_mode:=Standard "$@"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROS_SETUP="/opt/ros/${ROS_DISTRO:-humble}/setup.bash"

# This smoke test is local-only. Isolation avoids malformed/incompatible DDS traffic
# from Isaac Sim, another ROS distro, or another computer on the LAN.
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-73}"
export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-1}"
export ROS2CLI_NO_DAEMON=1

LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/jetson_real_nav_smoke_domain_${ROS_DOMAIN_ID}.lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
  echo "Another smoke run is already active for ROS_DOMAIN_ID=$ROS_DOMAIN_ID" >&2
  exit 4
fi

set +u
source "$ROS_SETUP"
source "$ROOT_DIR/../../install/setup.bash"
set -u

if ! ros2 pkg prefix nav2_bringup >/dev/null 2>&1; then
  echo "Nav2 missing: sudo apt install ros-humble-navigation2 ros-humble-nav2-bringup" >&2
  exit 2
fi
if ! ros2 pkg prefix sllidar_ros2 >/dev/null 2>&1; then
  echo "Build robot_ws first (sllidar_ros2 missing)." >&2
  exit 2
fi

serial_port="${SLLIDAR_PORT:-}"
if [[ -z "$serial_port" ]]; then
  for candidate in /dev/slamtec_c1 /dev/serial/by-id/* /dev/ttyUSB0; do
    if [[ -e "$candidate" ]]; then serial_port="$candidate"; break; fi
  done
fi
if [[ -z "$serial_port" ]]; then
  echo "SLAMTEC C1 serial port not found. Connect it or set SLLIDAR_PORT=/dev/ttyUSBx" >&2
  exit 2
fi
if [[ ! -r "$serial_port" || ! -w "$serial_port" ]]; then
  echo "No access to $serial_port. Run ./scripts/install_udev_rule.sh once, then reconnect C1." >&2
  exit 2
fi

echo "Map: $ROOT_DIR/maps/isaac_saved_map.yaml (same pixels as original map_preview.png)"
echo "ROS isolation: DOMAIN_ID=$ROS_DOMAIN_ID, LOCALHOST_ONLY=$ROS_LOCALHOST_ONLY"
echo "Open another terminal and run: htop"
echo "Verify actual input/load in another terminal: bash $ROOT_DIR/scripts/check_runtime.sh"
echo "Mode: real C1 /scan + fake odom/TF + repeated Nav2 goals; no robot or motor output."
echo "Ctrl-C stops C1 and Nav2 together."

exec ros2 launch "$ROOT_DIR/launch/jetson_real_nav.launch.py" \
  map:="$ROOT_DIR/maps/isaac_saved_map.yaml" \
  params_file:="$ROOT_DIR/config/nav2_jetson.yaml" \
  points_file:="$ROOT_DIR/maps/isaac_saved_map.points.csv" \
  serial_port:="$serial_port" \
  "$@"

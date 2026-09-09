#!/usr/bin/env bash
set -eo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/scripts/start_mapping.sh" --mapping-odometry lidar \
  --imu-calibration "$ROOT/src/robot_mapping/config/imu_calibrated.yaml" "$@"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPS_WS="${SLLIDAR_DEPS_WS:-$ROOT_DIR/.deps/sllidar_ws}"
REPOSITORY_URL="https://github.com/Slamtec/sllidar_ros2.git"

set +u
source /opt/ros/humble/setup.bash
set -u

if ros2 pkg prefix sllidar_ros2 >/dev/null 2>&1; then
    exit 0
fi

if [[ ! -f "$DEPS_WS/src/sllidar_ros2/package.xml" ]]; then
    mkdir -p "$DEPS_WS/src"
    git clone --depth 1 "$REPOSITORY_URL" "$DEPS_WS/src/sllidar_ros2"
fi

(
    cd "$DEPS_WS"
    colcon build --symlink-install --paths src/sllidar_ros2
)

echo "SLLIDAR_SETUP=$DEPS_WS/install/setup.bash"

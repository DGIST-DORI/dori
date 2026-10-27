#!/usr/bin/env bash
set -eo pipefail
DORI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == --clean ]]; then
    shift
    # Package identities and generated DDS types cannot share an old overlay.
    # Preserve previous artifacts outside colcon's workspace discovery tree.
    DORI_BUILD_BACKUP="$DORI_ROOT/.state/build-backups/$(date +%Y%m%d_%H%M%S)_$$"
    mkdir -p "$DORI_BUILD_BACKUP"
    for artifact in build install log; do
        if [[ -e "$DORI_ROOT/ros2_ws/$artifact" ]]; then
            mv "$DORI_ROOT/ros2_ws/$artifact" "$DORI_BUILD_BACKUP/$artifact"
        fi
    done
    echo "Previous build artifacts archived: $DORI_BUILD_BACKUP"
elif compgen -G "$DORI_ROOT/ros2_ws/install/robot_*" > /dev/null || \
     compgen -G "$DORI_ROOT/ros2_ws/build/robot_*" > /dev/null; then
    echo 'Package migration requires a clean overlay. Run scripts/build.sh --clean.' >&2
    exit 1
fi
unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH LD_LIBRARY_PATH
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL
export PATH="$(/usr/bin/python3 -c 'import os; print(":".join(p for p in os.environ["PATH"].split(":") if "conda" not in p.lower()))')"
source /opt/ros/humble/setup.bash
export PATH="/usr/bin:/bin:$PATH"
source "$DORI_ROOT/.venv/bin/activate"
export PYTHONNOUSERSITE=1
cd "$DORI_ROOT/ros2_ws"
exec "$DORI_ROOT/.venv/bin/python" -m colcon build --symlink-install --parallel-workers 2 --cmake-args -DPython3_EXECUTABLE="$DORI_ROOT/.venv/bin/python" -DPYTHON_EXECUTABLE="$DORI_ROOT/.venv/bin/python" "$@"

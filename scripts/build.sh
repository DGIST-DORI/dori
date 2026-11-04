#!/usr/bin/env bash
set -eo pipefail
DORI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ -f /opt/ros/humble/setup.bash ]] || { echo 'Install ROS 2 Humble first.' >&2; exit 1; }
unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH LD_LIBRARY_PATH
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL
export PATH="$(/usr/bin/python3 -c 'import os; print(":".join(p for p in os.environ["PATH"].split(":") if "conda" not in p.lower()))')"
source /opt/ros/humble/setup.bash
export PYTHONNOUSERSITE=1
for tool in node npm; do
    command -v "$tool" >/dev/null || { echo 'Install Node.js 22.12+ and npm before building.' >&2; exit 1; }
done
if [[ ! -x "$DORI_ROOT/.venv/bin/python" ]]; then
    /usr/bin/python3 -m venv --system-site-packages "$DORI_ROOT/.venv"
fi
source "$DORI_ROOT/.venv/bin/activate"

# Colcon does not install all Python runtime dependencies. Keep the visitor
# gateway's Azure Speech SDK and the dashboard dependencies in the same venv.
cd "$DORI_ROOT"
python -m pip install -r "$DORI_ROOT/requirements-runtime.txt"
# Check before moving artifacts or invoking colcon's legacy develop cleanup.
python - <<'PY'
import sys
from importlib.metadata import version
from packaging.version import Version

installed = Version(version('setuptools'))
if not Version('70.3.0') <= installed < Version('80'):
    sys.exit(
        f'Unsupported setuptools {installed} for Humble colcon. '
        'From the repository root, run: '
        '.venv/bin/python -m pip install -c constraints-robot.txt "setuptools>=70.3.0,<80"'
    )
PY
# setup.py collects both web trees at build time. Fail before archiving a clean
# overlay if dependency installation or either frontend build fails.
(
    cd "$DORI_ROOT/web"
    npm ci --include=dev
    npm run build
    npm run build:visitor
)
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
cd "$DORI_ROOT/ros2_ws"
exec "$DORI_ROOT/.venv/bin/python" -m colcon build --symlink-install --parallel-workers 2 --cmake-args -DBUILD_TESTING=ON -DPython3_EXECUTABLE="$DORI_ROOT/.venv/bin/python" -DPYTHON_EXECUTABLE="$DORI_ROOT/.venv/bin/python" "$@"

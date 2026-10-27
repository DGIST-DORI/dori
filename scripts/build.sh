#!/usr/bin/env bash
set -eo pipefail
DORI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH LD_LIBRARY_PATH
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL
export PATH="$(/usr/bin/python3 -c 'import os; print(":".join(p for p in os.environ["PATH"].split(":") if "conda" not in p.lower()))')"
source /opt/ros/humble/setup.bash
export PATH="/usr/bin:/bin:$PATH"
source "$DORI_ROOT/.venv/bin/activate"
export PYTHONNOUSERSITE=1
cd "$DORI_ROOT/ros2_ws"
exec "$DORI_ROOT/.venv/bin/python" -m colcon build --symlink-install --parallel-workers 2 --cmake-args -DPython3_EXECUTABLE="$DORI_ROOT/.venv/bin/python" -DPYTHON_EXECUTABLE="$DORI_ROOT/.venv/bin/python" "$@"

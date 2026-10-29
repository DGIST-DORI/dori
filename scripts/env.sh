#!/usr/bin/env bash
# Source from launch helpers. No other workspace overlay is needed.
DORI_WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH LD_LIBRARY_PATH
unset CONDA_PREFIX CONDA_DEFAULT_ENV CONDA_SHLVL
export PATH="$(/usr/bin/python3 -c 'import os; print(":".join(p for p in os.environ["PATH"].split(":") if "conda" not in p.lower()))')"
source /opt/ros/humble/setup.bash
if compgen -G "$DORI_WS/ros2_ws/install/robot_*" > /dev/null; then
    echo 'Old package overlay detected. Run scripts/build.sh --clean, then source scripts/env.sh.' >&2
    return 1
fi
if [[ ! -f "$DORI_WS/ros2_ws/install/setup.bash" ]]; then
    echo "Build first: $DORI_WS/scripts/build.sh" >&2
    return 1
fi
source "$DORI_WS/ros2_ws/install/setup.bash"
export DORI_WS
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"

# Humble binary extensions require the Ubuntu Python ABI, not a user Python 3.13.
if [[ -f "$DORI_WS/.venv/bin/activate" ]]; then
    source "$DORI_WS/.venv/bin/activate"
    export PYTHONPATH="$DORI_WS/.venv/lib/python3.10/site-packages:${PYTHONPATH:-}"
else
    export PATH="/usr/bin:$PATH"
fi

export PYTHONNOUSERSITE=1

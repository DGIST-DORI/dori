#!/usr/bin/env bash
# One-time installation on Ubuntu 22.04 with the ROS Humble apt source configured.
set -eo pipefail
export PYTHONNOUSERSITE=1
DORI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
with_voice=true
with_vision=false
for arg in "$@"; do
    case "$arg" in
        --no-voice) with_voice=false ;;
        --vision) with_vision=true ;;
        *) echo 'Usage: install_dependencies.sh [--no-voice] [--vision]' >&2; exit 2 ;;
    esac
done
[[ -f /opt/ros/humble/setup.bash ]] || { echo 'Install ROS 2 Humble first.' >&2; exit 1; }
sudo apt-get update
sudo apt-get install -y python3.10-venv python3-pip python3-rosdep \
    python3-colcon-common-extensions python3-serial python3-numpy python3-scipy python3-pil \
    libportaudio2 portaudio19-dev ffmpeg mpg123 can-utils nlohmann-json3-dev \
    ros-humble-navigation2 ros-humble-nav2-bringup ros-humble-cartographer-ros \
    ros-humble-rosbridge-server ros-humble-behaviortree-cpp-v3
source /opt/ros/humble/setup.bash
if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then sudo rosdep init; fi
rosdep update --rosdistro humble
rosdep install --from-paths "$DORI_ROOT/ros2_ws/src" --ignore-src --rosdistro humble -r -y
/usr/bin/python3 -m venv --system-site-packages "$DORI_ROOT/.venv"
"$DORI_ROOT/.venv/bin/python" -m pip install -r "$DORI_ROOT/requirements-runtime.txt"
if [[ "$with_voice" == true ]]; then "$DORI_ROOT/scripts/prepare_voice.sh"; fi
if [[ "$with_vision" == true ]]; then
    "$DORI_ROOT/.venv/bin/python" -m pip install -c "$DORI_ROOT/constraints-robot.txt" -r "$DORI_ROOT/ros2_ws/src/dori_perception/requirements.txt"
fi
printf 'Dependencies installed. Next: cd %q/web && npm ci && npm run build; then scripts/build.sh\n' "$DORI_ROOT"

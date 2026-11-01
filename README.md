<br>
<p align="center">
  <img
    src="https://raw.githubusercontent.com/DGIST-DORI/dori/master/web/src/assets/logo/logo-full.svg"
    alt="dori logo"
    width="300">
</p>
<br>
<div align="center">

  <a href="">![GitHub commit activity](https://img.shields.io/github/commit-activity/w/DGIST-DORI/dori)</a>
  <a href="">![GitHub last commit](https://img.shields.io/github/last-commit/DGIST-DORI/dori)</a>
  <a href="">![GitHub repo size](https://img.shields.io/github/repo-size/DGIST-DORI/dori)</a>
  <br>
  <a href="">[![CodeQL Advanced](https://github.com/DGIST-DORI/dori/actions/workflows/codeql.yml/badge.svg)](https://github.com/DGIST-DORI/dori/actions/workflows/codeql.yml)</a>
  <a href="">[![Dependency review](https://github.com/DGIST-DORI/dori/actions/workflows/dependency-review.yml/badge.svg)](https://github.com/DGIST-DORI/dori/actions/workflows/dependency-review.yml)</a>
  <br>
  <a href="">[![Contributor Covenant](https://img.shields.io/badge/Contributor%20Covenant-v2.0%20adopted-hotpink.svg)](CODE_OF_CONDUCT.md)</a>
  <a href="">![Discord](https://img.shields.io/discord/1416157037695598753)</a>
  
</div>

# DORI

[DORI](https://dgist-dori.xyz) (DGIST O-shaped Robot for Interaction, stylized as *Dori*) is a spherical campus guide robot capable of navigating diverse campus environments while providing LLM-powered voice interaction.

> UGRP 2026 — DGIST

## Installation

### Prerequisites

- JetPack 6 (for Jetson)
- Ubuntu 22.04
- ROS2 Humble
- Python 3.10+
- CUDA 11+ (for Jetson or GPU workstation)

### 1. Install System Dependencies

```bash
sudo apt update
sudo apt install -y git build-essential python3.10-venv python3-pip python3-rosdep \
  python3-colcon-common-extensions python3-vcstool libportaudio2 portaudio19-dev \
  ffmpeg mpg123 can-utils nlohmann-json3-dev \
  ros-humble-navigation2 ros-humble-nav2-bringup ros-humble-cartographer-ros \
  ros-humble-rosbridge-server ros-humble-behaviortree-cpp-v4
```

Ensure Node.js (version 22 recommended) and npm are installed for building dashboard web assets.

### 2. Clone Repository & Import Dependencies

```bash
git clone https://github.com/DGIST-DORI/dori
cd dori

# Import third-party repositories
vcs import ros2_ws/src < ros2_ws/src/third_party.repos
```

### 3. Install ROS & Python Dependencies

Initialize and update rosdep:

```bash
source /opt/ros/humble/setup.bash
if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then sudo rosdep init; fi
rosdep update --rosdistro humble
rosdep install --from-paths ros2_ws/src --ignore-src --rosdistro humble -y
```

Set up a virtual environment inheriting system site-packages (required for ROS Python bindings):

```bash
/usr/bin/python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-runtime.txt
```

### 3-1. Prepare Voice Assets (STT / openWakeWord & Whisper)

DORI uses openWakeWord (`hey_mycroft` / custom wake word) and faster-whisper (`small` model) for speech recognition:

```bash
.venv/bin/python -m pip install -c constraints-robot.txt 'openwakeword>=0.6,<0.7' 'faster-whisper>=1,<2'
mkdir -p .state/voice
.venv/bin/python - <<'PYVOICE'
import openwakeword
from faster_whisper.utils import download_model
openwakeword.utils.download_models(model_names=['hey_mycroft'])
download_model('small', output_dir='.state/voice/whisper-small')
print('Voice assets ready.')
PYVOICE
```

*(Alternatively, use the helper script under tools/voice if available)*

### 3-2. (Optional) Download Perception & Vision Models

If `enable_perception:=true` is used, gesture and expression nodes require MediaPipe Task models:

1. Create the model asset directory:

```bash
mkdir -p ros2_ws/src/dori_perception/models
```

2. Download required `.task` files and place them in that directory:

```text
ros2_ws/src/dori_perception/models/hand_landmarker.task
ros2_ws/src/dori_perception/models/face_landmarker.task
```

3. Install perception dependencies:

```bash
.venv/bin/python -m pip install -c constraints-robot.txt -r ros2_ws/src/dori_perception/requirements.txt
```

### 4. Set Environment & API Keys (Optional)

DORI works out-of-the-box with local rule-based intent classification and offline guidance without any external API keys.

If using external LLM providers (e.g. Gemini) or cloud services:

```bash
# Optional: external LLM providers (Gemini)
echo 'export GEMINI_API_KEY="your_key_here"' >> ~/.bashrc

source ~/.bashrc
```

If using external LLM features, install the LLM requirements:

```bash
.venv/bin/python -m pip install -c constraints-robot.txt -r ros2_ws/src/dori_llm/requirements.txt
```

### 5. Build

> **Note:** The web dashboard frontend must be built before building ROS packages so that the compiled assets are packaged into `dori_dashboard`.

```bash
# 1. Build frontend dashboard assets
cd web
npm ci
npm run build
cd ..

# 2. Build ROS 2 workspace
source /opt/ros/humble/setup.bash
source .venv/bin/activate
export PYTHONNOUSERSITE=1
cd ros2_ws
python -m colcon build --symlink-install --parallel-workers 2 \
  --cmake-args -DBUILD_TESTING=ON \
  -DPython3_EXECUTABLE="$VIRTUAL_ENV/bin/python" \
  -DPYTHON_EXECUTABLE="$VIRTUAL_ENV/bin/python"
source install/local_setup.bash
cd ..
```

---

## Usage

### Setting Up Terminal Environment

Before running any ROS 2 nodes or launch files, configure your terminal environment:

```bash
export DORI_ROOT="$PWD"
source /opt/ros/humble/setup.bash
source "$DORI_ROOT/.venv/bin/activate"
source "$DORI_ROOT/ros2_ws/install/local_setup.bash"
export PYTHONPATH="$DORI_ROOT/.venv/lib/python3.10/site-packages:${PYTHONPATH:-}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}"
export PYTHONNOUSERSITE=1
```

### Desktop / Simulation Mode (without Actuators)

Run desktop HRI with or without the dashboard on a development PC:

```bash
# Desktop HRI + Dashboard (Default)
ros2 launch dori_bringup bringup_dev.launch.py

# Desktop HRI without Dashboard
ros2 launch dori_bringup bringup_dev.launch.py enable_dashboard:=false

# Dashboard Standalone
ros2 launch dori_dashboard dashboard.launch.py
```

### Physical Robot (Hardware Launch)

For complete robot operation with hardware drivers, LiDAR, Nav2, HRI, and web viewer:

```bash
ros2 launch dori_bringup hardware.launch.py \
  map:=$(pwd)/maps/live_navigation_20261023_1938.yaml \
  named_goals_file:=$(pwd)/maps/web_goals.json
```

Or using the standard bringup entrypoint:

```bash
ros2 launch dori_bringup bringup.launch.py \
  dori_mode:=real \
  real_map:=$(pwd)/maps/live_navigation_20261023_1938.yaml \
  real_named_goals_file:=$(pwd)/maps/web_goals.json \
  enable_dashboard:=true
```

### Topic Namespace (Default vs Multi-Robot)

- Default (single robot): `namespace:=/dori`
- Multi Robot: Set the `namespace` launch argument to expand to `/dori1/...`, `/dori2/...`

```bash
# Default topic namespace
ros2 launch dori_bringup bringup.launch.py namespace:=/dori

# Robot 1
ros2 launch dori_bringup bringup.launch.py namespace:=/dori1

# Robot 2
ros2 launch dori_bringup bringup.launch.py namespace:=/dori2
```

### Dashboard Access

Once launched, access the dashboard at:

```text
# Local machine
http://localhost:3000

# Remote device on the same local network
http://<Robot-IP>:3000
```

or via Cloudflare Tunnel if configured:
[Cloudflare Server](https://dash.dgist-dori.xyz)

---

## License

This project is developed as part of the DGIST UGRP (Undergraduate Group Research Program).

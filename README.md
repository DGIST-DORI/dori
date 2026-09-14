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

[DORI](https://dgist-dori.xyz) (Dual-shell Omnidirectional Robot for Interaction, stylized as *Dori*) is a spherical campus guide robot capable of navigating diverse campus environments while providing LLM-powered voice interaction.

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
sudo apt install -y \
  portaudio19-dev python3-pyaudio ffmpeg libsndfile1 mpg123 \
  ros-humble-rosbridge-server ros-humble-realsense2-camera
```

### 2. Clone Repository

```bash
git clone https://github.com/DGIST-DORI/dori
cd dori
```

### 3. Install Python Dependencies

```bash
pip3 install -r requirements.txt
```

### 3-1. Download and Place Porcupine `.pv` Models (STT)

1. Download the model
[Porcupine Wake Word GitHub repository](https://github.com/Picovoice/porcupine/tree/master/lib/common)

2. Put it in ros2_ws/src/dori_hri/models

### 3-2. Download and Place MediaPipe `.task` Models (Perception)

`dori_perception` gesture/expression nodes use MediaPipe Tasks models that are **not** bundled by default.

1. Create the model asset directory:

```bash
mkdir -p ros2_ws/src/dori_perception/models
```

2. Download required `.task` files and place them in that directory:

```text
ros2_ws/src/dori_perception/models/hand_landmarker.task
ros2_ws/src/dori_perception/models/face_landmarker.task
```

3. Build/install the workspace so models are copied to:

```text
<install-prefix>/share/dori_perception/models/
```

4. Launch Perception with explicit model paths (recommended) or rely on default share-directory lookup:

```bash
ros2 launch dori_bringup perception.launch.py \
  hand_model_path:=/absolute/path/to/hand_landmarker.task \
  face_model_path:=/absolute/path/to/face_landmarker.task
```

If model files are missing/unreadable/corrupted, the nodes log explicit errors and stop startup.

### 4. Set API Keys

```bash
# Porcupine wake word (required)
echo 'export PORCUPINE_ACCESS_KEY="your_key_here"' >> ~/.bashrc

# Optional: external LLM providers
echo 'export GEMINI_API_KEY="your_key_here"' >> ~/.bashrc

source ~/.bashrc
```

Get your Porcupine key for free at [Picovoice Console](https://console.picovoice.ai/).

### 5. Build

```bash
source /opt/ros/humble/setup.bash
cd ros2_ws
colcon build --symlink-install
source install/setup.bash
```

---

## Usage

### Full Robot (without Dashboard)

```bash
ros2 launch dori_bringup robot.launch.py
```

or

```bash
ros2 launch dori_bringup robot_dev.launch.py enable_dashboard:=false
```

### Topic Namespace (default vs multi-robot remap)

- Default (single robot): `namespace:=/dori`
- Multi Robot: Change only the launch argument to expand to `/dori1/...`, `/dori2/...`

```bash
# Basic topic (same as before)
ros2 launch dori_bringup robot.launch.py namespace:=/dori

# robot1
ros2 launch dori_bringup robot.launch.py namespace:=/dori1

# robot2
ros2 launch dori_bringup robot.launch.py namespace:=/dori2
```

The default topic value is declared with `declare_parameter("topics.xxx", "...")` of each node, and is changed at once by injecting a common prefix at launch.

### Full Robot (with Dashboard)
 
Launches the full robot stack via `robot_dev.launch.py`, together with the web dashboard (rosbridge + HTTP server + knowledge API).
`robot.launch.py` is not responsible for dashboard orchestration in the current setup.
The dashboard frontend must be built before the first run.
 
```bash
# First time only — build the frontend assets
cd web && npm ci && npm run build && cd ..
cd ros2_ws
colcon build --symlink-install
source install/setup.bash
 
# Launch (default includes dashboard)
ros2 launch dori_bringup robot_dev.launch.py

# Equivalent explicit form
# ros2 launch dori_bringup robot_dev.launch.py enable_dashboard:=true
```

Dashboard access:

```text
# Same machine
http://localhost:3000
 
# Remote (another device on the same network)
http://[Robot IP]:3000
```

or

[Cloudflare Server](https://dash.dgist-dori.xyz)

---

## License

This project is developed as part of the DGIST UGRP (Undergraduate Group Research Program).

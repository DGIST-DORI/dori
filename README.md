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

[DORI](https://dgist-dori.xyz) (DGIST O-shaped Robot for Interaction, stylized as _Dori_) is a spherical campus guide robot capable of navigating diverse campus environments while providing LLM-powered voice interaction.

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
  ros-humble-rosbridge-server
```

Ensure Node.js (22.12+ recommended) and npm are installed for building both the dashboard and visitor app.

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

Dori's behavior tree uses Humble's `behaviortree_cpp_v3` package, installed by
rosdep as `ros-humble-behaviortree-cpp-v3`, matching Nav2. Existing checkouts that
imported BehaviorTree.CPP 4.9.0 must archive the old vendor source and generated
artifacts before rebuilding (run from the repository root):

```bash
DORI_BT_BACKUP="$PWD/.state/bt-v4-backup-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$DORI_BT_BACKUP"
for artifact in src/third_party/BehaviorTree.CPP build/behaviortree_cpp install/behaviortree_cpp build/dori_bt; do
  if [ -e "ros2_ws/$artifact" ]; then
    mkdir -p "$DORI_BT_BACKUP/$(dirname "$artifact")"
    mv "ros2_ws/$artifact" "$DORI_BT_BACKUP/$artifact"
  fi
done
```

The default build in step 5 creates `.venv` with system site-packages (required
for ROS Python bindings) and installs `requirements-runtime.txt`, including the
Azure Speech SDK for the visitor app. To prepare Python dependencies before
building, for example for the optional local voice setup below:

```bash
/usr/bin/python3 -m venv --system-site-packages .venv
export PYTHONNOUSERSITE=1
.venv/bin/python -m pip install -r requirements-runtime.txt
```

### 3-1. (Optional) Prepare Local Robot Voice Assets

The smartphone visitor app uses Azure Speech by default and does not need
openWakeWord or Whisper models. For local robot microphone input, DORI uses
openWakeWord and faster-whisper (`small` model):

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

Alternatively, use `scripts/prepare_voice.sh`. For visitor input using local
Whisper, use `scripts/prepare_voice.sh --topic-only`.

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

### 4. Configure Visitor Speech, TTS & Optional LLM API Keys

The default build prepares the visitor app and its SDKs. Cloud credentials are
runtime settings and only need to be configured once per machine.

For the default Azure visitor STT provider, store these values from your Azure
Speech F0 resource in `.state/voice/azure.env` (ignored by Git):

```dotenv
AZURE_SPEECH_KEY=your_speech_resource_key
AZURE_SPEECH_REGION=your_resource_region
AZURE_SPEECH_TIER=F0
```

Create the parent directory with `mkdir -p .state/voice` and restrict the file
with `chmod 600 .state/voice/azure.env`. The launcher reads it automatically;
use `DORI_AZURE_ENV_FILE` for another location. No shell exports are needed for
these file values. See the [visitor setup guide](web/README.md#visitor-voice-app-app-host)
for provider configuration and local Whisper mode.

DORI uses Google Cloud Text-to-Speech by default (`tts_engine:=gcp`). The SDK is
included in `requirements-runtime.txt`. Enable the Cloud Text-to-Speech API and
billing in the service account's Google Cloud project, then store the downloaded
service-account JSON outside the repository:

```bash
install -d -m 700 "$HOME/.config/dori"
install -m 600 /absolute/path/to/downloaded-key.json "$HOME/.config/dori/google-cloud-tts.json"
```

The TTS node automatically reads this file for the user running ROS. To use a
different file, set `GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/key.json`
in the launch environment; this takes precedence over the DORI default path.
If neither is provided, the Google client uses Application Default Credentials.
See [Google Cloud authentication](https://docs.cloud.google.com/text-to-speech/docs/authentication).
Do not commit the JSON or paste its contents into logs or chat.

Restart the TTS node after changing credentials or `tts_engine`. A successful
initialization logs `Google Cloud TTS engine & DB ready`; the first synthesis
also verifies API access. Initialization/request errors or the local daily usage
limits fall back to gTTS and log the reason. To explicitly use gTTS, launch with
`tts_engine:=gtts`. `tts_playback_mode:=publish_only` retains browser speech for
local requests.

Local rule-based intent classification and destination guidance do not require
external LLM API keys.

For Gemini, create a key in [Google AI Studio](https://aistudio.google.com/apikey)
and export it in the shell that starts ROS:

```bash
export GEMINI_API_KEY="your_key_here"
```

If using external LLM features, install the LLM requirements:

```bash
.venv/bin/python -m pip install -c constraints-robot.txt -r ros2_ws/src/dori_llm/requirements.txt
```

After building and sourcing the workspace, enable the external LLM explicitly:

```bash
ros2 launch dori_bringup voice.launch.py \
  use_external_llm:=true llm_model:=gemini-3.5-flash-lite
```

You can persist the export in `~/.bashrc`; a service must receive the variable in
its own environment. DORI does not automatically load `.env` files. The node uses
the `api_key` ROS parameter first, then `GEMINI_API_KEY`, then `GOOGLE_API_KEY`.
The Cloud TTS service-account JSON above is separate from the Gemini API key.
See [LLM configuration and model selection](ros2_ws/src/dori_llm/README.md#external-llm-gemini)
for direct node invocation and model tradeoffs.

### 5. Build

Run the standard build from the repository root:

```bash
scripts/build.sh
```

This prepares the dashboard and smartphone visitor app together:

1. Create `.venv` if needed and install/update the constrained Python runtime
   dependencies, including Azure Speech and Google Cloud TTS.
2. Run `npm ci --include=dev`, then build both `web/dist` and `web/dist-visitor`.
3. Build ROS packages with the project venv and a clean Humble underlay.
   `dori_dashboard` packages both web apps and the visitor gateway.

No separate visitor build or Azure SDK installation is required. The build does
not start servers or require cloud credentials. Network access is needed when
dependencies are not cached. `scripts/build.sh --clean` archives the previous
ROS build/install/log directories before rebuilding; additional arguments are
forwarded to `colcon build`. For example, `scripts/build.sh --packages-select
dori_dashboard` refreshes both web apps and their ROS package after an initial
full build.

Humble colcon requires the legacy setuptools `develop` options. The runtime
constraints pin setuptools 79.0.1; do not upgrade it to 80 or later in this venv.
The build installs this compatible version before invoking colcon. If
`error: option --uninstall not recognized` appears after a manual colcon build,
rerun `scripts/build.sh`; existing build artifacts need not be deleted for
this error. Clearing inherited ROS overlay paths before building prevents
duplicate-underlay warnings caused by sourcing `~/ros2_ws` and this workspace
together. `--allow-overriding` does not repair that environment mix-up.

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

### Smartphone Visitor App + Dashboard

After building and configuring the credentials above, start both apps from the
repository root:

```bash
# Shared secret for the dashboard and visitor gateway; keep it private.
export DORI_INTERNAL_TOKEN="$(openssl rand -hex 32)"
scripts/start_visitor.sh
```

The launcher sets up the ROS environment, selects `visitor_mode:=true`, and
uses Azure STT in the gateway with local microphone STT disabled. No additional
visitor flags or build steps are needed. Stop any existing desktop/dashboard
session before starting it.

Open `http://127.0.0.1:3001/display` on the robot screen and scan its QR code
with the phone. The public app uses `https://app.dgist-dori.xyz` through the
configured tunnel to loopback port 3100; the dashboard uses port 3000. See
[access and authentication](web/README.md#access-and-authentication) for dashboard
authentication and tunnel setup.

Building makes both apps available; the launch profile selects who owns voice
input. The local robot profile below uses the robot microphone and has
`visitor_mode:=false`, so smartphone pairing returns 503 ("voice service not
ready") even if the dashboard is running. Use `scripts/start_visitor.sh` for
phone conversations. This profile keeps visitor speech from triggering robot
movement.

### Local Robot Microphone / Simulation Mode (without Actuators)

After preparing the optional local voice assets in step 3-1, run desktop HRI
with or without the dashboard on a development PC. Set `DORI_INTERNAL_TOKEN`
as above when starting the dashboard:

```bash
# Local robot microphone HRI + Dashboard
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

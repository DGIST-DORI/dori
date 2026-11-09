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

### Default Bringup: Smartphone Visitor App + Dashboard

After building, sourcing the environment, and configuring the credentials above,
start the default bringup:

```bash
# Shared secret for the dashboard and visitor gateway; keep it private.
export DORI_INTERNAL_TOKEN="$(openssl rand -hex 32)"
ros2 launch dori_bringup bringup.launch.py
```

This is the standard entrypoint for both apps, LLM/TTS and the interaction tree.
External LLM conversation is enabled by default (`use_external_llm:=true`), using
`gemini-3.5-flash-lite`. Set `GEMINI_API_KEY` in the launch environment; the standard
build installs its SDK. Use `use_external_llm:=false` for local-only responses or
`llm_model:=...` to select another model. See [LLM setup](ros2_ws/src/dori_llm/README.md).
For campus-document RAG, install `.venv/bin/python -s -m pip install -r requirements-rag.txt`
and run `scripts/refresh_knowledge.sh`. This collects official source records,
validates retrieval, and atomically activates a new index; failed refreshes keep
the previous index. See the [RAG workflow](ros2_ws/src/dori_llm/README.md#source-backed-rag-pipeline).
It defaults to desktop mode, `enable_dashboard:=true`, `visitor_mode:=true`, and
Azure STT in the gateway. Local microphone STT is disabled automatically. The
launch checks the SDK and F0 settings using the gateway's Python before starting
the session. No separate app launcher or visitor flags are needed. Stop any
existing desktop/dashboard session before starting it.

If the previous terminal was closed or shutdown was interrupted, use the recovery
command from this checkout before launching again:

```bash
scripts/stop_dori.sh --dry-run  # Inspect the processes that will be stopped
scripts/stop_dori.sh           # Stop and verify that they have exited
ros2 launch dori_bringup bringup.launch.py
```

Normally, press **Ctrl+C once** in the launch terminal and wait for it to exit.
The recovery command works without sourcing ROS or activating the venv. It stops
this checkout's DORI sessions owned by the current user, including orphaned app
servers. It first sends SIGINT to launchers to disable automatic respawning and
allow normal cleanup, then sends SIGINT, SIGTERM and finally SIGKILL to remaining
processes as needed. Each SIGINT stage waits up to 10 seconds (`--grace SECONDS`
changes this); SIGTERM and SIGKILL wait up to 5 and 2 seconds. Repeating the command
after shutdown is harmless. Process identities are checked to avoid signalling a
reused PID. All sessions/namespaces from this checkout are included; unrelated
processes are not stopped just because they occupy a DORI port.

New bringup/dashboard sessions label their descendants with `DORI_SESSION_ROOT`
so recovery can find them even after their parent exits. Older sessions are
identified by their launch tree, workspace paths and dashboard ROS namespace.
Run as the same user that launched DORI. This stops the server processes;
`scripts/stop_navigation.sh` only requests a navigation stop. For a physical robot,
stop movement before shutting down the stack; forced process termination cannot
perform hardware cleanup.

On a connected robot display, follow the [kiosk setup](#connected-display-automatic-kiosk)
below to open `http://127.0.0.1:3001/display` automatically after bringup, or open
it manually and scan its QR code with the phone. The public app uses
`https://app.dgist-dori.xyz` through the
configured tunnel to loopback port 3100; the dashboard uses port 3000. See
[access and authentication](web/README.md#access-and-authentication) for dashboard
authentication and tunnel setup.

Visitor mode keeps phone conversations from triggering robot movement. To use
local Whisper for phone input, prepare its model once with
`scripts/prepare_voice.sh --topic-only`, then run:

```bash
ros2 launch dori_bringup bringup.launch.py visitor_stt:=whisper
```

`visitor_stt` takes precedence over `DORI_VISITOR_STT`; if neither is set, Azure
is selected. Whisper mode automatically enables topic STT and uses the prepared
`.state/voice/whisper-small` model. `enable_stt` and `stt_audio_input_mode` default
to `auto`, so switching profiles keeps the voice node and gateway consistent.

### Connected Display: Automatic Kiosk

The connected robot screen shows the visitor pairing and connection screen at
`http://127.0.0.1:3001/display`; visitors use the public app on their phones.
Bringup starts the display server. Complete this one-time desktop setup to also
open its screen automatically in [Firefox kiosk mode](https://support.mozilla.org/en-US/kb/firefox-enterprise-kiosk-mode)
when the server is ready. This setup uses the native DEB package and does not
require Chromium or Snap.

Log in to the robot's graphical desktop on the connected display and run the
setup as that desktop user. A connected monitor alone is not enough: an active
X11 or Wayland session is required. Use a terminal in that desktop for setup so
the browser inherits the correct display environment.

Install Firefox using [Mozilla's official APT repository](https://support.mozilla.org/en-US/kb/install-firefox-linux),
which provides ARM64 and AMD64 packages. Ubuntu 22.04's default `firefox` package
is a Snap launcher, so configure the repository and package priorities first:

```bash
sudo apt update
sudo apt install -y curl ca-certificates
sudo install -d -m 0755 /etc/apt/keyrings
sudo curl --fail --show-error --silent --location \
  https://packages.mozilla.org/apt/repo-signing-key.gpg \
  --output /etc/apt/keyrings/packages.mozilla.org.asc
sudo chmod 644 /etc/apt/keyrings/packages.mozilla.org.asc

sudo tee /etc/apt/sources.list.d/mozilla.list > /dev/null <<'MOZILLA_APT'
deb [signed-by=/etc/apt/keyrings/packages.mozilla.org.asc] https://packages.mozilla.org/apt mozilla main
MOZILLA_APT

sudo tee /etc/apt/preferences.d/mozilla > /dev/null <<'MOZILLA_PIN'
Package: firefox firefox-l10n-*
Pin: origin packages.mozilla.org
Pin-Priority: 1001

Package: firefox
Pin: release o=Ubuntu
Pin-Priority: -1
MOZILLA_PIN

sudo apt update
apt-cache policy firefox
```

Confirm that the candidate comes from `packages.mozilla.org`, then install it:

```bash
sudo apt install firefox
/usr/bin/firefox --version
```

The priority of 1001 allows APT to replace an installed `1:1snap...` transitional
package with Mozilla's native package. APT may describe this as a downgrade.

Create a launcher that waits for the local display page before opening the browser,
and register it with [desktop autostart](https://specifications.freedesktop.org/autostart/latest/):

```bash
mkdir -p "$HOME/.local/bin" "$HOME/.config/autostart" "$HOME/.local/state/dori"

cat > "$HOME/.local/bin/dori-kiosk" <<'KIOSK'
#!/usr/bin/env bash
set -euo pipefail

profile="$HOME/.local/state/dori/firefox-kiosk"
mkdir -p "$profile"
url='http://127.0.0.1:3001/display'
until curl --noproxy '*' --fail --silent --max-time 2 --output /dev/null "$url"; do
    sleep 1
done

exec /usr/bin/firefox \
    --no-remote \
    --profile "$profile" \
    --kiosk \
    --private-window "$url"
KIOSK
chmod +x "$HOME/.local/bin/dori-kiosk"

cat > "$HOME/.config/autostart/dori-kiosk.desktop" <<AUTOSTART
[Desktop Entry]
Type=Application
Name=DORI Kiosk
Exec="$HOME/.local/bin/dori-kiosk"
Terminal=false
AUTOSTART
```

The separate Firefox profile and `--no-remote` keep the kiosk independent of
ordinary browser windows. If you used the earlier Chromium setup, recreate the
launcher above to switch browsers. Start it once for the current desktop session,
then run the usual bringup from the repository root with the terminal environment
and credentials configured above:

```bash
nohup "$HOME/.local/bin/dori-kiosk" > "$HOME/.local/state/dori/kiosk.log" 2>&1 &
export DORI_INTERNAL_TOKEN="$(openssl rand -hex 32)"
ros2 launch dori_bringup bringup.launch.py
```

On subsequent desktop logins, the launcher starts automatically and waits for
bringup. Once `/display` responds successfully, Firefox opens it full-screen.
Keep `enable_dashboard:=true` and `visitor_mode:=true` for phone pairing. Bringup
can also be started over SSH while the local desktop and its launcher are running.

Press **Ctrl+C once** in the ROS terminal to stop bringup. The kiosk stays open,
shows its disconnected state, and reconnects when bringup restarts. **Alt+F4**
closes the kiosk; rerun the `nohup` command to reopen it in the current desktop
session. Remove `~/.config/autostart/dori-kiosk.desktop` to disable future autostart.
For an unattended display, disable screen blanking and automatic suspend in the
desktop settings. If no window appears, check `~/.local/state/dori/kiosk.log`
for a manually started launcher and confirm that the display URL opens locally.

### Local Robot Microphone / Simulation Mode (without Actuators)

After preparing the optional local voice assets in step 3-1, run desktop HRI
with or without the dashboard on a development PC. Set `DORI_INTERNAL_TOKEN`
as above when starting the dashboard:

```bash
# Local robot microphone HRI + Dashboard
ros2 launch dori_bringup bringup.launch.py visitor_mode:=false

# Local robot microphone HRI without Dashboard
ros2 launch dori_bringup bringup.launch.py visitor_mode:=false enable_dashboard:=false

# Dashboard Standalone
ros2 launch dori_dashboard dashboard.launch.py
```

`visitor_mode:=false` enables microphone STT automatically and disables phone
pairing. A standalone dashboard also needs the voice/interaction nodes for
phone pairing; use the default bringup for the complete app session.

### Physical Robot (Hardware Launch)

For complete robot operation with hardware drivers, LiDAR, Nav2, HRI, and web viewer:

Install CAN auto-setup **once**, with the CANable2 connected and robot nodes stopped:

```bash
sudo /usr/bin/python3 ros2_ws/src/dori_hardware/scripts/install_can_service.py
```

This identifies the connected CANable2 by USB serial and installs
`dori-can.service` plus its udev rule. At boot and on USB reconnect, the service
creates and activates `can1`; unplugging the adapter stops its service.
It does not launch ROS nodes or issue motor commands. The FTDI adapter is not
required for this installation. No `systemctl enable` or per-session sudo is needed.
Use `--dry-run` to review the device and paths without changing the system.

Bringup waits up to 10 seconds for CAN to become UP, then checks that the
Dynamixel, IMU and LiDAR ports exist, are accessible, and refer to different
devices. `real_can_wait_timeout:=20` changes this wait (0–30 seconds);
`hardware.launch.py` uses `can_wait_timeout`. Failure reports the CAN service
state and all missing devices before starting robot nodes. Full device setup
and troubleshooting are in [AMM 20-30](docs/user/DORI-AMM.md#task-20-30-00--현장-장치-준비).

```bash
systemctl status dori-can.service --no-pager
journalctl -u dori-can.service -b --no-pager
ip -details link show can1
```

```bash
ros2 launch dori_bringup hardware.launch.py \
  map:=$(pwd)/maps/live_navigation_20261023_1938.yaml \
  named_goals_file:=$(pwd)/maps/web_goals.json
```

Or using the standard bringup entrypoint with local robot microphone input:

```bash
ros2 launch dori_bringup bringup.launch.py \
  dori_mode:=real \
  visitor_mode:=false \
  real_map:=$(pwd)/maps/live_navigation_20261023_1938.yaml \
  real_named_goals_file:=$(pwd)/maps/web_goals.json \
  enable_dashboard:=true
```

Omit `visitor_mode:=false` to keep the default visitor app profile on the
physical robot. Hardware still requires the map and device preparation above.

The DORI Dynamixel driver uses the FTDI adapter's stable `/dev/serial/by-id/`
path. Do not run the upstream `dynamixel_sdk_examples/read_write_node` alongside
bringup: its fixed `/dev/ttyUSB0` can open the LiDAR port, change its baud rate,
and cause `SL_RESULT_OPERATION_TIMEOUT`. The DORI driver handles only DXL IDs
1 and 3; motor 4 uses CubeMars CAN ID 4. Failed DXL reads are rejected as invalid
feedback instead of being reported as position zero.

To use different hardware paths, set `real_can_interface`, `real_dxl_port`,
`real_imu_port` and `real_lidar_port` on `bringup.launch.py`. On
`hardware.launch.py`, use the same argument names without `real_`. Specify the
actual devices; changing `can1` to the onboard `can0` is not a substitute for
preparing the connected CANable adapter. A missing FTDI path means that adapter
must be connected or its replacement's path explicitly configured.

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

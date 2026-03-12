# DORI — Autonomous Campus Guide Robot

**DORI** (Dual-shell Omnidirectional Robot for Interaction) is a spherical campus guide robot capable of navigating diverse campus environments while providing LLM-powered voice interaction in Korean and English both.

> UGRP 2026 — DGIST

---

## Overview

DORI

```
User speaks
    │
    ▼
[STT Node]  Porcupine wake word + Whisper transcription
    │
    ▼
[HRI Manager]  State machine: IDLE → LISTENING → RESPONDING → NAVIGATING
    │
    ├──► [LLM Node]  Intent classification + RAG knowledge base → response
    │         │
    │         └──► [Nav]  PoseStamped destination if navigation intent
    │
    └──► [TTS Node]  Korean speech synthesis
```

---

## System Architecture

### Hardware

#### Component

Based on: https://www.notion.so/2f869a97d828815ea997c18536e5388d?v=2f869a97d8288142962f000c1662184d

Last updated: March 10, 2026.

**Total Estimated Cost:** ₩4,387,816  
**Total Weight (major components):** ~2,632 g

| Component | Spec | Weight (g) | Power (W) | Voltage (V) | Price (₩) | Stock | Notes |
|---|---|---|---|---|---|---|---|
| Compute | NVIDIA Jetson Orin Nano Super | 176 | 7–25 | 9–20 (19V nominal) | 480,000 | 1 | Main onboard computer |
| Camera | Intel RealSense D435i | 72 | 2 | USB-C | 526,000 | 2 | RGB-D camera |
| Motor 1–2 | CubeMars AK45-10 KV75 | 260 | 50.4 / 120 | 24 | 240,900 | 2 | Ordered |
| Motor 3–4 | ROBOTIS Dynamixel XH430-V350-R | 82 | 1.44 / 16.8 | 24 | 387,200 | 2 | Ordered |
| Link Component | CubeMars Rubik Link | – | – | – | 64,300 | 1 | Ordered |
| Interface | ROBOTIS U2D2 | – | – | – | 39,300 | 1 | Ordered |
| Interface | ROBOTIS U2D2 Hub | – | – | – | 24,780 | 1 | Ordered |
| CAN Adapter | Waveshare USB-CAN-A | – | – | USB | 52,700 | 1 | Ordered |
| Jetson Power | 24V→19V Step-down Converter (10A) | 270 | – | 24→19 | 28,500 | 1 | Jetson power regulation |
| IMU | - | - | - | - | 1 | - |
| Microphone | Hollyland Lark M2 | 15 / 87 | <1 | USB-C | 123,000 | 1 | Wireless mic |
| Speaker | Adafruit USB Powered Mini Speaker | 73.6 | 4 | 5 | 28,300 | 1 | USB powered |
| Ultrasonic Sensor | DFRobot Gravity URM09 (I2C) | – | – | – | – | 4 | Distance sensing |
| Battery | HRB LiPo 6S 8000mAh (22.2V) | 1155 | – | 22.2 | 225,782 | 2 | Main battery |
| Battery Monitor | LiPo Voltage Tester / Alarm | – | – | – | 3,100 | 1 | Battery safety |
| Charger | SKYRC B6 Neo Charger (200W / 20A) | – | – | – | 55,000 | 1 | LiPo charger |
| Power Cable | XT60 F → DC 5.5×2.1mm Cable | – | – | – | 7,600 | 1 | Jetson power input |
| Power Connector | XT60 Connector Socket | – | – | – | 1,300 | 30 | Power distribution |
| Power Cable | 14AWG 2P Power Cable | – | – | – | 1,600 | 10 | Wiring |
| USB Hub | NEXT-614U3 (4-port USB hub) | 34 | – | – | 9,020 | 1 | Peripheral expansion |
| Frame | Aluminum Pipe 16mm / 2T / 3000mm | – | – | – | 15,200 | 1 | Structural frame |
| Frame | Aluminum Pipe 10mm / 2T / 2500mm | – | – | – | 10,300 | 1 | Cut into 12×170mm |
| Frame | Aluminum Pipe 12mm / 1T / 500mm | – | – | – | 3,700 | 1 | Structural frame |
| Tool | Pipe Reamer | – | – | – | 39,270 | 1 | Assembly tool |
| Frame Part | Aluminum Flange (16mm inner diameter) | – | – | – | 10,100 | 9 | Pipe mounting |
| Bearing | 6" Lazy Susan Bearing | – | – | – | 8,530 | 5 | Rotation joint |
| Bearing | C-E6004ZZ Bearing | – | – | – | 1,903 | 8 | Mechanical support |
| Bearing | C-E6701ZZ Bearing | – | – | – | 1,276 | 8 | Mechanical support |
| Tool | Pipe Cutter | – | – | – | 17,500 | 1 | Assembly tool |

#### Robot Infomation
|||
|---|---|
| Robot form | Spherical, 540 mm diameter, dual-shell cube mechanism |
| Camera height | 270 mm |

### Software Packages

```
src/
├── hri_pkg/              # Perception: person detection, gesture, expression, landmark
├── stt_pkg/              # Wake word (Porcupine) + transcription (Whisper)
├── llm_pkg/              # Intent classification + RAG + LLM response
├── tts_pkg/              # Text-to-speech playback
├── navigation_pkg/       # Navigation execution node
├── dashboard_pkg/        # ROS ↔ web dashboard bridge
└── bringup/              # Launch files
    ├── robot.launch.py           # Full robot (top-level)
    ├── hri.launch.py             # HRI perception only
    └── voice_interface.launch.py # Voice pipeline only
```

### ROS2 Topic Map

All topics are namespaced under `/dori/`.

```
/dori/
├── camera/
│   ├── color/image_raw
│   ├── depth/image_raw
│   └── rear/color/image_raw
├── stt/
│   ├── wake_word_detected  (Bool)    wake word trigger
│   └── result              (String)  JSON {text, language, confidence}
├── hri/
│   ├── manager_state       (String)  current HRI state
│   ├── persons             (String)  YOLO detection JSON
│   ├── tracking_state      (String)  ByteTrack state JSON
│   ├── gesture             (String)  MediaPipe gesture
│   └── expression          (String)  face expression
├── llm/
│   ├── query               (String)  user text + location context
│   └── response            (String)  generated response
├── tts/
│   ├── text                (String)  direct TTS bypass
│   ├── speaking            (Bool)    mutes STT while speaking
│   └── done                (Bool)    playback finished signal
├── follow/
│   └── target_offset       (Point)   person-following offset for nav
└── nav/
    ├── command             (String)  high-level nav command
    └── destination         (PoseStamped) goal pose from LLM
```

---

## Installation

### Prerequisites

- Ubuntu 22.04
- ROS2 Humble
- Python 3.10+
- CUDA 11+ (for Jetson or GPU workstation)
- Microphone and speakers

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

#### 필수 (공통)

아래 한 번으로 음성 인터페이스 핵심 패키지(`stt_pkg`, `tts_pkg`, `llm_pkg`) 의존성을 모두 설치합니다.

```bash
pip3 install -r requirements.txt
```

루트 `requirements.txt`는 다음 파일을 참조합니다.

- `src/stt_pkg/requirements.txt`
- `src/tts_pkg/requirements.txt`
- `src/llm_pkg/requirements.txt`

#### 선택 (패키지별 추가 설치)

기능별로 아래를 추가 설치하세요.

- `hri_pkg` (카메라/비전 기능):

  ```bash
  pip3 install opencv-python mediapipe ultralytics pyrealsense2
  ```

- `llm_pkg` 외부 모델 API 사용 시: API 키 설정 필요 (`OPENAI_API_KEY`, `GEMINI_API_KEY` 등)
- `stt_pkg` Silero VAD 사용 시: `torch` 설치 권장

### 4. Set API Keys

```bash
# Porcupine wake word (required)
echo 'export PORCUPINE_ACCESS_KEY="your_key_here"' >> ~/.bashrc

# Optional: external LLM providers
echo 'export OPENAI_API_KEY="your_key_here"' >> ~/.bashrc
echo 'export GEMINI_API_KEY="your_key_here"' >> ~/.bashrc

source ~/.bashrc
```

Get your Porcupine key for free at [Picovoice Console](https://console.picovoice.ai/).

### 5. Build

```bash
source /opt/ros/humble/setup.bash
colcon build --symlink-install
source install/setup.bash
```

---

## Usage

### Full Robot

```bash
ros2 launch bringup robot.launch.py
```

### Common Launch Options

```bash
# Use external LLM instead of local model
ros2 launch bringup robot.launch.py use_external_llm:=true

# SW development without navigation hardware
ros2 launch bringup robot.launch.py enable_navigation:=false

# Change Whisper model size (tiny / base / small / medium)
ros2 launch bringup robot.launch.py whisper_model:=base

# Change TTS language
ros2 launch bringup robot.launch.py tts_language:=ko
```

### Sub-system Launch (Development)

```bash
# HRI perception only (cameras + detection nodes)
ros2 launch bringup hri.launch.py visualize:=true

# Voice pipeline only (no cameras needed)
ros2 launch bringup voice_interface.launch.py
```

### Testing Without Hardware

Perception and voice nodes can be tested independently using manual topic injection:

```bash
# Terminal 1: start HRI manager
ros2 run hri_pkg hri_manager_node

# Terminal 2: simulate wake word
ros2 topic pub /dori/stt/wake_word_detected std_msgs/msg/Bool "data: true" --once

# Terminal 3: simulate STT result
ros2 topic pub /dori/stt/result std_msgs/msg/String \
  'data: "{\"text\": \"도서관 어디야\", \"language\": \"ko\", \"confidence\": 0.95}"' --once

# Monitor state
ros2 topic echo /dori/hri/manager_state
ros2 topic echo /dori/tts/text
```

---

## Interaction Flow

DORI wakes on the keyword **"porcupine"** (temporary; to be replaced with custom keyword (Dori)).

```
User: "porcupine"           → IDLE → LISTENING
User: "도서관 어디야?"        → STT transcription
DORI: "도서관으로 안내할게요." → LLM response → TTS playback → NAVIGATING
```

Alternatively, a **WAVE** gesture activates the same wake-word handler for users who prefer not to speak.

### Supported Gestures

| Gesture | Action |
|---|---|
| WAVE | Activate DORI (same as wake word) |
| STOP | Pause navigation |
| POINT | Provide directional hint |
| THUMBS_UP | Positive confirmation |

---

## HRI State Machine

```
         wake word / WAVE gesture
IDLE ──────────────────────────────► LISTENING
  ▲                                      │
  │                                 STT result
  │ idle timeout (10 s)                  │
  │                                      ▼
  │                                 RESPONDING ──► LLM query
  │                                      │
  │                               TTS done / nav intent
  │                                      │
  └────────────── target lost ◄─── NAVIGATING
```

---

## Node Reference

### `hri_manager_node`
Central coordinator. Manages the state machine and routes messages between all HRI subsystems.

### `person_detection_node`
YOLOv8 + ByteTrack full-body person detection with depth-based distance estimation. Publishes tracking state and follow offset for navigation.

### `gesture_recognition_node`
MediaPipe Hands — classifies STOP / POINT / WAVE / THUMBS_UP from 21-point hand landmarks. CPU-only; activates only after interaction trigger.

### `facial_expression_node`
MediaPipe Face Mesh — classifies SATISFIED / CONFUSED / NEUTRAL from 468-point face landmarks. Activates only after interaction trigger.

### `landmark_detection_node`
YOLOv8 landmark detection for SLAM drift correction and LLM location context. Fine-tunable on campus-specific dataset.

### `stt_node`
Always-on Porcupine wake word detection. On trigger, activates Whisper transcription with Silero VAD for speech-end detection. Mutes itself while TTS is playing.

### `llm_node`
Intent classification (navigation / information / greeting / general) + lightweight RAG over campus knowledge base (locations + FAQs). Supports local inference or external API (OpenAI / Anthropic).

### `tts_node`
Korean TTS with `gtts` (online) or `pyttsx3` (offline). Publishes `/dori/tts/speaking` to mute the microphone during playback.

---

## Dashboard

A browser-based debug dashboard is available, serving both an HRI monitor and a 3×3 cube simulator.

```bash
# 1) Build the frontend assets first (required)
cd web
npm ci   # or: npm install
npm run build

# 2) Return to ROS workspace root
cd ..

# 3) Build workspace and source overlay
colcon build --symlink-install
source install/setup.bash

# 4) Start dashboard backend (rosbridge + HTTP server)
ros2 launch dashboard_pkg dashboard.launch.py
```

Dashboard access endpoints:

- Dashboard URL: `http://[Robot IP]:3000`
- ROS WebSocket URL: `ws://[Robot IP]:9090`

Connection examples:

```text
# Local access on robot host
http://localhost:3000
ws://localhost:9090

# Remote access from another device on the same network
http://[Robot IP]:3000
ws://[Robot IP]:9090
```

The dashboard displays real-time topic values, HRI state, person tracking, gesture/expression state, and event log through the ROS WebSocket bridge.

---

## Development Notes

### Resource Management (Jetson Orin Nano)

- **Camera FPS:** 15 Hz (two D435s at 30 Hz saturates USB 3.0 bandwidth)
- **YOLOv8:** TensorRT inference on GPU (~5 ms/frame); infers every 2–3 frames
- **MediaPipe gesture/expression:** activates only after wake word (Tier 3 resource)
- **LLM:** offload to external server recommended for 7B+ models
- **SLAM:** 

### Coordinate System (Cube Robot)

```
Origin: cube center (0, 0, 0)
  x: right = +1,  left  = -1
  y: up    = +1,  down  = -1
  z: front = +1,  back  = -1

Robot axes (rotatable): U, R, L, B
Internal axes (fixed):  F, D
```

### Adding Campus Knowledge

Edit `/data/campus/indexed/campus_knowledge.json`:

```json
"E8": {
      "bldg_no": "E8",
      "class": "E",
      "name_ko": "학술정보관",
      "name_en": "Central Library",
      "description_ko": "학술정보관입니다. 열람실과 스터디룸이 있습니다.",
      "description_en": "",
      "coordinates": [0.0, 0.0],
      "floor": 6,
      "keywords": ["도서관", "책", "공부", "열람실", "library", "study"],
      "hours": "09:00-24:00",
      "facilities": ["열람실", "그룹스터디룸", "북카페"],
      "url": "https://library.dgist.ac.kr/main.do"
    },
```

### Training a Custom Landmark Model

```bash
# Prepare dataset (YOLO format) and edit config/data.yaml
ros2 run hri_pkg train_landmark \
  --data config/data.yaml \
  --model yolov8n.pt \
  --epochs 100
```

---

## License

This project is developed as part of the DGIST UGRP (Undergraduate Group Research Program).

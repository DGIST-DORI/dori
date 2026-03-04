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

| Component | Spec |
|---|---|
| Compute | NVIDIA Jetson Orin Nano (6-core ARM, 1024 CUDA cores, 8 GB RAM) |
| Camera | Intel RealSense D435i × 2 |
| Robot form | Spherical, 540 mm diameter, dual-shell cube mechanism |
| Camera height | 270 mm |

### Software Packages

```
ros2_ws/src/
├── hri_pkg/              # Perception: person detection, gesture, expression, landmark
├── stt_pkg/              # Wake word (Porcupine) + transcription (Whisper)
├── llm_pkg/              # Intent classification + RAG + LLM response
├── tts_pkg/              # Text-to-speech playback
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
git clone https://github.com/DGIST-DORI/dori_ros2
cd dori_ros2
```

### 3. Install Python Dependencies

```bash
pip3 install -r requirements.txt
```

### 4. Set API Keys

```bash
# Porcupine wake word (required)
echo 'export PORCUPINE_ACCESS_KEY="your_key_here"' >> ~/.bashrc

# Optional: external LLM
echo 'export OPENAI_API_KEY="your_key_here"' >> ~/.bashrc

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
# Start rosbridge + HTTP server
ros2 launch cubesim_pkg cubesim.launch.py

# Access from any device on the same network
http://[Robot IP]:3000
```

The dashboard connects to ROS2 via WebSocket (`ws://[Robot IP]:9090`) and displays real-time topic values, HRI state, person tracking, gesture/expression state, and event log.

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

Edit `llm_pkg/config/campus_knowledge.json`:

```json
{
  "locations": {
    "library": {
      "name": "E8: 중앙도서관",
      "description": "학생들이 공부하는 공간",
      "coordinates": [42.424, 242.424],
      "keywords": ["도서관", "책", "열람실"]
    }
  },
  "faqs": {
    "wifi": "캠퍼스 Wi-Fi는 'DGIST-Guest' 네트워크를 사용하세요."
  }
}
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

> Note: Port `3000` is now served directly by `knowledge_api.py` (unified frontend + API server).
> If dashboard launch fails on startup, first verify runtime dependencies are installed (`fastapi`, `uvicorn`, `python-multipart`).

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
# Perception only (cameras + detection nodes)
ros2 launch bringup perception.launch.py visualize:=true

# Interaction state machine only
ros2 launch bringup interaction.launch.py

# Voice pipeline only (no cameras needed)
ros2 launch bringup voice.launch.py
```

### Testing Without Hardware

Perception and voice nodes can be tested independently using manual topic injection:

```bash
# Terminal 1: start HRI manager
ros2 run dori_hri hri_manager_node

# Terminal 2: simulate wake word
ros2 topic pub /stt/wake_word_detected std_msgs/msg/Bool "data: true" --once

# Terminal 3: simulate STT result
ros2 topic pub /stt/result std_msgs/msg/String \
  'data: "{\"text\": \"도서관 어디야\", \"language\": \"ko\", \"confidence\": 0.95}"' --once

# Monitor state
ros2 topic echo /hri/manager_state
ros2 topic echo /tts/text
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

### MediaPipe Task Models (Operations)

Gesture and expression nodes require external MediaPipe Task files:

- `hand_landmarker.task`
- `face_landmarker.task`

Recommended placement in source tree:

```text
ros2_ws/src/dori_perception/models/
```

After `colcon build`, assets are installed under:

```text
install/dori_perception/share/dori_perception/models/
```

Launch options:

- Set explicit launch arguments: `hand_model_path`, `face_model_path`
- Or leave them empty and let each node resolve defaults from package share

Startup logs distinguish:

- missing model file
- permission/readability errors
- model loading/validation failures

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
ros2 run dori_perception train_landmark \
  --data config/data.yaml \
  --model yolov8n.pt \
  --epochs 100
```

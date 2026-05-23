# Architecture

## System Architecture

### Hardware

#### Component

Based on: https://www.notion.so/2f869a97d828815ea997c18536e5388d?v=2f869a97d8288142962f000c1662184d

Last updated: March 10, 2026.

**Total Estimated Cost:** ₩4,387,816  
**Total Weight (major components):** ~2,632 g
<details>
    <summary>Component list</summary>
    
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

</details>

#### Robot Infomation
|||
|---|---|
| Robot form | Spherical, 540 mm diameter, dual-shell cube mechanism |
| Camera height | 270 mm |

### Software Packages

```
ros2_ws/src/
├── perception_pkg/       # Perception: camera, person detection, gesture, expression, landmark
├── interaction_pkg/      # Interaction coordinator (HRI manager state machine)
├── hri_pkg/              # HRI nodes
├── stt_pkg/              # Wake word (Porcupine) + transcription (Whisper)
├── llm_pkg/              # Intent classification + RAG + LLM response
├── tts_pkg/              # Text-to-speech playback
├── navigation_pkg/       # Navigation execution node
├── dashboard_pkg/        # ROS ↔ web dashboard bridge
└── bringup/              # Launch files
    ├── robot.launch.py           # Full robot (top-level)
    ├── perception.launch.py      # Perception only
    ├── interaction.launch.py     # HRI manager/state machine only
    └── voice.launch.py # Voice pipeline only
```

### ROS2 Topic List (Actual Nodes)

#### Topic List source of truth

- Source file: `config/ros2_topics.yaml`.
- This section is generated/synchronized from the YAML file via `python3 tools/topic/topic_lint.py --sync-architecture`.
- CI runs `python3 tools/topic/topic_lint.py --check` and emits warnings if drift is detected.

<!-- TOPIC:START -->
#### In-scope application topics

| Topic | Msg type | Publisher(s) | Subscriber(s) | Description |
|---|---|---|---|---|
| `/dori/odom` | `nav_msgs/msg/Odometry` | Base controller / localization stack | navigator_node | Robot odometry pose/velocity input. |
| `/dori/scan` | `sensor_msgs/msg/LaserScan` | LiDAR driver | navigator_node | Laser range scan for obstacle detection/avoidance. |
| `/dori/cmd_vel` | `geometry_msgs/msg/Twist` | navigator_node | Base controller / motor interface | Velocity command output to robot base. |

#### Out of documentation scope (base platform topics)

| Topic | Msg type | Publisher(s) | Subscriber(s) | Description |
|---|---|---|---|---|
| `camera/front/color/image_raw` | `sensor_msgs/msg/Image` | depth_camera_node | person_detection_node, gesture_recognition_node, facial_expression_node, landmark_detection_node | RGB camera stream used by all perception pipelines. |
| `camera/front/depth/image_raw` | `sensor_msgs/msg/Image` | depth_camera_node | person_detection_node, landmark_detection_node | Raw depth frame for distance estimation and landmark range filtering. |
| `camera/front/depth/image_colormap` | `sensor_msgs/msg/Image` | depth_camera_node | - | Colorized depth visualization stream. |
| `camera/front/color/camera_info` | `sensor_msgs/msg/CameraInfo` | depth_camera_node | landmark_detection_node | RGB intrinsics for pixel-to-direction / localization math. |
| `camera/front/depth/camera_info` | `sensor_msgs/msg/CameraInfo` | depth_camera_node | - | Depth intrinsics metadata stream. |
| `camera/front/depth/scale` | `std_msgs/msg/Float32` | - | person_detection_node | Optional depth meter-per-unit scale expected by person detection. |
| `camera/rear/color/image_raw` | `sensor_msgs/msg/Image` | depth_camera_node | - | Rear RGB camera stream. |
| `camera/rear/depth/image_raw` | `sensor_msgs/msg/Image` | depth_camera_node | - | Rear raw depth frame. |
| `camera/rear/depth/image_colormap` | `sensor_msgs/msg/Image` | depth_camera_node | - | Rear colorized depth visualization stream. |
| `camera/rear/color/camera_info` | `sensor_msgs/msg/CameraInfo` | depth_camera_node | - | Rear RGB intrinsics metadata stream. |
| `camera/rear/depth/camera_info` | `sensor_msgs/msg/CameraInfo` | depth_camera_node | - | Rear depth intrinsics metadata stream. |
| `camera/rear/depth/scale` | `std_msgs/msg/Float32` | - | - | Optional rear depth meter-per-unit scale. |
| `hri/persons` | `std_msgs/msg/String` | person_detection_node | - | JSON list of detected persons/tracks. |
| `hri/interaction_trigger` | `std_msgs/msg/Bool` | person_detection_node | gesture_recognition_node, facial_expression_node | Enables gesture/expression inference only during interaction. |
| `hri/tracking_state` | `std_msgs/msg/String` | person_detection_node | hri_manager_node | JSON tracking state (`idle/tracking/lost`) for session/nav control. |
| `follow/target_offset` | `geometry_msgs/msg/Point` | person_detection_node | - | Relative target offset for follow-control consumers. |
| `hri/annotated_image` | `sensor_msgs/msg/Image` | person_detection_node | - | Person detection debug overlay image. |
| `hri/gesture` | `std_msgs/msg/String` | gesture_recognition_node | - | Gesture detection JSON payload. |
| `hri/gesture_command` | `std_msgs/msg/String` | gesture_recognition_node | hri_manager_node | Mapped high-level gesture command (`STOP`, `CALL`, etc.). |
| `stt/wake_word_detected` | `std_msgs/msg/Bool` | gesture_recognition_node (WAVE trigger), external STT node | hri_manager_node | Wake event that starts HRI listening flow. |
| `hri/annotated_gesture` | `sensor_msgs/msg/Image` | gesture_recognition_node | - | Gesture visualization/debug image. |
| `hri/expression` | `std_msgs/msg/String` | facial_expression_node | - | Expression inference JSON payload. |
| `hri/expression_command` | `std_msgs/msg/String` | facial_expression_node | hri_manager_node | HRI action hint from expression state. |
| `hri/annotated_expression` | `sensor_msgs/msg/Image` | facial_expression_node | - | Facial expression visualization/debug image. |
| `landmark/detections` | `std_msgs/msg/String` | landmark_detection_node | - | Raw landmark/candidate detections as JSON. |
| `landmark/localization` | `std_msgs/msg/String` | landmark_detection_node | - | Landmark-based localization estimate JSON. |
| `landmark/context` | `std_msgs/msg/String` | landmark_detection_node | hri_manager_node | Current location/context text used in LLM query payload. |
| `hri/annotated_landmark` | `sensor_msgs/msg/Image` | landmark_detection_node | - | Landmark detection visualization/debug image. |
| `stt/audio_input` | `std_msgs/msg/String` | dashboard STTPanel mic publisher | stt_node | E2E STT input payload JSON: {audio_b64, format:'wav_pcm16', sample_rate:16000, channels:1}. |
| `stt/result` | `std_msgs/msg/String` | stt_node | hri_manager_node | STT output JSON/text from recognizer. E2E path: STTPanel mic -> stt/audio_input -> stt_node(Whisper) -> stt/result -> hri_manager_node. |
| `tts/done` | `std_msgs/msg/Bool` | tts_node | hri_manager_node | Playback completion event for HRI state transitions. |
| `hri/manager_state` | `std_msgs/msg/String` | hri_manager_node | - | Current HRI state heartbeat (`IDLE`, `LISTENING`, etc.). |
| `llm/query` | `std_msgs/msg/String` | hri_manager_node | llm_node | JSON request containing user text + contextual fields. |
| `tts/text` | `std_msgs/msg/String` | hri_manager_node | tts_node | Direct TTS text (bypass LLM for prompts/system messages). |
| `nav/command` | `std_msgs/msg/String` | hri_manager_node | - | High-level navigation command channel. |
| `llm/response` | `std_msgs/msg/String` | llm_node | tts_node | Generated natural-language response text. |
| `nav/destination` | `geometry_msgs/msg/PoseStamped` | llm_node | navigator_node | Navigation goal pose extracted from navigation intent. |
| `tts/speaking` | `std_msgs/msg/Bool` | tts_node | - | True while TTS is actively speaking (used for mic mute by external STT). |
| `nav/global_path` | `nav_msgs/msg/Path` | navigator_node | - | Planned global path visualization/output. |
| `nav/local_path` | `nav_msgs/msg/Path` | navigator_node | - | Local path / short-horizon trajectory visualization. |
| `nav/status` | `std_msgs/msg/String` | navigator_node | - | Human-readable navigation status updates. |
| `nav/cancel` | `std_msgs/msg/Bool` | external/nav client node | navigator_node | Cancel signal for current navigation task. |
| `system/metrics` | `std_msgs/msg/String` | system_monitor_node | - | Periodic system metrics JSON (CPU/RAM/Disk/GPU). |
| `/map` | `nav_msgs/msg/OccupancyGrid` | SLAM / map server | navigator_node | Occupancy map used for global path planning. |
| `dori/stt/audio_input` | `std_msgs/msg/String` | dashboard_frontend | - | Dashboard/client microphone STT input (robot+sim profile canonical). |
| `dori/perception/vision/image/compressed` | `sensor_msgs/msg/CompressedImage` | dashboard_frontend | - | Dashboard/client camera compressed image input (robot+sim profile canonical). |
| `dori/audio/output` | `audio_common_msgs/msg/AudioData` | dashboard_frontend | - | ROS audio output stream for dashboard ros_audio playback mode. |
<!-- TOPIC:END -->


The detailed API reference for ROS2 topics is managed as a single source at [`topics.adoc`](docs/dev/topics.adoc).

- Topic source of truth: [`config/ros2_topics.yaml`](config/ros2_topics.yaml)
- Sync/check tool: `python3 tools/topic/topic_lint.py --sync-architecture`, `python3 tools/topic/topic_lint.py --check`
- Detailed documentation: [`docs/dev/topics.adoc`](docs/dev/topics.adoc)

#### Global ROS topic naming policy (all packages)

- Canonical rule: **all nodes and dashboard publishers/subscribers** must use relative topics in code (e.g. `stt/audio_input`, `perception/vision/image/compressed`, `tts/text`).
- Launch files own final routing by namespace/remapping (e.g. `namespace:=/dori` → runtime topic `/dori/stt/audio_input`).
- Do not hardcode absolute `/dori/...` topics in node implementation or frontend code.
- This rule is global (voice, perception, navigation, dashboard) and not camera-only.


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

## Dashboard Execution Profile (Robot/Sim)

- Settings > Connection 에서 `Execution Profile` 을 `Robot|Sim` 으로 전환한다.
- Sim 프로파일은 데모(mock) 모드와 다르며, **실제 ROS 그래프를 타는 테스트 모드**다.
- 기본 토픽은 프로파일 기반 자동 매핑을 사용한다.
  - STT 입력: `stt/audio_input`
  - Vision 입력: `perception/vision/image/compressed`
  - TTS 텍스트: `tts/text`
  - ROS 오디오 출력(옵션): `audio/output`
- 모바일 브라우저 오디오 제약: HTTPS + 사용자 제스처 필요.

## Remote device test guide (phone/laptop)

1. 노트북/폰에서 대시보드 접속 (`http://[Robot IP]:3000`).
2. Settings > Connection 에서 WS URL 확인 후 연결 (`ws://[Robot IP]:9090`).
3. `Execution Profile=Sim` 으로 설정 후 Client Mic/Cam 활성화.
4. STT Panel에서 mic 녹음 전송 → `stt/audio_input`(런타임 `/dori/stt/audio_input`) 유입 확인.
5. Vision Panel에서 프레임 publish → `perception/vision/image/compressed`(런타임 `/dori/perception/vision/image/compressed`) 유입 확인.
6. Speaker Output 모드를 `browser_tts` 또는 `ros_audio` 로 선택해 재생 경로 확인.

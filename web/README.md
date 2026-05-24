# DORI Dashboard Frontend (`web`)

This directory contains the Vite/React frontend for the DORI dashboard.

## Build (Required before first launch)

Build frontend assets before launching the dashboard.

```bash
cd web
npm ci   # or: npm install
npm run build
```

After the build completes, continue from the ROS workspace root:

```bash
cd ..
colcon build --symlink-install
source install/setup.bash
```

## Launch
 
The dashboard can be launched in three clear modes:

- Full stack + dashboard (default): `ros2 launch bringup robot_dev.launch.py`
  - Equivalent explicit form: `ros2 launch bringup robot_dev.launch.py enable_dashboard:=true`
- Full stack without dashboard: `ros2 launch bringup robot_dev.launch.py enable_dashboard:=false`
- Dashboard only (standalone): `ros2 launch dashboard_pkg dashboard.launch.py`
 
```bash
# Full stack + dashboard (default)
ros2 launch bringup robot_dev.launch.py

# Full stack + dashboard (explicit)
ros2 launch bringup robot_dev.launch.py enable_dashboard:=true

# Full stack without dashboard
ros2 launch bringup robot_dev.launch.py enable_dashboard:=false
```
 
If you need to run the dashboard standalone (without the full robot stack):
 
```bash
ros2 launch dashboard_pkg dashboard.launch.py
```
 
## Access

- Dashboard: `http://[Robot IP]:3000` (`knowledge_api.py` serves port 3000)
- ROS WebSocket bridge: `ws://[Robot IP]:9090`

If dashboard startup fails, check whether runtime dependencies are installed in the ROS/Python environment: `fastapi`, `uvicorn`, `python-multipart`.

```text
# Same machine (robot/local)
http://localhost:3000
ws://localhost:9090

# Another device on same network (remote)
http://[Robot IP]:3000
ws://[Robot IP]:9090
```

For broader project context, see the root README: [../README](../README.md).

## Style system

```
web/src/styles/
  tokens.css      ← color, font, and spacing tokens
  layout.css      ← grid layout classes
  components.css  ← reusable UI: buttons, badges, inputs, log panes, etc.
```

`index.css` globally imports all three, so each panel CSS only needs to `@import` what it uses.
For the full design conventions, see [web-style.md](../docs/dev/web-style.md).

## Panel structure convention

Panel implementations live exclusively under `web/src/panels/<domain>/`.
Each panel follows the **one file, one component** rule
(e.g. `web/src/panels/system/EventLogPanel.jsx`, `web/src/panels/hri/STTPanel.jsx`).

- Example domain folders: `hri/`, `control/`, `perception/`, `conversation/`, `system/`
- `web/src/panelTree.jsx` imports panel components only from `web/src/panels/...`
- New and migrated styles go in the panel-adjacent CSS file
  (`web/src/panels/<domain>/<PanelName>.css`). Styles shared across multiple panels go in
  the three files under `web/src/styles/`

### Adding a new panel

1. Create the panel file under `web/src/panels/<domain>/` (one component per file)
2. Export the component as a named export
3. Add the import to `web/src/panelTree.jsx`
4. Register it at the appropriate leaf node in `PANEL_TREE` with `component: <YourPanel>`
5. Add default window dimensions to `PANEL_SIZES` in `web/src/core/floatingPanels.js`
6. Only add a re-export to `web/src/tabs/` if a legacy entry point requires it

System panels include `Event Log` and `Topic Publisher`, located at
`web/src/panels/system/EventLogPanel.jsx` and `web/src/panels/system/TopicPublisherPanel.jsx`.

### Header ownership rule

- `FloatingPanel` and `MobileStack` own the window title and minimize/close controls.
  Panels rendered inside them must be **content-only roots** and must not recreate an
  internal `Panel` header.
- Sidebar or fixed tab layouts may still use `web/src/components/Panel.jsx` when a local
  card header/body shell is needed.
- When moving a panel between layouts, keep header responsibility in exactly one layer and
  move any padding, overflow, or badge UI into the panel-specific root or CSS.

## Execution Profile and I/O routing

- Settings > Connection 에서 Execution Profile (`Robot`/`Sim`)을 선택합니다.
- Sim은 demo(mock)와 분리된 모드이며, 실제 ROS 토픽 파이프라인 검증용입니다.
- 기본 라우팅
  - STT input: `stt/audio_input`
  - Vision input: `perception/vision/image/compressed`
  - Browser TTS trigger: `tts/text`
  - ROS audio stream (optional): `audio/output`
- 모바일 브라우저 오디오 사용 시 HTTPS/사용자 제스처가 필요할 수 있습니다.

## Remote device test guide (phone/laptop)

### 출력 검증 절차 (공통)

1. 원격 장치(PC/모바일 브라우저)에서 대시보드 접속: `http://[Robot IP]:3000`.
2. Settings > Connection 에서 WS 연결: `ws://[Robot IP]:9090`.
3. `Execution Profile=Sim` 설정 후 Client Mic/Cam 활성화.
4. STT Panel에서 mic 녹음 전송 후 `stt/audio_input`(런타임 `/dori/stt/audio_input`) 수신 확인.
5. Vision Panel에서 프레임 publish 후 `perception/vision/image/compressed`(런타임 `/dori/perception/vision/image/compressed`) 수신 확인.
6. Speaker Output 모드를 시나리오에 맞게 선택하고 TTS 재생을 트리거한다.
7. 아래 시나리오별 기대 장치에서 실제 음성이 출력되는지 확인한다.

### 최소 시나리오 (분리)

| 시나리오 | 클라이언트 장치 | Speaker Output | 기대 결과(소리 출력 장치) |
| --- | --- | --- | --- |
| A | PC 브라우저 | `browser_tts` | **해당 PC의 스피커**에서 소리가 나야 한다. |
| B | 모바일 브라우저 | `browser_tts` | **해당 모바일 기기 스피커**에서 소리가 나야 한다. |
| C | 모바일 브라우저 | `ros_audio` | **ROS 오디오 출력이 연결된 외부/로봇 스피커**에서 소리가 나야 한다 (모바일 스피커 아님). |

### 실패 시 점검 항목

| 점검 항목 | 증상 예시 | 확인 방법 |
| --- | --- | --- |
| HTTPS | 모바일에서 재생이 시작되지 않음 | 원격 접속 URL이 HTTPS인지 확인(모바일 정책상 필요 가능). |
| User gesture | 재생 요청은 보냈지만 음성이 무음 | 재생 버튼 탭/클릭 등 사용자 제스처 이후 재시도. |
| AudioContext resume | 브라우저 콘솔에 suspended 상태 | 개발자도구에서 `AudioContext` 상태 확인 후 resume 트리거. |
| WS 연결 | 패널 값/이벤트가 갱신되지 않음 | Settings > Connection 상태 및 `ws://[Robot IP]:9090` 연결 상태 확인. |
| 토픽 수신 | STT/Vision/TTS 경로가 동작하지 않음 | `stt/audio_input`, `perception/vision/image/compressed` 등 토픽 수신 여부를 `ros2 topic echo`로 확인. |


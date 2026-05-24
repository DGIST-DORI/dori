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

# DORI Dashboard Frontend (`web`)

This directory contains the Vite/React frontend for the DORI dashboard.

## Build (Required before first launch)

From the repository root, build both apps, their runtime dependencies and ROS
packages together:

```bash
scripts/build.sh
```

Source the Humble/Python 3.10 environment with `source scripts/env.sh` or follow
[AMM 20-10/20-12](../docs/user/DORI-AMM.md).
The ROS workspace is `ros2_ws`; the installed dashboard must contain this fresh
web build. For package migrations, follow the clean-overlay procedure in AMM 20-15.

## Launch

The default bringup (`dori_mode:=robot`) starts hardware drivers, LiDAR, Nav2,
the required front camera/person detector, visitor app, Azure voice gateway, LLM/TTS, interaction tree, dashboard and
navigation viewer. It requires `map:=...` and the device preparation in AMM 40-10.
For frontend/HRI development, use `dori_mode:=desktop` as shown below.
In desktop mode, the map backend starts automatically with the dashboard
and restarts after an unexpected exit. It listens only on `127.0.0.1:8080`; it
does not open the standalone user port or start hardware/Nav2. Without a running
robot/map source, the panel connects in monitor mode and waits for data.
Use `bringup.launch.py` for normal operation; it selects the `robot.launch.py`
profile by default. Map-based operation keeps `visitor_mode:=true`.
`config_file` selects deployment YAML;
explicit arguments override it. The navigation panel shows component startup
readiness from `/dori/bringup/status`, including normal initial-pose waiting and
missing/stale data. Robot startup stops the session on required readiness timeout.

After configuring the Azure F0 settings and shared authentication below:

```bash
# Visitor app + dashboard on a development PC
ros2 launch dori_bringup bringup.launch.py dori_mode:=desktop

# Explicit local robot microphone HRI + dashboard (requires local voice assets)
ros2 launch dori_bringup bringup.launch.py dori_mode:=desktop visitor_mode:=false

# Local robot microphone HRI without dashboard
ros2 launch dori_bringup bringup.launch.py dori_mode:=desktop visitor_mode:=false enable_dashboard:=false
```

If you need to run the dashboard standalone (without the desktop HRI stack):

```bash
ros2 launch dori_dashboard dashboard.launch.py
```

If a separately managed viewer already owns port 8080, launch the dashboard with
`enable_navigation_viewer:=false`. The integrated `robot.launch.py` sets this
automatically because it supplies its own navigation-mode viewer. Stop a desktop
dashboard session before switching to the full hardware launch.

After installing this update, remove the temporary recovery viewer before the
next normal dashboard launch: `systemctl --user stop dori-navigation-viewer.service`
(only if that temporary service is running). The dashboard launch then owns the
viewer lifecycle. This follows the dashboard's existing startup mechanism; it
does not install a new boot service for the dashboard itself.

## Access and authentication

The dashboard binds to `127.0.0.1:3000` in production. Open
`https://dash.dgist-dori.xyz` through the dashboard tunnel. Both local and remote
browsers use the same-origin `/ws/admin` proxy; port 9090 is loopback-only.
The user gateway uses port 3100, and the display/internal API uses loopback port
3001. Neither 3001 nor 9090 may appear in Cloudflare ingress.

Install the root `requirements-runtime.txt` in the ROS Python venv before
building the dashboard package. It includes `PyJWT[crypto]` for RSA verification.
The launch uses the repository `.venv/bin/python` when present. Both API scripts
and their shared modules are included in the installed package.

Before starting either API, set `DORI_INTERNAL_TOKEN` to a random secret of at
least 32 characters in their shared environment (for example, generate one with
`openssl rand -hex 32`). Missing/short secrets refuse startup, including direct
script and uvicorn startup. Do not put secrets in source control.

For normal operation, protect the **entire dashboard hostname**, including
`/api/*`, `/navigation/*`, and `/ws/admin`, with Cloudflare Access. Configure:

- `DORI_CF_TEAM_DOMAIN=https://YOUR-TEAM.cloudflareaccess.com`
- `DORI_CF_AUDIENCE=<Access application AUD>`
- `DORI_CF_ROLE_MAP=admin@example.org:admin,operator@example.org:control`

The backend also reads `config/dashboard_access.json` under its repository root
(`--repo-root`). It contains the non-secret team domain and application AUD for
`dash.dgist-dori.xyz`, so normal launches and respawns retain Access verification
without shell exports. The corresponding environment variables override each
file value, including explicitly empty values. For another Access application,
set its team domain and AUD together. `role_map` lists the explicitly assigned
operator/admin accounts; unlisted identities remain viewers. Never put JWTs or
secrets in this file.
A missing verification configuration returns 503 and the login screen displays
the configuration error instead of silently requesting another login.

The backend verifies RS256 signatures, issuer, audience, subject, and finite
expiry. JWKS fetching runs outside the event loop with a three-second timeout
and cached keys. Unmapped identities have viewer permissions. Cloudflare issues
the production token; the application does not expose an unauthenticated token
issuance endpoint. See [Cloudflare JWT validation](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/).

For local fallback, configure a random `DORI_API_JWT_SECRET` of at least 32
characters, optionally `DORI_API_JWT_ISSUER` and `DORI_API_JWT_AUDIENCE`, and issue
a token **on the trusted host** using the same environment:

```bash
.venv/bin/python tools/auth/issue_dashboard_token.py --user operator --role admin --ttl 900
```

The login screen puts email sign-in first. It uses the saved dashboard language
or detects Korean/English from the browser, and provides a language selector
before sign-in. Token login is available under **Other sign-in options**
(**다른 로그인 방법**); paste a locally issued token there when needed.

The shared API wrapper uses an HttpOnly,
SameSite=Strict session cookie (Secure on HTTPS); tokens are never saved in
localStorage/sessionStorage. The cookie expires within 15 minutes and never
outlives the source JWT. This also authenticates the navigation panel requests. API 401s
return the UI to login. Logout clears the local session and tickets; Access
logins additionally use Cloudflare's [logout endpoint](https://developers.cloudflare.com/cloudflare-one/access-controls/access-settings/session-management/).

Static `Access` tokens are disabled unless `DORI_ENABLE_BREAK_GLASS=true` is
explicitly set alongside `DORI_API_ACCESS_TOKENS=TOKEN=user:admin`. Enable only
for an incident and remove afterwards. Admin WS connections obtain a 30-second,
one-use ticket over the authenticated API; long-lived URL tokens are rejected.
Origins, admin roles, session expiry and logout are checked; disconnecting either
side cancels the other forwarding task. Authentication sessions/tickets are
in memory: use one API worker, and expect re-login after a restart.

`DORI_DEV_MODE=true` deliberately exposes the HTTP listeners on the LAN for
development; it does not expose rosbridge or disable authentication. Prefer
HTTPS or an SSH port forward when entering a token. For Vite development,
`/api`, `/navigation`, and `/ws` are proxied to localhost:3000.

## Dashboard control contract

### Navigation panel

`Navigation → Map → Robot Map & Navigation` renders a native React canvas and
controls. The existing `/navigation/api/{session,state,map.png,command}` proxy
continues to connect to the navigation web viewer on loopback port 8080. Run the
hardware/navigation stack for live data; starting the dashboard alone starts the
viewer in auto-detection mode, but does not start Nav2. The standalone
`/navigation/` viewer remains available.

The panel supports map pan/zoom, robot follow, initial pose and goal direction,
named destination editing, AUTO stop, and sensor/drive diagnostics. Narrow panels
and mobile screens stack the controls below the map. Viewer accounts can inspect
data; control, deploy, and admin roles can use the command controls, matching the
backend permission policy.

State polling runs 200ms after each response. A 1.5-second gap disables motion
controls; upstream failures and stale ROS snapshots are displayed. Map images
refresh on version changes. Server/coordinate-system changes clear pending pose
selections. Commands are never automatically replayed on reconnect.

Each mounted panel has its own control client ID. Only the owning client sends
heartbeats. Closing/minimizing the panel ends polling and heartbeat; the existing
server lease expires after 10 seconds and stops AUTO. Use **AUTO 정지** for an
explicit stop before closing; ESC sends that same request only while focus is
inside this panel. This retains the navigation stop behavior, separate from the
dashboard's emergency-stop latch. Reopening never automatically acquires control.

Frontend regression checks: `npm test`, `npm run lint`, and `npm run build`.
Navigation client tests cover permissions, stale state, ownership/heartbeat,
restart, HTTP failures and cleanup; geometry tests cover rotated map origins,
coordinate conversion, cursor-anchored zoom and pose input. Physical driving and
stopping still require the hardware acceptance checks below.

For the browser regression, start Vite on loopback port 5178, install Playwright
and its Chromium browser in your test environment, then run
`node tests/navigation.browser.mjs` from `web`. Set `PLAYWRIGHT_MODULE` to an
external Playwright module path if it is not installed locally, and
`PLAYWRIGHT_BROWSERS_PATH` if using a custom browser cache. `NAV_TEST_URL` can
override the Vite URL. The test intercepts all API calls with fixtures and never
sends robot commands. It checks pose selection, destination CRUD, scoped ESC,
map caching, resizing/mobile, ownership, reconnect, cleanup and authentication.
Desktop/mobile screenshots are written under `/tmp/dori-navigation-*.png`.

### Manual control

Open **Control → Hardware → Hardware Control** for manual driving, A/B posture
changes, stop/resume, motor feedback and body pitch/rate/stabilization telemetry.
This panel uses the authenticated HTTP control API; it does not require an admin
ROS WebSocket. Viewers can inspect status; operators/admins can send commands.

Hold a direction with a pointer/touch or Space/Enter. Releasing the button,
losing focus, hiding the page, minimizing/closing the panel, stale status or a
failed request sends a latched stop. **비상 정지** (or Escape while focused inside
the panel) is always available to an authorized operator, including after status
disconnects. **정지 해제 / 변형 재개** explicitly publishes emergency-go, returns
to manual mode, and resumes a paused transform if one exists. A/B requests use
the supervisor and existing transform sequence, requiring fresh motor 1–4
feedback. Motor values older than 0.5 seconds and unavailable effort values are
shown as missing. The panel does not send raw CAN, encoder-zero or torque commands.

Use **실제 제어 켜기 / 실제 제어 끄기** in the panel to switch between live and
simulated commands at runtime. No environment change or restart is needed for
each switch. The bridge owns one shared setting for all dashboards; viewers
cannot change it. Enabling requires a connected supervisor and no competing
joystick/keyboard publisher. Each change latches a stop, so enabling alone never
starts driving or resumes a transform. Explicitly use **정지 해제 / 변형 재개**
after enabling. Disabling remains available during motion and stale UI status.

The bridge starts in simulation after every restart. Opening/reconnecting a
panel never enables live control. The old `DORI_CONTROL_EXECUTOR` variable no
longer selects the executor; the UI and authenticated control API replace it.
The selected setting governs dashboard commands, not other joystick or Nav2
command sources. A running joystick/keyboard input must still be stopped before
enabling dashboard control; this switch does not terminate its process.

- `move`: normalized manual joystick values, **not** SI velocity; `linear_x`
  is in [-0.8, 0.8], `linear_y` must be 0, and `angular_z` is in [-1, 1].
  NaN, infinity, booleans and strings are rejected at both API boundaries.
- The persistent bridge publisher targets `/manual/cmd_vel`, which goes through
  the supervisor. Move requires manual mode, idle/drive state, a supervisor
  subscriber, and no other manual publisher (stop the joystick/keyboard input
  process before this test). Commands must be refreshed within 0.5 seconds.
- The bridge's ROS-thread watchdog latches `/emergency_stop` when refreshes stop
  or another manual publisher appears. The downstream drive controller's
  existing 0.3-second command timeout also stops output if the bridge crashes.
- User WS `STOP`, API `stop` in live mode, and live/simulation transitions publish
  `/emergency_stop` plus `/dori/hri/cancel`. In simulation, API `stop` only
  invalidates pending commands and does not publish to hardware.
  The supervisor prevents subsequent manual/auto commands from overriding this
  latch. An operator must explicitly resume using emergency-go or the panel's
  resume button; the web API does not automatically clear a stop.
- `resume` publishes `/emergency_go`; `transform` accepts `pose: "A" | "B"`
  and publishes `/manual/transform_cmd`. Command delivery is shown separately
  from actual controller feedback and does not claim physical completion.
- `GET /api/control/state` provides role-filtered control availability and
  telemetry. The panel includes its `client_id` and the current `control_epoch`
  in action parameters. A second client cannot overwrite active manual driving;
  stop invalidates outstanding commands from the panel and is never rate-limited.
- `set_live_control` accepts `enabled: true | false`. Enabling and all live
  commands except stop require the current `control_epoch`; switching invalidates
  it. Disabling accepts stale state and is never rate-limited. Delayed simulated
  commands cannot execute after live control is enabled, and a held simulated
  input stops when another dashboard changes the setting.
- `set_mode` supports only `manual` (Int32 0) and `auto` (Int32 1), published to
  `/control_mode_cmd`. `dock`, `idle`, and `safe` are not supervisor control modes.
- Pairing/LLM/BT traffic uses the actual `/dori` namespace. Low-level hardware
  input topics retain their existing absolute names.

Hardware checks include `test_hardware_control.py`, the dashboard security tests,
and frontend tests under `src/panels/control/hardware`. With Vite on port 5179,
run `PLAYWRIGHT_MODULE=/path/to/playwright node tests/hardware.browser.mjs` from
`web` for mocked browser checks (no robot commands). An optional real-supervisor
test is in `tests/integration/test_hardware_supervisor.py`; it requires a separate
test executable, `ROS_DOMAIN_ID=97`, and `ROS_LOCALHOST_ONLY=1`, and uses only
synthetic motor feedback. Physical movement and stopping remain unverified.

## Deployment checks and review status (2026-11-03)

The review found session DELETE constant-time comparison, nonce invalidation,
loopback rosbridge and removal of the 9090 quick tunnel already implemented.
This revision removes fixed IPC-secret fallback, fixes installed bridge scripts,
adds CF issuer/expiry checks and nonblocking JWKS, replaces raw control with the
supervisor/deadman path, and supplies browser login plus one-use WS tickets.
`DORI_WS_URL` and the old `ws_url` launch option no longer select a raw ROS tunnel.

On the reviewed host, `/etc/cloudflared/config.yml` and the user config contain
only dashboard:3000, app:3100 and a 404 catch-all. None of 3000, 3001, 3100, 9090
was listening at inspection. **UFW is not installed.** Running Cloudflare Access
policy, post-restart port exposure, and physical stopping distance are not yet
verified by these code tests.

Validation for this revision: 31 related Python tests passed (session/auth,
control deadman, launch/packaging and documentation), frontend lint/tests/build
passed, and an isolated colcon build installed both API scripts, shared modules,
and the console entrypoint. Installed scripts were imported without starting
servers or ROS nodes. Tests used `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` because the
host's ROS `launch_testing` plugin is incompatible with pytest 9; thread-based
tests ran outside the sandbox after a minimal asyncio example reproduced its
thread-notification restriction. Existing uvicorn/websockets deprecation
warnings remain. No live robot motion or production service restart was tested.

Before production acceptance:

1. Rebuild/install `dori_dashboard` with the current frontend, supply the shared
   IPC secret and actual Access team/AUD/role mapping, and start the dashboard.
2. Check `ss -ltnp`: 3000/3001/3100/9090 must be loopback in production. Verify
   `/internal/session` returns 404 on 3100 and raw 9090 is unreachable from LAN.
3. Validate the active cloudflared ingress as well as the local config. `ws.`
   must have no route to 9090; `/ws/admin` must reject unauthenticated upgrades.
4. Apply the host's approved firewall policy. For UFW, install it, preserve
   existing SSH/Tailscale/ROS management access, and block inbound TCP 3001/9090
   on non-loopback interfaces. Confirm management ports/subnets before enabling
   a previously absent firewall; enabling UFW was not part of this code test.
5. With wheels lifted and an operator at the stop switch, verify manual/auto
   priority, STOP latch, a lost browser connection, bridge termination, and the
   measured stopping distance. Keep dry-run until this acceptance is complete.

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
- Sim은 실제 ROS 토픽 파이프라인 검증용 프로파일이며, ROS 연결이 필요합니다.
- 기본 라우팅
  - STT input: `stt/audio_input`
  - Vision input: `perception/vision/image/compressed`
  - Browser TTS trigger: `tts/text`
  - ROS audio stream (optional): `audio/output`
- 모바일 브라우저 오디오 사용 시 HTTPS/사용자 제스처가 필요할 수 있습니다.

## Remote device test guide (phone/laptop)

### 출력 검증 절차 (공통)

1. 원격 장치(PC/모바일 브라우저)에서 대시보드 접속: `https://dash.dgist-dori.xyz`.
2. Settings > Connection 에서 WS 연결: `wss://dash.dgist-dori.xyz/ws/admin`.
3. `Execution Profile=Sim` 설정 후 Client Mic/Cam 활성화.
4. STT Panel에서 mic 녹음 전송 후 `stt/audio_input`(런타임 `/dori/stt/audio_input`) 수신 확인.
5. Vision Panel에서 프레임 publish 후 `perception/vision/image/compressed`(런타임 `/dori/perception/vision/image/compressed`) 수신 확인.
6. Speaker Output 모드를 시나리오에 맞게 선택하고 TTS 재생을 트리거한다.
7. 아래 시나리오별 기대 장치에서 실제 음성이 출력되는지 확인한다.

### 최소 시나리오 (분리)

| 시나리오 | 클라이언트 장치 | Speaker Output | 기대 결과(소리 출력 장치)                                                                |
| -------- | --------------- | -------------- | ---------------------------------------------------------------------------------------- |
| A        | PC 브라우저     | `browser_tts`  | **해당 PC의 스피커**에서 소리가 나야 한다.                                               |
| B        | 모바일 브라우저 | `browser_tts`  | **해당 모바일 기기 스피커**에서 소리가 나야 한다.                                        |
| C        | 모바일 브라우저 | `ros_audio`    | **ROS 오디오 출력이 연결된 외부/로봇 스피커**에서 소리가 나야 한다 (모바일 스피커 아님). |

### 실패 시 점검 항목

| 점검 항목           | 증상 예시                           | 확인 방법                                                                                             |
| ------------------- | ----------------------------------- | ----------------------------------------------------------------------------------------------------- |
| HTTPS               | 모바일에서 재생이 시작되지 않음     | 원격 접속 URL이 HTTPS인지 확인(모바일 정책상 필요 가능).                                              |
| User gesture        | 재생 요청은 보냈지만 음성이 무음    | 재생 버튼 탭/클릭 등 사용자 제스처 이후 재시도.                                                       |
| AudioContext resume | 브라우저 콘솔에 suspended 상태      | 개발자도구에서 `AudioContext` 상태 확인 후 resume 트리거.                                             |
| WS 연결             | 패널 값/이벤트가 갱신되지 않음      | Settings > Connection 상태 및 `wss://dash.dgist-dori.xyz/ws/admin` 연결 상태 확인.                                  |
| 토픽 수신           | STT/Vision/TTS 경로가 동작하지 않음 | `stt/audio_input`, `perception/vision/image/compressed` 등 토픽 수신 여부를 `ros2 topic echo`로 확인. |

## Visitor voice app (app. host)

The mobile visitor app has its own frontend alongside the developer dashboard.
The standard `scripts/build.sh` installs runtime dependencies (including Azure
Speech), builds both frontends, and packages them with ROS. No separate visitor
build is required; `npm run test:visitor` tests its PCM/WAV encoder.
`dist-visitor` installs into `share/dori_dashboard/visitor_web` when rebuilding
`dori_dashboard`. The regular dashboard build and authentication are unchanged.
The existing `control` role and the `operator` alias both permit operator actions.

The default bringup selects the visitor profile. It disables BT
wake-triggered following, local STT intents, gestures and automatic patrols.
Visitor text/voice requests and destination buttons can dispatch registered
destinations through `nav/navigate_named` when the real navigation stack is
running. Following remains unavailable. For a desktop session:

```bash
# Build both apps and ROS packages; configure the private F0 settings below once.
scripts/build.sh
source scripts/env.sh
# Stop any existing desktop/dashboard session first, then:
export DORI_INTERNAL_TOKEN="$(openssl rand -hex 32)"
ros2 launch dori_bringup bringup.launch.py dori_mode:=desktop
```

`bringup.launch.py` defaults to `dori_mode:=robot`, `visitor_mode:=true`, `enable_dashboard:=true`
and Azure STT. It sets `DORI_VISITOR_STT` for the gateway and automatically
disables the local Whisper STT node. Azure recognition runs in the gateway;
the launch checks the SDK and local F0 settings with the same Python environment
before starting the session. `visitor_mode:=false` explicitly selects robot
microphone input and disables visitor pairing. There is one standard bringup
entrypoint for the app and dashboard.

To explicitly use the previous local provider, first run
`scripts/prepare_voice.sh --topic-only`, then
`ros2 launch dori_bringup bringup.launch.py dori_mode:=desktop visitor_stt:=whisper`. This enables
topic STT and selects `.state/voice/whisper-small` automatically. The
`visitor_stt` argument overrides `DORI_VISITOR_STT`; Azure is the default when
neither is set. There is no automatic cloud
retry, paid-tier upgrade or fallback to another recognition provider.

The normal dashboard authentication variables, a random `DORI_INTERNAL_TOKEN`
remain required; Azure visitor mode does not require a Whisper model. Azure keys
stay in `.state/voice/azure.env`, or the file named by `DORI_AZURE_ENV_FILE` (see
the F0 configuration below). The file is read as data and never sourced as shell.
To use local Whisper for visitor input with the robot profile,
pass `visitor_stt:=whisper` to `bringup.launch.py`
alongside its required map and hardware settings. Visitor mode remains enabled.
Do not start duplicate HRI
nodes. Pairing returns 503 unless `bt/visitor_ready` confirms the voice-only
profile and BT, LLM and TTS cleanup succeeds. Local STT mode also requires its
STT reset; Azure mode drains its own per-turn stream instead. Starting the dashboard alone does
not activate or stop physical hardware.

Open `http://127.0.0.1:3001/display` on the robot screen. QR codes are rendered
locally, rotate every 30 seconds, have a five-second overlap, and disappear while
occupied. On page entry the phone immediately exchanges a valid QR at
`POST /api/pair/claim {nonce}` for a Secure, HttpOnly, SameSite=Strict scan cookie
valid for two minutes. This does not activate a robot session or request media
permissions. The visitor can read the consent text while the displayed QR
rotates. `POST /api/pair {consent:true}` completes pairing using that cookie;
legacy requests containing a still-valid `nonce` are also accepted.
`GET /api/pair/claim` restores the remaining time after reload without extending
it. A new QR scan can replace the previous proof. Successful pairing clears all
pending scan proofs; 503 readiness failures keep the current proof available
for retry. Expired scans, busy sessions and unavailable voice services have
separate messages. Multiple displays refresh on the same rotation deadline.

The robot display gives the current connection state priority over the greeting, with
scan instructions while idle and distinct conversation, reconnecting, cleanup,
and connection-loss screens. The original Dori logo is embedded in the HTML,
so the installed display needs no external asset server or frontend build.
QR images appear only after loading and are hidden at the advertised rotation
deadline or when the session/connection changes; delayed image responses cannot
restore an old code. The layout adapts to landscape and narrow screens.

Only tunnel `app.dgist-dori.xyz` to `http://127.0.0.1:3100` and the
Access-protected `dash.dgist-dori.xyz` to port 3000. Never register 3001 or 9090 in
a tunnel. The default listeners are loopback; `DORI_DEV_MODE` explicitly widens
public binding and must stay off in production. Firewall changes and Cloudflare
account configuration are deployment operations, not performed by the build.

For a local HTTPS demo, configure `DORI_VISITOR_ORIGIN=https://<trusted-local-host>:3100`,
`DORI_VISITOR_TLS_CERT` and `DORI_VISITOR_TLS_KEY` with a certificate trusted by the
phone. Both certificate and key are required. Reach the loopback service through
a local TLS proxy, or explicitly enable development binding on an isolated demo
network. Cookies remain Secure in all modes. Set `DORI_VISITOR_WEB_DIR` when
running the bridge directly from an installed location without dashboard launch.

The user protocol is JSON over `/ws/user`, protected by the session cookie and
an exact Origin check. Supported input messages:

- `heartbeat` every 5 seconds; it does not extend the 180-second idle deadline.
- `ptt_start` marks a microphone gesture in legacy Whisper mode as user activity,
  before recording is uploaded. It never opens a server microphone.
- `ptt_audio` with `audio_b64`, `format: "wav_pcm16"`, `sample_rate: 16000`,
  `channels: 1`; legacy Whisper mode only, 0.5–120 seconds, one outstanding turn,
  5,130,000-byte WS limit.
- `stt_start` with a fresh `id` (16–64 letters/digits/underscore/hyphen),
  `format: "pcm16"`, `sample_rate: 16000`, `channels: 1`; Azure mode only.
  Wait for `stt_ready` with the same ID before sending audio.
- `stt_chunk` with the same `id`, consecutive integer `seq` starting at 0, and
  `audio_b64`: raw little-endian PCM16, **no WAV header**. The browser sends
  100 ms / 3200-byte chunks; the gateway accepts at most 8000 bytes per frame and
  3,840,000 bytes per turn. Stale IDs cannot feed or finish another turn.
- `stt_end` with `id` and the next `seq` closes input on manual finish or the
  two-minute capture limit; `stt_cancel` with `id` discards that turn.
- `text` with `text`: a nonblank string of at most 1,000 characters. The gateway
  trims surrounding whitespace, echoes accepted input as `user_text`, skips STT,
  and uses the same LLM and remote TTS actions as microphone input. Audio and text
  share one outstanding turn, cancellation, idle activity and cleanup rules.
- `navigate` with `destination_id`: selects an ID from the current destination
  snapshot. The gateway validates the ID and skips LLM interpretation for buttons.
  The named action server revalidates the destination against the active map.
- `command` with `action: "CANCEL_RESPONSE"` cancels only STT/LLM/TTS. The app
  immediately stops local playback, keeps the draft, and waits in `CANCELING`
  until the action drains. In-flight reply/media events are ignored during that wait.
- `command` with `action: "CANCEL_NAVIGATION"` cancels only the named navigation
  action, including late goal acceptance. Conversation and phone playback continue.
- Legacy `command` with `action: "STOP"` cancels both scopes without clearing an
  operator emergency stop. The app's two scoped controls do not use global STOP.
  Unsupported commands, including GUIDE/FOLLOW, fail.
- `playback` with the issued audio `id` and `status: "ended" | "failed" | "canceled"`.
- `end` closes and cleans up the session; `DELETE /api/session` is also available.

Outputs are `robot_state` (READY/TRANSCRIBING/THINKING/SPEAKING/CANCELING), `stt_text`, `user_text`,
`llm_text` (spoken `data` plus optional display-only `sources`), `tts_audio` (id and authenticated URL), `command_result`, and `error`.
The initial READY snapshot includes `stt_provider`, `destinations` (ID/name), and
a separate `navigation` snapshot. `navigation_state` events contain `status`
(IDLE/STARTING/NAVIGATING/STOPPING/ARRIVED/FAILED), `destination` (ID), and `name`
when a destination is known. They never reset the conversation state.
Subsequent `destinations` events replace the whole list, including empty lists
after a map change or deletion. `GET /api/destinations` exposes the same snapshot
with session authentication. The app uses the WebSocket snapshot to avoid races
with older HTTP responses.

Both the LLM and gateway subscribe to the named adapter's transient-local
`/dori/nav/locations`; they never combine maps or load example destinations.
The web viewer and named adapter share `maps/web_goals.json` under `DORI_WS`
(then `DORI_SESSION_ROOT`, then the working directory), unless a goals file is
explicitly supplied. In real bringup, pass the same absolute `named_goals_file`
to both via the launch argument. A desktop-only session has no navigation server
and therefore no destination buttons; start the real navigation profile before
requesting motion.

“길안내 해줘” asks for a destination; a subsequent name such as “e6 gate” or
“계단” resolves only against the active registry. Ambiguous/unknown destinations
do not produce a motion target. A successful departure announcement must finish
playing before dispatch. Navigation then runs independently, so text and voice
questions remain available during movement. There is at most one conversation
and one navigation action; choosing a different destination requires stopping
the existing navigation first. Each scope owns its action handle and drain
barrier. Disconnect, session end and global STOP cancel both and cleanup waits
for both terminal results, including late acceptance. A separate navigation
banner shows progress, failure and successful arrival. Arrival is visual and
does not interrupt microphone capture or speak over a conversational answer.

Azure additionally sends
`stt_ready` and `stt_closed` with the client stream ID. On `stt_closed`, the app
stops its microphone immediately; the server still drains buffered final segments
before emitting one `stt_text` and starting the existing LLM/TTS actions.
`GET /api/session` permits page reload recovery. MP3 URLs are unpredictable,
require the active cookie, have no-store caching, and expire after playback or
cancellation. Pairing uses a global limit of 30 attempts/minute, intentionally
independent of untrusted forwarding headers. Responses include 409 busy, 410
expired nonce, 429 throttled, and 503 voice profile unavailable.

UX references for the November 2026 update:
[Apple data entry guidance](https://developer.apple.com/design/human-interface-guidelines/entering-data)
supports preserving available input methods;
[Azure continuous recognition documentation](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-recognize-speech?pivots=programming-language-python)
distinguishes segmentation from continuous input and explains the pause/latency
tradeoff. These support the integrated composer and multiple-segment turn design;
the 1.5-second threshold and two-minute cap are project choices to validate on phones.

The visitor composer accepts text without requesting microphone permission.
Send with the button or Enter; Shift+Enter inserts a newline and IME composition
does not send. Drafts remain until the server accepts them, survive a transient
connection loss, and are cleared with the conversation when the session ends.

The visitor app keeps a visible text field with a single trailing action: a
microphone for an empty/whitespace-only draft, Send for text, Finish during
recording, and Stop while transcribing/generating/speaking. Stop takes priority
even if the visitor is drafting the next question; Enter never cancels a reply.
Recording has a separate discard action. A distinct Stop navigation button lives
in the navigation banner. Destination choices open on demand and collapse after
selection; drafting remains possible while a reply is in progress. The action has an
explicit accessible name and a visible label, with a 60px touch height.

The initial question heading and input instructions collapse after the first
accepted `user_text`/`stt_text` (or answer) in the current page session. Typing,
opening the microphone and rejected input do not dismiss them. Once dismissed,
they stay hidden after completion, cancellation, errors and transient reconnects.
Transcription/generation/cancellation feedback appears in a transient answer
bubble at the end of the conversation. Received answers replace that placeholder;
playback status appears inside the current answer. Recording feedback stays by
the composer. Status text is never added to the message history or passed to TTS.
New replies stay above the sticky composer while following the conversation;
scrolling back to earlier messages preserves the reading position. Sending a new
question resumes following. The collapse and activity dots respect reduced-motion
preferences. This follows
[Apple's guidance on contextual help](https://developer.apple.com/design/human-interface-guidelines/offering-help):
show instructions only while they remain useful.

Answers and provenance are separate throughout the pipeline. The model returns
JSON (`answer`, `source_ids`); source IDs resolve only against that turn's
retrieved documents. Titles, editions and pages come from verified retrieval
metadata, never model-written URLs. `LLMQuery.Result.sources_json` carries these
records to the gateway, and `llm_text.sources` displays them in a collapsible
reference area below the speech bubble. Both phone and robot TTS receive only
`response_text`. Invalid structured output uses the localized fallback. Rebuild
`dori_msgs` and its consumers together before restarting the stack.

In Azure mode the phone streams continuously; **a final recognition segment is
not the end of the visitor's turn**. The gateway collects all final segments and
closes input after 1.5 seconds of quiet PCM audio following speech, manual finish,
or the 120-second resource cap. Eight seconds without detected speech produces a
recoverable empty-input error. The browser reports the resource cap explicitly.
The energy detector rejects DC offset and isolated clicks, but is not semantic
turn detection: loud background sound and very quiet speech still require field
testing. These thresholds are initial UX choices, not measured accuracy claims.
AtStart language identification selects Korean or English per turn;
within-sentence mixing remains a known limitation. Three seconds without PCM
frames is a transport failure; silent microphone frames continue flowing.
The gateway allows eight seconds to drain final results after input closes.
STOP, backgrounding and disconnect cancel capture and prevent late text from
starting a reply. The browser limits queued audio and fails visibly on congestion.
The consent screen discloses transmission to Microsoft Azure Speech.

In explicitly selected legacy Whisper mode, the same 1.5-second quiet interval,
eight-second initial silence and 120-second cap apply locally, with 200 ms edge
padding and local silence rejection. The WAV encoder, gateway size limit and
STT decoder all accept the full duration. The idle deadline is 180 seconds to
leave room for capture and upload; heartbeats alone cannot extend it. Local
visitor transcription uses Silero filtering, greedy decoding,
and `visitor_min_confidence=0.4` for short utterances; the robot STT threshold
remains `min_confidence=0.55`. No-speech segments are still rejected. Recognition
failures (`stt_unclear`, `stt_failed`, `stt_timeout`), reply failures and playback
failures have separate messages, and the app returns to READY for retry.

The gateway assigns per-turn request IDs to local STT JSON and uses ROS action UUIDs
for LLM/TTS work; it never adds a ROS session ID. Visitor STT replies use
`stt/visitor_result`, separate from the BT's `stt/result`. `tts/speak_remote`
synthesizes MP3 and waits for `tts/remote_playback` acknowledgment (90-second
limit). It never plays visitor answers on the robot speaker. Wake chimes remain
local. The existing `tts/speak` and legacy `publish_only` behavior are preserved.

TTS selects the voice for each reply: Korean-containing text uses `ko-KR`,
Latin-only text uses `en-US`, and numbers/punctuation use the node's `language`
fallback (default `ko`). This ko/en policy also applies to gTTS and dashboard
browser speech; it does not split mixed-language replies into separate voices.
Cloud TTS uses the matching Neural2, WaveNet or Standard voice and applies
SSML IPA `ˈdɔːri` to `DORI`/`Dori` and `diːˈdʒist` to `DGIST`
(with /dʒ/ and stress on the second syllable). Matching is
case-insensitive and supports Korean particles without changing larger Latin
words or identifiers. In Korean replies only these names switch to an
English voice of the same tier for its English phonemes and stress.
gTTS and browser speech use best-effort `Dory` / `dee jist` (English) and
`도리` / `디지스트` (Korean)
because they do not provide portable IPA control. Displayed conversation text
stays unchanged; audio events add `language` and `speech_text` metadata.
See Google's [SSML reference](https://docs.cloud.google.com/text-to-speech/docs/ssml)
and [supported phonemes](https://docs.cloud.google.com/text-to-speech/docs/phonemes).

GRACE cancels work immediately and retains history for up to 90 seconds.
Reconnection never resumes canceled work. Session expiry is 15 minutes.
ENDING revokes the cookie and waits for actual in-flight action completion;
failed cleanup retries every 5 seconds and cannot be bypassed by an admin.
STT reset drains current transcription and rejects queued audio predating cleanup.
The reset services also prevent a restarted gateway from inheriting old speech
or LLM history. A stuck upstream provider can keep cleanup pending; operators
should diagnose/restart the affected HRI service before admitting another user.

Audio stays in memory at the gateway/STT; synthesis may use a temporary MP3
which TTS removes after completion/cancellation. No uploaded recordings are
persisted. AI transcription/synthesis providers may have separate data handling
policies; the consent screen discloses use of external services. Camera input,
GUIDE and FOLLOW are deferred.

Before a visitor rollout, verify on physical Android Chrome and iPhone Safari:
QR pairing, permissions denied/retried, first-gesture audio playback, the manual
play fallback, long speech beyond 10 seconds and the two-minute recording cutoff, background/lock/foreground, network
switch, STOP during each voice phase, session expiry and a second visitor with
no previous visitor's audio or history. Software tests do not establish physical
stopping behavior or mobile autoplay compatibility.

An optional desktop Chromium smoke test is retained at
`tests/browser/visitor.spec.mjs`. With Playwright and its Chromium runtime installed,
run it from the repository root using `node tests/browser/visitor.spec.mjs`.
Set `DORI_PLAYWRIGHT_MODULE` to a Playwright module path if installed outside the
repository; `DORI_CHROMIUM_EXECUTABLE` can select an already installed Chromium.
The test starts a local static server, mocks the API/WebSocket,
uses a fake microphone, and checks consent, pairing, legacy WAV capture, Azure PCM
streaming beyond ten seconds and through pauses, server endpoint events, stale
IDs, manual finish, recognition-error recovery, playback, scoped stop, end, input action
switching, parallel conversation/navigation, draft preservation, stale reply
suppression, collapsible destinations/references and 320px/390px mobile layouts.
It does not contact the robot or Azure.

The standalone robot display has a separate Chromium check:
`node tests/browser/display.spec.mjs` from the repository root, with the same
`DORI_PLAYWRIGHT_MODULE` override. It mocks all requests and display events,
checks QR expiry/loading races and session transitions, and captures six viewport
sizes under `/tmp/dori-display-*.png`. Set `DORI_DISPLAY_QR_FIXTURE` to a local
SVG QR image for realistic screenshots; the default is a placeholder image.

UX update verification (2026-11-10): frontend audio tests, gateway/LLM/RAG
regressions, mobile Chromium smoke checks, ESLint and the visitor production
bundle passed. The generated action, LLM, HRI, gateway and BT packages built;
an isolated ROS domain-96 integration test verified provenance crossing the real
LLM action and answer-only text reaching synthesis. A follow-up verified
conversation during movement, independent response/navigation cancellation,
arrival during playback, and disconnect cleanup across both actions. These checks use mocked
cloud services and synthetic audio; they do not measure physical phone or live
Azure performance. Restart the stack together to load the rebuilt action type.

Azure app integration verification (2026-11-05): 53 gateway/visitor tests,
9 native-session lifecycle tests, 16 frontend tests, one isolated ROS visitor
integration test (domain 96), ESLint, the visitor bundle
and the `dori_dashboard` overlay build passed. The Chromium smoke test exercised
Azure mode with real browser audio capture and mocked service events, including
continued recording through more than 800 ms of silence and recovery after a
recognition error. The production Azure session also recognized the Korean
paused question and English question using the actual F0 resource. A further
in-memory ASGI WebSocket check streamed both samples through the authenticated
gateway and verified one complete STT text handed to LLM/TTS actions; those
downstream actions were mocked, so it did not call reply-generation APIs.
Local reports are `.state/voice/azure-app-module-live.json` and
`.state/voice/azure-app-websocket-live.json`. These checks did not restart the
public service or validate a physical phone's microphone/network/autoplay.

### Azure Speech F0 evaluation

`tools/voice/evaluate_azure.py` evaluates cloud STT independently of the running
visitor app. It streams 16 kHz mono PCM16 in 100 ms chunks at capture speed,
collects interim and final results, and records language and latency evidence.
It does not select the app's provider or start any ROS nodes.

The standalone evaluator retains its historical **Azure-controlled endpoint
detection** baseline. It does not implement the current app turn endpoint. By default,
`--endpoint-mode azure` keeps sending microphone-equivalent audio until Azure
emits its first final result (or NoMatch), then closes input and drains any
remaining results. There is no client 800 ms silence cutoff in this mode.
The default 5000 ms appended silence is only a bounded test observation window;
reaching the input limit is reported as `azure_endpoint_timeouts`, not successful
Azure endpoint detection. Reports also flag `speech_truncated` if the service
stops input before the labeled end of speech in the source file.

The app integration now collects multiple Azure segments using the turn endpoint
described above. Evaluator results below describe earlier endpoint strategies.
Azure segmentation can still split a speaker's pause; a
service endpoint is not a guarantee that the user has finished their whole turn.

The [Azure pricing page](https://azure.microsoft.com/en-us/pricing/details/speech/)
lists five audio hours of real-time STT per month for Free F0. This allowance is
shared by standard and custom STT; batch transcription is excluded. Create a
**Speech resource with pricing tier F0** in Azure Portal, then copy its key and
region from **Keys and Endpoint** into the local settings file below. A paid S0
resource is not equivalent to an F0 resource with unused free allowance.

The evaluator requires an explicit `AZURE_SPEECH_TIER=F0`, sends one request at a
time, limits each run to 120 audio seconds including appended silence, and stops
on the first service error. It does not create resources or upgrade tiers.
The tier setting is an operator declaration: a Speech API key alone does not
verify the actual Azure pricing tier or remaining monthly allowance. Confirm
F0 in the portal before supplying a key.

Install the optional tools in this checkout's environment:

```bash
/usr/bin/python3 -m venv .venv
.venv/bin/python -m pip install -c constraints-robot.txt -r tools/voice/requirements-azure.txt
mkdir -p .state/voice
```

Store these values in `.state/voice/azure.env` (ignored by Git, mode `0600`):

```dotenv
AZURE_SPEECH_KEY=your-resource-key
AZURE_SPEECH_REGION=your-resource-region
AZURE_SPEECH_TIER=F0
```

The key is read as data, never sourced as a shell script or included in command
arguments, reports or browser code. Environment variables override file values.
`--env-file` selects an existing private settings file. No Azure subscription
or credential is needed for `--dry-run` or offline unit tests.

For the initial smoke test, generate synthetic speech and validate its budget:

```bash
.venv/bin/python tools/voice/prepare_stt_smoke.py
.venv/bin/python tools/voice/evaluate_azure.py \
  --manifest .state/voice/stt-smoke/manifest.json --dry-run
.venv/bin/python tools/voice/evaluate_azure.py \
  --manifest .state/voice/stt-smoke/manifest.json \
  --output .state/voice/azure-first-run.json
```

Sample generation uses gTTS and ffmpeg for fixed public test phrases. It refuses
to overwrite an existing corpus; choose a new `--output-dir` for another set.
The corpus covers a short Korean greeting, Korean and English questions, mixed
speech, a pause within a sentence, silence and low background noise. Synthetic
speech-end labels are energy estimates and are not production latency evidence.

Language identification uses **AtStart**, with `ko-KR` and `en-US` as candidates
for each new utterance. `--languages ko-KR en-US ja-JP zh-CN` changes the candidate
set (up to four distinct base languages). Recognition streams continuously, but
the **Continuous Language Identification** paid add-on is not enabled. AtStart
chooses one language per request, so mixed-language sentences are a deliberate
limitation test. Even continuous language identification does not identify
language changes word by word within one sentence according to
[Microsoft's language identification guide](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-identification).

For representative phone recordings, use a manifest with relative WAV paths:

```json
[
  {
    "id": "phone-ko-short",
    "audio": "phone-ko-short.wav",
    "reference": "안녕",
    "speech_end_seconds": 0.85,
    "expected_languages": ["ko"],
    "source": "phone_human_labeled"
  }
]
```

Evaluator recordings must be 0.5–10 seconds; this historical corpus limit is
independent of the visitor app’s 120-second capture limit. Label the actual end
of speech in the source audio for `speech_end_seconds`; omit it if unknown.
For silence, use an empty reference and omit the speech-end label.

Reports distinguish session startup, first text, final text after speech ends,
PCM pacing lag, character error rate (ignoring case, spaces and punctuation),
language mismatch and silence false positives. A final emitted only after the
input stream is closed is recorded as forced and cannot count as successful
natural endpoint detection. Earlier finals during a sentence are counted
separately, because an app could otherwise cut the user off too early.

`speech_end_to_final_ms` measures natural endpoints only.
`speech_end_to_text_ms` also measures complete results flushed by closing the
input stream; `completion_trigger` distinguishes `natural` from `input_close`.
`input_close_to_text_ms` isolates the wait after close, while
`speech_end_to_input_close_ms` includes the client's silence wait. These are
timing measurements, not accuracy checks: inspect CER and the transcript too.
The SDK's `session_started_ms` is a local recognition-session event, not proof
that the network connection or service is ready.

The following commands reproduce the **historical comparison**, which kept
feeding the full file and tail even after Azure emitted an initial final result:

```bash
.venv/bin/python tools/voice/evaluate_azure.py \
  --manifest .state/voice/stt-smoke/manifest.json --endpoint-mode input-close --tail-ms 5000 --repeats 2 \
  --output .state/voice/azure-baseline-500ms.json
.venv/bin/python tools/voice/evaluate_azure.py \
  --manifest .state/voice/stt-smoke/manifest.json --endpoint-mode input-close --tail-ms 600 --repeats 3 \
  --output .state/voice/azure-client-endpoint-800ms.json
```

The generated speech WAVs already contain 200 ms of trailing silence, so the
600 ms appended tail closes input about 800 ms after their labeled speech end.
This simulated the app's endpoint timing; it did not run the browser's detector.
The 800 ms approach was subsequently rejected in favor of Azure endpointing.
For other recordings, inspect their existing trailing silence before using the
same setting. The 5000 ms tail leaves enough time to observe the service's
at-start language identification and natural finals before forcing EOF.

P50/P95 exclude missing finals and unlabeled speech ends; always inspect their
counts and the sample source. Natural and input-close latency summaries are
separate. `--repeats 2` fits this corpus with the default 5000 ms tail within the
120-second run budget. A 0.5–1.5 second finalization target is a test objective,
not a measured promise. CLI exit code 0 means requests completed, not that
recognition quality passed. Reports and audio remain under ignored `.state`.

Run the offline tests without Azure calls:

```bash
.venv/bin/python -m unittest discover -s tests/control_and_nav -p test_azure_evaluation.py
```

The app integration provides streaming microphone transport, session cancellation,
final-text UI and cloud STT consent. This evaluator does not deploy that switch.
Actual phone accuracy, timing and autoplay still need physical-device validation.

#### Live F0 smoke results — 2026-11-04 UTC

Tested from this ARM64 host against `koreacentral`, SDK 1.53.0, declared F0,
AtStart with `ko-KR` / `en-US`, 100 ms PCM chunks and 500 ms server segmentation.
The seven synthetic samples above were replayed twice with a 5000 ms tail and
three times with a 600 ms tail. All 35 requests completed without service errors.
An earlier one-request diagnostic exposed an evaluator bug reading Python SDK
cancellation fields; the handler now uses `event.cancellation_details.reason`
and `.code`, with EOF/error regression coverage in the 14 offline tests.

The table includes only the four single-language speech samples (three Korean,
one English) per repetition. Latency starts at the synthetic labeled speech end
and includes the client's silence wait. It excludes phone capture/transport,
LLM processing and speech synthesis. Exact matches ignore case, punctuation
and whitespace.

| Measurement | Server endpoint, 2 repetitions | Close input after 800 ms, 3 repetitions |
| --- | ---: | ---: |
| Single-language transcript and language matches | 8/8 | 12/12 |
| Speech-end to complete text, P50 | 3371 ms | 1307 ms |
| Speech-end to complete text, P95 | 4602 ms | 1640 ms |
| Range | 2401–4612 ms | 978–1733 ms |
| Complete text within 1500 ms | 0/8 | 8/12 |
| Silence/noise false positives | 0/4 | 0/6 |
| Mixed-language exact matches | 0/2 | 0/3 |

The mixed sample consistently returned only `도서관에 가려면?`, omitting
`should I turn left?` (normalized CER 0.682). Candidate-language selection
worked for separate Korean/English utterances; within-utterance language mixing
did not. Languages beyond these two candidates remain untested.

All speech results in the 800 ms experiment arrived after EOF. It demonstrated
lower latency when a client already knew the speech-end boundary, but did not
validate detection of pauses or hesitation. The paused Korean sample returned
two finalized segments; forwarding the first would lose the question. Collect
**all** buffered final segments until session completion after closing input.
This configuration did not demonstrate useful interim text while speaking.

The decision at the time was to wait for Azure endpoint detection; the 800 ms client
experiment is retained only as historical evidence. Its results do not meet a
strict P95 <1500 ms target or establish phone accuracy. The
repeated synthetic corpus is too small to establish production percentiles.
Real phone speech, network variation and conversation completion still need
validation. No app provider or running service was changed by this evaluation.

Local evidence (ignored by Git): `.state/voice/azure-baseline-500ms.json`,
`.state/voice/azure-client-endpoint-800ms.json` and
`.state/voice/azure-comparison.json`. The comparison records per-sample results
and WAV hashes. About 168.6 seconds of PCM were sent including the initial
diagnostic; this is not a measurement of Azure billed usage or remaining quota.

#### Azure-controlled endpoint follow-up — 2026-11-05 KST

After the 800 ms client cutoff was rejected, the default evaluator behavior was
changed to stop input on Azure's first final/NoMatch event. A new one-pass run
(`.state/voice/azure-service-endpoint.json`) completed all seven requests without
errors or observation-window timeouts. Five speech samples closed on an Azure
final, and silence/noise closed on NoMatch. All four single-language speech
samples retained the full reference text; the mixed sample still lost English.
Speech-end to complete text for the four single-language samples ranged from
2411 to 4571 ms. The paused sample received its second segment after input was
closed, confirming that buffered results must be drained. None of these short
samples was truncated before its labeled end; this does not establish tolerance
of longer hesitation. Offline endpoint/error tests: 18 passed.

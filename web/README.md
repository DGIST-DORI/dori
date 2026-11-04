# DORI Dashboard Frontend (`web`)

This directory contains the Vite/React frontend for the DORI dashboard.

## Build (Required before first launch)

Build frontend assets before launching the dashboard.

```bash
cd web
npm ci   # or: npm install
npm run build
```

Return to the repository root with `cd ..`, then build ROS and source the
Humble/Python 3.10 environment following [AMM 20-10/20-12](../docs/user/DORI-AMM.md).
The ROS workspace is `ros2_ws`; the installed dashboard must contain this fresh
web build. For package migrations, follow the clean-overlay procedure in AMM 20-15.

## Launch

The development launch below starts desktop HRI and the dashboard map backend,
not physical navigation. The map backend starts automatically with the dashboard
and restarts after an unexpected exit. It listens only on `127.0.0.1:8080`; it
does not open the standalone user port or start hardware/Nav2. Without a running
robot/map source, the panel connects in monitor mode and waits for data.
For hardware + Nav2 + map viewer + HRI, use `dori_bringup hardware.launch.py`
with the device preparation and arguments in AMM 40-10.

Desktop dashboard options:

- Desktop HRI + dashboard (default): `ros2 launch dori_bringup bringup_dev.launch.py`
  - Equivalent explicit form: `ros2 launch dori_bringup bringup_dev.launch.py enable_dashboard:=true`
- Desktop HRI without dashboard: `ros2 launch dori_bringup bringup_dev.launch.py enable_dashboard:=false`
- Dashboard only (standalone): `ros2 launch dori_dashboard dashboard.launch.py`

```bash
# Desktop HRI + dashboard (default)
ros2 launch dori_bringup bringup_dev.launch.py

# Desktop HRI + dashboard (explicit)
ros2 launch dori_bringup bringup_dev.launch.py enable_dashboard:=true

# Desktop HRI without dashboard
ros2 launch dori_bringup bringup_dev.launch.py enable_dashboard:=false
```

If you need to run the dashboard standalone (without the desktop HRI stack):

```bash
ros2 launch dori_dashboard dashboard.launch.py
```

If a separately managed viewer already owns port 8080, launch the dashboard with
`enable_navigation_viewer:=false`. The integrated `hardware.launch.py` sets this
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

`DORI_CONTROL_EXECUTOR=dry-run` remains the default. Live control requires
`DORI_CONTROL_EXECUTOR=bridge` in **both** backend and bridge environments.
The removed `ros2_cli` executor is rejected instead of silently publishing.

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
- Both user WS `STOP` and API `stop` publish `/emergency_stop` plus `/dori/hri/cancel`.
  The supervisor prevents subsequent manual/auto commands from overriding this
  latch. A local operator must explicitly resume using the existing emergency-go
  procedure; the web API does not automatically clear a stop.
- `set_mode` supports only `manual` (Int32 0) and `auto` (Int32 1), published to
  `/control_mode_cmd`. `dock`, `idle`, and `safe` are not supervisor control modes.
- Pairing/LLM/BT traffic uses the actual `/dori` namespace. Low-level hardware
  input topics retain their existing absolute names.

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

The mobile visitor app is separate from the developer dashboard. Build it with
`npm run build:visitor`; `npm run test:visitor` tests its PCM/WAV encoder.
`dist-visitor` installs into `share/dori_dashboard/visitor_web` when rebuilding
`dori_dashboard`. The regular dashboard build and authentication are unchanged.
The existing `control` role and the `operator` alias both permit operator actions.

Use the visitor profile for the first release. It deliberately disables BT
wake-triggered following, local STT intents, gestures and automatic patrols;
visitor utterances cannot dispatch navigation. For a desktop session:

```bash
# One-time network/model preparation (phone input needs no wake-word model).
scripts/prepare_voice.sh --topic-only
# Stop any existing bringup_dev session first, then:
scripts/start_visitor.sh
```

`start_visitor.sh` selects `visitor_mode:=true`, `stt_audio_input_mode:=topic`
and the prepared `.state/voice/whisper-small` model. The development launch keeps
its original defaults (visitor mode off, robot microphone input); simply enabling
the dashboard does not select the visitor profile.

The normal dashboard authentication variables, a random `DORI_INTERNAL_TOKEN`
and prepared Whisper models remain required. To use the real hardware profile,
pass `visitor_mode:=true stt_audio_input_mode:=topic` to `hardware.launch.py`
alongside its required map and hardware settings. Do not start duplicate HRI
nodes. Pairing returns 503 unless `bt/visitor_ready` confirms the voice-only
profile and STT, BT, LLM and TTS cleanup succeeds. Starting the dashboard alone does
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

- `heartbeat` every 5 seconds; it does not extend the 120-second idle deadline.
- `ptt_audio` with `audio_b64`, `format: "wav_pcm16"`, `sample_rate: 16000`,
  `channels: 1`; 0.5–10 seconds, one outstanding turn, 450,000-byte WS limit.
- `text` with `text`: a nonblank string of at most 1,000 characters. The gateway
  trims surrounding whitespace, echoes accepted input as `user_text`, skips STT,
  and uses the same LLM and remote TTS actions as microphone input. Audio and text
  share one outstanding turn, cancellation, idle activity and cleanup rules.
- `command` with `action: "STOP"` cancels the current task without clearing an
  operator emergency stop. Unsupported commands, including GUIDE/FOLLOW, fail.
- `playback` with the issued audio `id` and `status: "ended" | "failed" | "canceled"`.
- `end` closes and cleans up the session; `DELETE /api/session` is also available.

Outputs are `robot_state` (READY/TRANSCRIBING/THINKING/SPEAKING), `stt_text`, `user_text`,
`llm_text`, `tts_audio` (id and authenticated URL), `command_result`, and `error`.
`GET /api/session` permits page reload recovery. MP3 URLs are unpredictable,
require the active cookie, have no-store caching, and expire after playback or
cancellation. Pairing uses a global limit of 30 attempts/minute, intentionally
independent of untrusted forwarding headers. Responses include 409 busy, 410
expired nonce, 429 throttled, and 503 voice profile unavailable.

The visitor composer accepts text without requesting microphone permission.
Send with the button or Enter; Shift+Enter inserts a newline and IME composition
does not send. Drafts remain until the server accepts them, survive a transient
connection loss, and are cleared with the conversation when the session ends.

The gateway assigns per-turn request IDs to STT JSON and uses ROS action UUIDs
for LLM/TTS work; it never adds a ROS session ID. Visitor STT replies use
`stt/visitor_result`, separate from the BT's `stt/result`. `tts/speak_remote`
synthesizes MP3 and waits for `tts/remote_playback` acknowledgment (90-second
limit). It never plays visitor answers on the robot speaker. Wake chimes remain
local. The existing `tts/speak` and legacy `publish_only` behavior are preserved.

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
play fallback, 10-second recording cutoff, background/lock/foreground, network
switch, STOP during each voice phase, session expiry and a second visitor with
no previous visitor's audio or history. Software tests do not establish physical
stopping behavior or mobile autoplay compatibility.

An optional desktop Chromium smoke test is retained at
`tests/browser/visitor.spec.mjs`. With Playwright and its Chromium runtime installed,
run it from the repository root using `node tests/browser/visitor.spec.mjs`.
Set `DORI_PLAYWRIGHT_MODULE` to a Playwright module path if installed outside the
repository. The test starts a local static server, mocks the API/WebSocket,
uses a fake microphone, and checks consent, pairing, WAV capture, playback
acknowledgment, STOP, end and mobile-width layout. It does not contact the robot.

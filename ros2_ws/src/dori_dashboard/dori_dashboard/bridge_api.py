#!/usr/bin/env python3
"""
DORI WebSocket Gateway & Session Manager (bridge_api.py)
사용자 앱 서빙, QR 페어링, 세션 관리 및 제한된 ROS 프로토콜 게이트웨이를 담당합니다.
"""

from contextlib import asynccontextmanager, contextmanager
import asyncio
import json
import logging
import os
import secrets
import signal
import threading
import time
from urllib.parse import urlsplit
from pathlib import Path
from collections import deque
from io import BytesIO
from enum import Enum
from typing import Dict, Optional, Set

import rclpy
from rclpy.node import Node
from rclpy.signals import SignalHandlerOptions
from rclpy.qos import QoSProfile, DurabilityPolicy
from std_msgs.msg import Bool, String, Int32
from std_srvs.srv import Trigger
from geometry_msgs.msg import Twist

import uvicorn
from fastapi import (
    Header,
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    Request,
    Response,
    Cookie,
)
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    from .visitor_voice import VisitorVoice, ros_future
    from .control_contract import CONTROL_MODES, MOVE_TIMEOUT, validate_control
    from .internal_auth import internal_token, require_internal_token
    from .hardware_control import HardwareControlMixin
except ImportError:  # installed scripts are also executable directly
    from visitor_voice import VisitorVoice, ros_future
    from control_contract import CONTROL_MODES, MOVE_TIMEOUT, validate_control
    from internal_auth import internal_token, require_internal_token
    from hardware_control import HardwareControlMixin

# ─── Configuration ─────────────────────────────────────────────────────────

PUBLIC_PORT = 3100
DISPLAY_PORT = 3001
NONCE_TTL = 30  # QR 갱신 주기 (초)
NONCE_GRACE = 5  # 스캔 지연 오차 허용 (초)
GRACE_TIMEOUT = 90  # WS 끊김 후 재연결 유예 시간 (초)
PAIR_CLAIM_TTL = 120  # Time to review consent after scanning a live QR.
SESSION_MAX_TIME = 900  # 최대 세션 시간 (15분)
MAX_WS_MSG_SIZE = 450000

_DEV_MODE = os.environ.get("DORI_DEV_MODE", "").strip().lower() in ("1", "true", "yes")
PUBLIC_HOST = "0.0.0.0" if _DEV_MODE else "127.0.0.1"

APP_ORIGIN = os.environ.get("DORI_VISITOR_ORIGIN", "https://app.dgist-dori.xyz").rstrip("/")
_origin = urlsplit(APP_ORIGIN)
if _origin.scheme != "https" or not _origin.netloc or _origin.path or _origin.query or _origin.fragment or _origin.username:
    raise RuntimeError("DORI_VISITOR_ORIGIN must be an HTTPS origin")
ALLOWED_ORIGINS = [APP_ORIGIN]
if _DEV_MODE:
    ALLOWED_ORIGINS.append("http://localhost:3100")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bridge_api")

# ─── Data Models & States ──────────────────────────────────────────────────


class SessionState(Enum):
    IDLE = "IDLE"
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    ENDING = "ENDING"


class PairClaimRequest(BaseModel):
    nonce: str = Field(min_length=1, max_length=64)


class PairRequest(BaseModel):
    nonce: Optional[str] = Field(default=None, min_length=1, max_length=64)
    consent: bool


ros_node: Optional["BridgeNode"] = None

# ─── ROS 2 Node (Bridge Gateway) ───────────────────────────────────────────


class BridgeNode(HardwareControlMixin, Node):
    def __init__(self):
        super().__init__("bridge_api_node")
        # 하향(ROS -> WS) Subscriptions
        self.voice = VisitorVoice(self, session_manager)

        # 상향(WS -> ROS) & 제어용 Publishers
        self.pub_wake = self.create_publisher(Bool, "stt/wake_word_detected", 10)
        self.pub_chime = self.create_publisher(String, "hri/audio_cue", 10)
        self.pub_manual = self.create_publisher(Twist, "manual/cmd_vel", 10)
        self.pub_stop = self.create_publisher(Bool, "emergency_stop", 10)
        self.pub_mode = self.create_publisher(Int32, "control_mode_cmd", 10)
        self._control_lock = threading.RLock()
        self._move_deadline = 0.0
        self._move_command = None
        self._mode = None
        self._action_state = None
        self._init_hardware_control()
        latch = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(Int32, "system/control_mode", self._on_mode, latch)
        self.create_subscription(Int32, "system/action_state", self._on_state, latch)
        self.create_timer(0.05, self._control_tick)
        self.pub_cancel = self.create_publisher(Bool, "hri/cancel", 10)

        self.pub_nav_idle = self.create_publisher(Int32, "NAVIGATION_MODE", 10)
        self.cli_visitor_ready = self.create_client(Trigger, "bt/visitor_ready")
        self.cli_stt_reset = self.create_client(Trigger, "stt/reset")
        self.cli_tts_reset = self.create_client(Trigger, "tts/remote_reset")
        self.cli_llm_reset = self.create_client(Trigger, "llm/reset")
        self.cli_bt_clear = self.create_client(Trigger, "bt/clear_session")
        self.destinations = self._load_saved_destinations()
        self.create_subscription(String, "nav/locations", self._on_locations, latch)

    def _load_saved_destinations(self):
        candidates = [
            Path(os.environ.get("DORI_SESSION_ROOT", ".")) / "maps/web_goals.json",
            Path(os.environ.get("DORI_SESSION_ROOT", ".")) / "maps/web_goals.example.json",
            Path(__file__).parents[4] / "maps/web_goals.json",
            Path(__file__).parents[4] / "maps/web_goals.example.json",
        ]
        for candidate in candidates:
            try:
                if candidate.is_file():
                    data = json.loads(candidate.read_text())
                    goals = []
                    for map_goals in data.get("maps", {}).values():
                        if isinstance(map_goals, list):
                            goals.extend(map_goals)
                    if goals:
                        return [{"id": g["id"], "name": g["name"]} for g in goals]
            except Exception:
                pass
        return []

    def _on_locations(self, msg):
        try:
            data = json.loads(msg.data)
            goals = data.get("goals", [])
            if goals:
                self.destinations = [{"id": g["id"], "name": g["name"]} for g in goals]
                if session_manager.active_ws:
                    loop = session_manager.main_loop
                    if loop and not loop.is_closed():
                        loop.call_soon_threadsafe(
                            lambda: asyncio.create_task(
                                session_manager.active_ws.send_json(
                                    {"type": "destinations", "destinations": self.destinations}
                                )
                            )
                        )
        except Exception:
            pass

    def _on_mode(self, msg):
        with self._control_lock:
            self._mode = msg.data
            if self._move_command is not None and msg.data != CONTROL_MODES["manual"]:
                self.request_stop()

    def _on_state(self, msg):
        with self._control_lock:
            self._action_state = msg.data
            if self._move_command is not None and msg.data not in (0, 1):
                self.request_stop()

    def request_stop(self):
        """Latch the supervisor's highest-priority stop; only an operator resumes."""
        with self._control_lock:
            self._move_command = None
            self._move_deadline = 0.0
            self._move_owner = None
            self._action_state = 4
            self._stop_latched = True
            self._control_epoch = secrets.token_hex(16)
            self.pub_stop.publish(Bool(data=True))
            self.pub_cancel.publish(Bool(data=True))

    def control_action(self, action, params):
        with self._control_lock:
            if (action != "stop" and "control_epoch" in params
                    and params["control_epoch"] != self._control_epoch):
                raise HTTPException(409, "Control state changed; refresh before commanding motion")
            if action == "stop":
                self.request_stop()
            elif action == "set_mode":
                if self._move_command is not None:
                    self.request_stop()
                self.pub_mode.publish(Int32(data=CONTROL_MODES[params["mode"]]))
            elif action == "move":
                owner = params.get("client_id", "legacy")
                if self._move_command is not None and self._move_owner != owner:
                    raise HTTPException(409, "Another dashboard is driving; stop before taking control")
                if (self._stop_latched or self._mode != CONTROL_MODES["manual"]
                        or self._action_state not in (0, 1)):
                    raise HTTPException(409, "Manual mode and idle/drive supervisor state required")
                if not self.pub_manual.get_subscription_count() or not self.pub_stop.get_subscription_count():
                    raise HTTPException(503, "Supervisor is unavailable")
                if self.count_publishers("/manual/cmd_vel") > 1:
                    raise HTTPException(409, "Another manual input publisher is active")
                cmd = Twist()
                cmd.linear.x = params["linear_x"]
                cmd.angular.z = params["angular_z"]
                self._move_command = cmd
                self._move_owner = owner
                self._move_deadline = time.monotonic() + MOVE_TIMEOUT
                self.pub_manual.publish(cmd)
            elif action in ("resume", "transform"):
                self.hardware_action(action, params)

    def _control_tick(self):
        # Runs on the ROS thread, independently of HTTP/WS event-loop load.
        # The downstream drive controller also expires commands after 0.3s
        # if this entire process crashes.
        with self._control_lock:
            if self._move_command is None:
                return
            if (time.monotonic() >= self._move_deadline
                    or self.count_publishers("/manual/cmd_vel") > 1
                    or not self.pub_manual.get_subscription_count()):
                self.request_stop()
                return
            self.pub_manual.publish(self._move_command)

    def cancel_visitor(self):
        self.voice.cancel()
        self.pub_cancel.publish(Bool(data=True))
        # IDLE does not clear the supervisor's latched emergency stop.
        self.pub_nav_idle.publish(Int32(data=0))

    async def prepare_visitor(self):
        if not self.cli_visitor_ready.service_is_ready():
            return False
        try:
            response = await asyncio.wait_for(ros_future(self.cli_visitor_ready.call_async(Trigger.Request())), 3)
            return response.success and await self.execute_cleanup()
        except Exception:
            return False

    def trigger_pairing_success(self):
        """페어링 성공 시 웨이크워드 감지 및 차임벨 발생"""
        self.pub_wake.publish(Bool(data=True))
        self.pub_chime.publish(String(data="wake_chime"))
        logger.info("[ROS] Pairing success triggered to HRI")

    async def execute_cleanup(self, timeout_sec: float = 5.0) -> bool:
        """Cancel visitor work and wait for LLM, BT and TTS cleanup barriers."""
        self.cancel_visitor()
        if self.voice.draining:
            return False

        async def call_ros_service(cli, name):
            if not cli.service_is_ready():
                logger.warning(f"Cleanup: {name} service not immediately available")
                return False

            loop = asyncio.get_running_loop()
            async_future = loop.create_future()
            ros_future = cli.call_async(Trigger.Request())

            def on_done(f):
                loop.call_soon_threadsafe(
                    lambda: (
                        async_future.set_result(f.result())
                        if not async_future.done()
                        else None
                    )
                )

            ros_future.add_done_callback(on_done)

            try:
                res = await asyncio.wait_for(async_future, timeout=timeout_sec)
                if not res.success:
                    logger.warning(f"Cleanup: {name} failed - {res.message}")
                    return False
                return True
            except asyncio.TimeoutError:
                logger.error(f"Cleanup: {name} service timed out")
                return False
            except Exception as e:
                logger.error(f"Cleanup: {name} error - {e}")
                return False

        # Reset LLM, BT and TTS; busy services fail closed and are retried.
        resets = [
            call_ros_service(self.cli_llm_reset, "LLM"),
            call_ros_service(self.cli_bt_clear, "BT"),
            call_ros_service(self.cli_tts_reset, "TTS"),
        ]
        if getattr(self.voice, 'provider', 'whisper') != 'azure':
            resets.append(call_ros_service(self.cli_stt_reset, "STT"))
        results = await asyncio.gather(*resets)

        logger.info("[ROS] Session cleanup completed")
        # Never admit a new visitor before every cleanup barrier succeeds.
        return all(results)


# ─── Core Logic: Nonce & Session Management ────────────────────────────────


class NonceManager:
    def __init__(self):
        self.nonces: Dict[str, float] = {}
        self.current = None
        self.generated_at = 0

    def generate(self) -> str:
        self._cleanup()
        if self.current in self.nonces and time.time() - self.generated_at < NONCE_TTL:
            return self.current
        nonce = secrets.token_urlsafe(16)
        self.current = nonce
        self.generated_at = time.time()
        # 생성 시간 + TTL + 지연 허용 시간
        self.nonces[nonce] = time.time() + NONCE_TTL + NONCE_GRACE
        return nonce

    def is_valid(self, nonce: str) -> bool:
        self._cleanup()
        return nonce in self.nonces and self.nonces[nonce] > time.time()

    def validate_and_consume(self, nonce: str) -> bool:
        if self.is_valid(nonce):
            del self.nonces[nonce]  # 1회용 소모
            return True
        return False

    def _cleanup(self):
        now = time.time()
        self.nonces = {k: v for k, v in self.nonces.items() if v > now}


class PairClaimManager:
    """Short-lived, browser-bound scan proofs; no robot session or consent yet."""
    def __init__(self):
        self.claims: Dict[str, tuple[str, float]] = {}

    def expires_at(self, token):
        now = time.time()
        self.claims = {key: claim for key, claim in self.claims.items() if claim[1] > now}
        claim = self.claims.get(token) if isinstance(token, str) else None
        return claim[1] if claim else None

    def issue(self, nonce, existing=None):
        expiry = self.expires_at(existing)
        if expiry and self.claims[existing][0] == nonce:
            return existing, expiry  # Retrying the same scan must not extend it.
        if isinstance(existing, str):
            self.claims.pop(existing, None)
        if len(self.claims) >= 128:
            raise HTTPException(429, "Too many pending scans")
        token = secrets.token_urlsafe(32)
        expiry = time.time() + PAIR_CLAIM_TTL
        self.claims[token] = (nonce, expiry)
        return token, expiry


class SessionManager:
    def __init__(self):
        self.state = SessionState.IDLE
        self.current_token: Optional[str] = None
        self.session_expires_at: float = 0
        self.active_ws: Optional[WebSocket] = None
        self.display_queues: Set[asyncio.Queue] = set()
        self.main_loop: Optional[asyncio.AbstractEventLoop] = None
        self.grace_task: Optional[asyncio.Task] = None
        self.last_activity = 0.0
        self._ending_lock = asyncio.Lock()
        self._pairing_lock = asyncio.Lock()
        self.session_timer_task: Optional[asyncio.Task] = None
        self.idle_task: Optional[asyncio.Task] = None
        self.cleanup_task = None
        self.idle_timeout = 120.0  # 2분 무조작 시 강제 종료

    async def _cancel_session_timers(self):
        # watcher가 직접 종료를 요청한 경우 자기 자신은 취소하지 않는다.
        current = asyncio.current_task()
        tasks = [
            task
            for task in (self.grace_task, self.session_timer_task, self.idle_task)
            if task is not None and task is not current
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.grace_task = self.session_timer_task = self.idle_task = None

    async def broadcast_display(self, event_type: str, data: dict):
        payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        for q in list(self.display_queues):
            try:
                q.put_nowait(payload)
            except Exception:
                self.display_queues.discard(q)

    async def start_session(self):
        await self._cancel_session_timers()
        nonce_manager.nonces.clear()
        pair_claim_manager.claims.clear()
        self.state = SessionState.ACTIVE
        self.current_token = secrets.token_hex(32)
        self.session_expires_at = time.time() + SESSION_MAX_TIME
        self.last_activity = time.monotonic()

        self.session_timer_task = asyncio.create_task(self._max_time_watcher())
        self.idle_task = asyncio.create_task(self._idle_watcher())
        await self.broadcast_display("paired", {"status": "ACTIVE"})
        ros_node.trigger_pairing_success()
        logger.info("Session ACTIVE")
        return self.current_token

    async def handle_disconnect(self):
        if self.state == SessionState.ACTIVE:
            ros_node.cancel_visitor()
            self.state = SessionState.GRACE
            self.active_ws = None
            await self.broadcast_display("state", {"status": "GRACE"})
            logger.warning("Session GRACE started")
            self.grace_task = asyncio.create_task(self._grace_timeout())

    async def _grace_timeout(self):
        await asyncio.sleep(GRACE_TIMEOUT)
        if self.state == SessionState.GRACE:
            logger.info("Grace period timeout")
            await self.end_session()

    async def _max_time_watcher(self):
        await asyncio.sleep(SESSION_MAX_TIME)
        logger.info("Session Max Time reached. Forcing end.")
        await self.end_session()

    async def _idle_watcher(self):
        while self.state in (SessionState.ACTIVE, SessionState.GRACE):
            # GRACE 중에는 기존 재연결 유예 시간을 보장한다.
            if self.state == SessionState.ACTIVE:
                remaining = self.idle_timeout - (time.monotonic() - self.last_activity)
                if remaining <= 0:
                    logger.info("User idle timeout reached.")
                    await self.end_session()
                    return
                await asyncio.sleep(min(remaining, 1.0))
            else:
                await asyncio.sleep(1.0)

    async def _retry_cleanup_loop(self):
        logger.info("Starting background cleanup retry task (5s interval)...")
        while self.state == SessionState.ENDING:
            await asyncio.sleep(5.0)
            logger.info("Retrying session cleanup in background...")
            if await ros_node.execute_cleanup():
                self.state = SessionState.IDLE
                await self.broadcast_display("state", {"status": "IDLE"})
                logger.info("Background cleanup succeeded.")
                break

    async def end_session(self, admin_force=False):
        async with self._ending_lock:  # 재진입 동시 실행 완벽 차단
            if self.state == SessionState.IDLE:
                return True

            if self.state == SessionState.ENDING and self.cleanup_task and not self.cleanup_task.done():
                return False
            self.state = SessionState.ENDING
            ros_node.cancel_visitor()
            await self.broadcast_display("state", {"status": "ENDING"})
            self.current_token = None
            await self._cancel_session_timers()
            if self.active_ws:
                try:
                    await self.active_ws.close(code=1000)
                except Exception:
                    pass
                self.active_ws = None

            # Exponential Backoff 적용된 정리 로직
            for attempt in range(3):
                if await ros_node.execute_cleanup():
                    self.state = SessionState.IDLE
                    await self.broadcast_display("state", {"status": "IDLE"})
                    return True
                logger.warning(f"Cleanup failed, retrying in {2**attempt}s...")
                await asyncio.sleep(2**attempt)

            logger.error(
                "Critical: Cleanup failed completely. Starting background retry task."
            )
            await self.broadcast_display("state", {"status": "ENDING"})

            self.cleanup_task = asyncio.create_task(self._retry_cleanup_loop())
            return False


nonce_manager = NonceManager()
pair_claim_manager = PairClaimManager()
session_manager = SessionManager()


@asynccontextmanager
async def public_lifespan(app: FastAPI):
    global ros_node

    internal_token()  # Refuse direct/uvicorn startup with missing IPC credentials.

    # 1. 앱 시작 시 ROS 2 노드 초기화 및 스핀 스레드 구동
    if not rclpy.ok():
        # Uvicorn owns process shutdown; ROS must not replace its handlers.
        rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    ros_node = BridgeNode()
    ros_thread = threading.Thread(target=lambda: rclpy.spin(ros_node), daemon=True)
    ros_thread.start()

    # 2. 메인 이벤트 루프 확보
    session_manager.main_loop = asyncio.get_running_loop()
    yield

    # 3. 앱 종료 시 ROS 2 안전하게 정리
    if ros_node:
        ros_node.cancel_visitor()
        await session_manager._cancel_session_timers()
        if session_manager.cleanup_task:
            session_manager.cleanup_task.cancel()
        if ros_node._move_command is not None:
            ros_node.request_stop()
        ros_node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()


# ─── FastAPI 1: Public App (Port 3100) ─────────────────────────────────────

app_public = FastAPI(title="DORI App Gateway", lifespan=public_lifespan)

app_public.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


pair_attempts = deque()


@app_public.middleware("http")
async def public_boundary(request: Request, call_next):
    if request.url.path in ("/api/pair", "/api/pair/claim", "/api/session") and request.method in ("POST", "DELETE") and request.headers.get("origin") not in ALLOWED_ORIGINS:
        return Response(status_code=403)
    if request.method == "POST" and request.url.path in ("/api/pair", "/api/pair/claim"):
        now = time.monotonic()
        while pair_attempts and pair_attempts[0] <= now - 60:
            pair_attempts.popleft()
        if len(pair_attempts) >= 30:
            return Response(status_code=429, headers={"Retry-After": "60"})
        pair_attempts.append(now)
        body = bytearray()
        async def read_body():
            async for chunk in request.stream():
                if len(body) + len(chunk) > 1024:
                    return False
                body.extend(chunk)
            return True
        try:
            if not await asyncio.wait_for(read_body(), 5):
                return Response(status_code=413)
        except asyncio.TimeoutError:
            return Response(status_code=408)
        request._body = bytes(body)
        original_receive = request._receive
        replayed = False
        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await original_receive()
        request._receive = replay
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(self)"
    return response


def require_session(token):
    if not token or not session_manager.current_token or not secrets.compare_digest(token.encode(), session_manager.current_token.encode()):
        raise HTTPException(401, "Session expired")


@app_public.get("/api/session")
async def session_status(dori_session: Optional[str] = Cookie(None)):
    require_session(dori_session)
    return {"state": session_manager.state.value, "expires_at": session_manager.session_expires_at}


@app_public.get("/api/destinations")
async def get_destinations(dori_session: Optional[str] = Cookie(None)):
    require_session(dori_session)
    return {"destinations": getattr(ros_node, "destinations", []) if ros_node else []}


@app_public.get("/api/audio/{audio_key}")
async def session_audio(audio_key: str, dori_session: Optional[str] = Cookie(None)):
    require_session(dori_session)
    audio = ros_node.voice.media.get(audio_key) if ros_node else None
    if not audio:
        raise HTTPException(404, "Audio expired")
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


def claim_info(expiry):
    return {"expires_at": expiry, "expires_in": max(0, expiry - time.time())}


@app_public.post("/api/pair/claim")
async def claim_pairing(req: PairClaimRequest, response: Response,
                        dori_pair_claim: Optional[str] = Cookie(None)):
    async with session_manager._pairing_lock:
        if session_manager.state != SessionState.IDLE:
            raise HTTPException(409, "Robot is currently in use or cleaning up")
        if not nonce_manager.is_valid(req.nonce):
            raise HTTPException(410, "Invalid or expired nonce")
        token, expiry = pair_claim_manager.issue(req.nonce, dori_pair_claim)
    response.set_cookie("dori_pair_claim", token, httponly=True, secure=True,
                        samesite="strict", max_age=max(1, int(expiry - time.time())))
    return claim_info(expiry)


@app_public.get("/api/pair/claim")
async def pairing_claim_status(dori_pair_claim: Optional[str] = Cookie(None)):
    expiry = pair_claim_manager.expires_at(dori_pair_claim)
    if not expiry:
        raise HTTPException(410, "Scan confirmation expired")
    return claim_info(expiry)


@app_public.post("/api/pair")
async def pair_device(req: PairRequest, response: Response,
                      dori_pair_claim: Optional[str] = Cookie(None)):
    if not req.consent:
        raise HTTPException(status_code=400, detail="Consent required")

    async with session_manager._pairing_lock:
        if session_manager.state != SessionState.IDLE:
            raise HTTPException(
                status_code=409,
                detail="Robot is currently in use or cleaning up",
            )

        # Validate before readiness checks, but consume only on success. A 503
        # must not turn a retry into a misleading 410. Accept legacy direct QR
        # requests as well as the browser-bound scan proof from the consent page.
        if not (pair_claim_manager.expires_at(dori_pair_claim) or nonce_manager.is_valid(req.nonce)):
            raise HTTPException(status_code=410, detail="Invalid or expired nonce")

        if not await ros_node.prepare_visitor():
            raise HTTPException(503, "Visitor voice profile unavailable or still draining")
        token = await session_manager.start_session()

    response.delete_cookie("dori_pair_claim", secure=True, httponly=True, samesite="strict")
    response.set_cookie(
        key="dori_session",
        value=token,
        httponly=True,
        secure=True,  # HTTPS is required, including phone demos.
        samesite="strict",
        max_age=SESSION_MAX_TIME,
    )
    return {"expires_at": session_manager.session_expires_at}


@app_public.delete("/api/session")
async def delete_session(
    dori_session: Optional[str] = Cookie(None),
):
    if (
        dori_session
        and session_manager.current_token
        and secrets.compare_digest(dori_session.encode(), session_manager.current_token.encode())
    ):
        ok = await session_manager.end_session()
        if not ok:
            raise HTTPException(
                status_code=503,
                detail="Session cleanup failed",
            )
    response = Response(content='{"status":"ok"}', media_type="application/json")
    response.delete_cookie("dori_session", secure=True, httponly=True, samesite="strict")
    return response


# ─── Internal IPC Endpoints (Called by backend_api.py) ─────────────────────


@app_public.websocket("/ws/user")
async def websocket_user(websocket: WebSocket):
    # 1. Origin 검증 (Cross-site WS Hijacking 방지)
    origin = websocket.headers.get("origin")
    if origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return

    # 2. 쿠키 기반 세션 토큰 검증
    cookie_token = websocket.cookies.get("dori_session")
    if (
        not cookie_token
        or not session_manager.current_token
        or not secrets.compare_digest(cookie_token.encode(), session_manager.current_token.encode())
    ):
        await websocket.close(code=1008)
        return

    if session_manager.state not in (SessionState.ACTIVE, SessionState.GRACE):
        await websocket.close(code=1008)
        return
    await websocket.accept()

    if session_manager.active_ws and session_manager.active_ws is not websocket:
        try:
            await session_manager.active_ws.close(code=4000, reason="Replaced")
        except Exception:
            pass

    # Replacing a tab cancels its playback and outstanding work.
    if session_manager.active_ws:
        ros_node.cancel_visitor()
    session_manager.active_ws = websocket
    session_manager.last_activity = time.monotonic()

    if session_manager.state == SessionState.GRACE:
        session_manager.state = SessionState.ACTIVE
        if session_manager.grace_task:
            session_manager.grace_task.cancel()
        await session_manager.broadcast_display("state", {"status": "ACTIVE"})
        logger.info("Session Resumed from GRACE")

    await websocket.send_json({"type": "robot_state", "status": "READY",
                               "stt_provider": getattr(ros_node.voice, 'provider', 'whisper')})
    await websocket.send_json({
        "type": "robot_state",
        "status": "READY",
        "stt_provider": getattr(ros_node.voice, 'provider', 'whisper') if ros_node else 'whisper',
        "destinations": getattr(ros_node, 'destinations', []) if ros_node else [],
    })
    try:
        while True:
            # 연결 생존 확인은 사용자 활동과 별개다. ASGI에는 프로토콜 ping이
            # 전달되지 않으므로 클라이언트는 애플리케이션 heartbeat를 보낸다.
            message = await asyncio.wait_for(websocket.receive(), timeout=15.0)
            if message["type"] == "websocket.disconnect":
                raise WebSocketDisconnect(code=message.get("code", 1000))
            if (
                websocket is not session_manager.active_ws
                or session_manager.state != SessionState.ACTIVE
            ):
                break

            data = message.get("text")
            binary = message.get("bytes")
            size = len(data.encode("utf-8")) if data is not None else len(binary or b"")
            if size > MAX_WS_MSG_SIZE:
                logger.warning("WS message exceeds size limit, dropping")
                continue

            if binary is not None:
                # 3단계 오디오/카메라 프로토콜 구현 지점. 현재는 연결을 유지하고
                # 미지원 바이너리를 무시하며, 사용자 활동으로 집계하지 않는다.
                logger.debug("Unsupported binary WS message, dropping")
                continue
            if data is None:
                continue

            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON format in WS, dropping")
                continue  # 세션을 끊지 않고 해당 메시지만 무시

            if not isinstance(payload, dict):
                logger.warning("WS JSON payload must be an object, dropping")
                continue

            cmd_type = payload.get("type")
            if cmd_type == "command" and payload.get("action") == "STOP":
                ros_node.cancel_visitor()
                session_manager.last_activity = time.monotonic()
                await websocket.send_json({"type": "command_result", "action": "STOP", "ok": True})
                await websocket.send_json({"type": "robot_state", "status": "READY"})
            elif cmd_type == "ptt_audio":
                try:
                    ros_node.voice.start(payload)
                    session_manager.last_activity = time.monotonic()
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "code": "audio_rejected", "message": str(exc)})
            elif cmd_type == "stt_start":
                try:
                    ros_node.voice.start_stream(payload)
                    session_manager.last_activity = time.monotonic()
                except ValueError as exc:
                    await websocket.send_json({"type": "stt_closed", "id": payload.get('id'), "reason": "rejected"})
                    await websocket.send_json({"type": "error", "code": "audio_rejected", "message": str(exc)})
            elif cmd_type == "stt_chunk":
                ros_node.voice.stream_audio(payload)
            elif cmd_type == "stt_end":
                ros_node.voice.finish_stream(payload)
            elif cmd_type == "stt_cancel":
                ros_node.voice.cancel_stream(payload)
            elif cmd_type == "text":
                try:
                    ros_node.voice.start_text(payload)
                    session_manager.last_activity = time.monotonic()
                except ValueError as exc:
                    await websocket.send_json({"type": "error", "code": "text_rejected", "message": str(exc)})
            elif cmd_type == "playback":
                ros_node.voice.playback(payload)
            elif cmd_type == "end":
                await session_manager.end_session()
                break
            elif cmd_type != "heartbeat":
                await websocket.send_json({"type": "error", "code": "unsupported_message", "message": "지원하지 않는 요청입니다."})

    except asyncio.TimeoutError:
        logger.warning("WS Heartbeat timeout. Network likely dropped.")
        if websocket is session_manager.active_ws:
            await session_manager.handle_disconnect()
    except WebSocketDisconnect:
        if websocket is session_manager.active_ws:
            await session_manager.handle_disconnect()
    except Exception as e:
        logger.error(f"WS Error: {e}")
        if websocket is session_manager.active_ws:
            await session_manager.handle_disconnect()


# ─── FastAPI 2: Display Listener (Port 3001, 127.0.0.1 Only) ─────────────────

app_display = FastAPI(title="DORI Display API")


async def display_event_generator(q: asyncio.Queue):
    try:
        # 최초 연결 시 현재 상태 즉시 전송
        yield f"event: state\ndata: {json.dumps({'status': session_manager.state.value})}\n\n"

        while True:
            # 1. 상태가 IDLE이면 Nonce 발급 및 전송 (30초 대기 또는 큐 이벤트 수신)
            refresh_in = NONCE_TTL
            if session_manager.state == SessionState.IDLE:
                nonce = nonce_manager.generate()
                # All displays follow the same rotation deadline, including
                # clients connecting near the end of the current QR's lifetime.
                refresh_in = max(0.1, nonce_manager.generated_at + NONCE_TTL - time.time())
                yield f"event: qr_update\ndata: {json.dumps({'nonce': nonce, 'ttl': refresh_in})}\n\n"

            try:
                # 다음 상태 변경 이벤트 대기 (timeout으로 30초 갱신 타이머 역할 병행)
                msg = await asyncio.wait_for(q.get(), timeout=refresh_in)
                yield msg
            except asyncio.TimeoutError:
                continue  # 30초 경과, 루프 처음으로 돌아가 새 Nonce 생성
    finally:
        session_manager.display_queues.discard(q)


# ─── Internal IPC Endpoints (Called by backend_api.py) ─────────────────────
# app_display (Port 3001)에 등록되어 외부(3100) 터널로부터 물리적/포트 단위로 완전히 격리됨


@app_display.get("/internal/session")
async def get_internal_session(x_internal_token: str = Header(None)):
    """현재 세션 상태를 반환 (내부 호출용)"""
    require_internal_token(x_internal_token)

    return {
        "state": session_manager.state.value,
        "expires_at": session_manager.session_expires_at,
        "has_active_ws": session_manager.active_ws is not None,
    }


@app_display.delete("/internal/session")
async def delete_internal_session(x_internal_token: str = Header(None)):
    """관리자 권한으로 현재 세션을 강제 종료 (내부 호출용)"""
    require_internal_token(x_internal_token)

    if session_manager.state != SessionState.IDLE:
        if await session_manager.end_session(admin_force=True):
            return {
                "status": "terminated",
                "message": "Session forcefully ended by admin",
            }
        else:
            return {"status": "error", "message": "Force termination failed"}

    return {"status": "already_idle", "message": "No active session to terminate"}


@app_display.post("/internal/control")
async def internal_control(body: dict, x_internal_token: str = Header(None)):
    require_internal_token(x_internal_token)
    action, params = validate_control(body)
    if ros_node is None:
        raise HTTPException(503, "ROS bridge is unavailable")
    return ros_node.execute_control(action, params)


@app_display.get("/internal/control/state")
async def internal_control_state(x_internal_token: str = Header(None)):
    require_internal_token(x_internal_token)
    if ros_node is None:
        raise HTTPException(503, "ROS bridge is unavailable")
    return ros_node.hardware_state()


@app_display.get("/display/events")
async def display_events(request: Request):
    """로봇 화면으로 QR Nonce와 세션 상태(Pairing 등)를 실시간 푸시하는 SSE"""
    q = asyncio.Queue(maxsize=8)
    session_manager.display_queues.add(q)
    return StreamingResponse(display_event_generator(q), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app_display.get("/display/qr/{nonce}")
async def qr_image(nonce: str):
    if session_manager.state != SessionState.IDLE or nonce_manager.nonces.get(nonce, 0) <= time.time():
        raise HTTPException(410, "QR expired")
    import qrcode
    import qrcode.image.svg
    output = BytesIO()
    qrcode.make(APP_ORIGIN + "/p#" + nonce,
                image_factory=qrcode.image.svg.SvgPathImage).save(output)
    return Response(output.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app_display.get("/display")
async def display_page():
    return FileResponse(Path(__file__).with_name("display.html"), headers={"Cache-Control": "no-store"})


def mount_visitor_assets(application=None, directory=None):
    application = app_public if application is None else application
    directory = Path(directory) if directory is not None else Path(os.environ.get("DORI_VISITOR_WEB_DIR", Path(__file__).parents[4] / "web/dist-visitor"))
    if (directory / "assets").is_dir():
        # colcon --symlink-install links each asset back to web/dist-visitor.
        # This is a trusted build directory, never a user upload directory.
        application.mount("/assets", StaticFiles(directory=directory / "assets", follow_symlink=True), name="visitor-assets")
    async def recorder():
        return FileResponse(directory / "recorder.js", media_type="text/javascript")
    application.add_api_route("/recorder.js", recorder, methods=["GET"])
    async def index():
        if not (directory / "index.html").is_file():
            raise HTTPException(503, "Build visitor app first")
        return FileResponse(directory / "index.html")
    application.add_api_route("/", index, methods=["GET"])
    application.add_api_route("/p", index, methods=["GET"])


mount_visitor_assets()


# ─── Entrypoint & Runner ───────────────────────────────────────────────────


class GatewayServer(uvicorn.Server):
    """Both listeners share one process-level signal handler in run_servers."""

    def install_signal_handlers(self):
        pass  # Uvicorn < 0.29.

    @contextmanager
    def capture_signals(self):
        yield  # Uvicorn >= 0.29.


async def run_servers():
    config_public = uvicorn.Config(
        app_public,
        host=PUBLIC_HOST,
        port=PUBLIC_PORT,
        log_level="info",
        ws="websockets",
        ws_max_size=MAX_WS_MSG_SIZE,
        ssl_certfile=os.environ.get("DORI_VISITOR_TLS_CERT"),
        ssl_keyfile=os.environ.get("DORI_VISITOR_TLS_KEY"),
        timeout_graceful_shutdown=5,
    )
    config_display = uvicorn.Config(
        app_display, host="127.0.0.1", port=DISPLAY_PORT, log_level="warning",
        timeout_graceful_shutdown=5,
    )

    servers = (GatewayServer(config_public), GatewayServer(config_display))

    def stop_servers(signum, frame):
        for server in servers:
            if server.should_exit and signum == signal.SIGINT:
                server.force_exit = True
            server.should_exit = True

    # 한 이벤트 루프에서 두 서버를 동시에 비동기로 실행 (상태 및 큐 공유 문제 완전 해결)
    # Per-server handlers otherwise compete, leaving one listener alive after
    # SIGTERM. Bound draining also lets an open display SSE close on restart.
    previous = {sig: signal.signal(sig, stop_servers) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        await asyncio.gather(*(server.serve() for server in servers))
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main():
    internal_token()
    # rclpy.init() 등의 로직은 public_lifespan으로 이동하여 삭제됨
    logger.info(
        f"Starting Gateways: Public({PUBLIC_HOST}:{PUBLIC_PORT}), Display(127.0.0.1:{DISPLAY_PORT})"
    )
    asyncio.run(run_servers())


if __name__ == "__main__":
    main()

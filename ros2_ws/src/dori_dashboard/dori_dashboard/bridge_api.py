#!/usr/bin/env python3
"""
DORI WebSocket Gateway & Session Manager (bridge_api.py)
사용자 앱 서빙, QR 페어링, 세션 관리 및 제한된 ROS 프로토콜 게이트웨이를 담당합니다.
"""

from contextlib import asynccontextmanager
import asyncio
import json
import logging
import os
import secrets
import threading
import time
from enum import Enum
from typing import Dict, Optional, Set

import rclpy
from rclpy.node import Node
from action_msgs.msg import GoalID
from std_msgs.msg import Bool, String, Empty
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
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── Configuration ─────────────────────────────────────────────────────────

PUBLIC_PORT = 3100
DISPLAY_PORT = 3001
NONCE_TTL = 30  # QR 갱신 주기 (초)
NONCE_GRACE = 5  # 스캔 지연 오차 허용 (초)
GRACE_TIMEOUT = 90  # WS 끊김 후 재연결 유예 시간 (초)
SESSION_MAX_TIME = 900  # 최대 세션 시간 (15분)
MAX_WS_MSG_SIZE = 1024 * 50

_INTERNAL_TOKEN = os.environ.get("DORI_INTERNAL_TOKEN", "default-internal-secret")
_DEV_MODE = os.environ.get("DORI_DEV_MODE", "").strip().lower() in ("1", "true", "yes")
PUBLIC_HOST = "0.0.0.0" if _DEV_MODE else "127.0.0.1"

ALLOWED_ORIGINS = ["https://app.dgist-dori.xyz"]
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


class PairRequest(BaseModel):
    nonce: str
    consent: bool


# ─── ROS 2 Node (Bridge Gateway) ───────────────────────────────────────────


class BridgeNode(Node):
    def __init__(self):
        super().__init__("bridge_api_node")
        # 하향(ROS -> WS) Subscriptions
        self.create_subscription(String, "llm/response", self.llm_callback, 10)

        # 상향(WS -> ROS) & 제어용 Publishers
        self.pub_wake = self.create_publisher(Bool, "stt/wake_word_detected", 10)
        self.pub_chime = self.create_publisher(String, "hri/audio_cue", 10)
        self.pub_cmd_vel = self.create_publisher(Twist, "cmd_vel", 10)
        self.pub_cancel = self.create_publisher(Bool, "hri/cancel", 10)

        self.cli_llm_reset = self.create_client(Trigger, "llm/reset")
        self.cli_bt_clear = self.create_client(Trigger, "bt/clear_session")

    def llm_callback(self, msg):
        try:
            text = json.loads(msg.data).get("text", "")
        except ValueError:
            return
        if (
            text
            and session_manager.state == SessionState.ACTIVE
            and session_manager.active_ws
        ):
            asyncio.run_coroutine_threadsafe(
                session_manager.active_ws.send_json({"type": "llm_text", "data": text}),
                loop=session_manager.main_loop,
            )

    def trigger_pairing_success(self):
        """페어링 성공 시 웨이크워드 감지 및 차임벨 발생"""
        self.pub_wake.publish(Bool(data=True))
        self.pub_chime.publish(String(data="wake_chime"))
        logger.info("[ROS] Pairing success triggered to HRI")

    async def execute_cleanup(self, timeout_sec: float = 5.0) -> bool:
        """로봇 정지 및 LLM 대화 기록 초기화를 수행한다."""
        self.pub_cancel.publish(Bool(data=True))

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

        # 3. LLM과 BT 초기화 서비스 동시 실행 및 대기
        results = await asyncio.gather(
            call_ros_service(self.cli_llm_reset, "LLM"),
            call_ros_service(self.cli_bt_clear, "BT"),
        )

        logger.info("[ROS] Session cleanup completed")
        # 둘 다 성공했는지 여부 반환 (필요에 따라 엄격도를 조절할 수 있습니다)
        return all(results)


# ─── Core Logic: Nonce & Session Management ────────────────────────────────


class NonceManager:
    def __init__(self):
        self.nonces: Dict[str, float] = {}

    def generate(self) -> str:
        nonce = secrets.token_urlsafe(16)
        # 생성 시간 + TTL + 지연 허용 시간
        self.nonces[nonce] = time.time() + NONCE_TTL + NONCE_GRACE
        return nonce

    def validate_and_consume(self, nonce: str) -> bool:
        self._cleanup()
        if nonce in self.nonces and self.nonces[nonce] > time.time():
            del self.nonces[nonce]  # 1회용 소모
            return True
        return False

    def _cleanup(self):
        now = time.time()
        self.nonces = {k: v for k, v in self.nonces.items() if v > now}


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
        self.session_timer_task: Optional[asyncio.Task] = None
        self.idle_timeout = 120.0  # 2분 무조작 시 강제 종료

    async def broadcast_display(self, event_type: str, data: dict):
        payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        for q in list(self.display_queues):
            try:
                await q.put(payload)
            except Exception:
                self.display_queues.discard(q)

    async def start_session(self):
        nonce_manager.nonces.clear()
        self.state = SessionState.ACTIVE
        self.current_token = secrets.token_hex(32)
        self.session_expires_at = time.time() + SESSION_MAX_TIME
        self.last_activity = time.time()

        if self.grace_task:
            self.grace_task.cancel()
        if self.session_timer_task:
            self.session_timer_task.cancel()

        self.session_timer_task = asyncio.create_task(self._max_time_watcher())
        await self.broadcast_display("paired", {"status": "ACTIVE"})
        ros_node.trigger_pairing_success()
        logger.info("Session ACTIVE")
        return self.current_token

    async def handle_disconnect(self):
        if self.state == SessionState.ACTIVE:
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

            self.state = SessionState.ENDING
            self.current_token = None
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

            if admin_force:
                logger.error("Admin forced cleanup despite failures.")
                self.state = SessionState.IDLE
                await self.broadcast_display("state", {"status": "IDLE"})
                return True

            logger.error(
                "Critical: Cleanup failed completely. Starting background retry task."
            )
            await self.broadcast_display("state", {"status": "ENDING"})

            asyncio.create_task(self._retry_cleanup_loop())
            return False


nonce_manager = NonceManager()
session_manager = SessionManager()


@asynccontextmanager
async def public_lifespan(app: FastAPI):
    # 앱이 시작될 때 단일 메인 이벤트 루프를 확보하여 저장
    session_manager.main_loop = asyncio.get_running_loop()
    yield


# ─── FastAPI 1: Public App (Port 3100) ─────────────────────────────────────

app_public = FastAPI(title="DORI App Gateway", lifespan=public_lifespan)

app_public.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app_public.post("/api/pair")
async def pair_device(req: PairRequest, response: Response):
    if not req.consent:
        raise HTTPException(status_code=400, detail="Consent required")

    if session_manager.state != SessionState.IDLE:
        raise HTTPException(
            status_code=409,
            detail="Robot is currently in use or cleaning up",
        )

    if not nonce_manager.validate_and_consume(req.nonce):
        raise HTTPException(status_code=410, detail="Invalid or expired nonce")

    token = await session_manager.start_session()

    response.set_cookie(
        key="dori_session",
        value=token,
        httponly=True,
        secure=True,  # LAN 테스트 시 False로 변경 필요
        samesite="strict",
        max_age=SESSION_MAX_TIME,
    )
    return {"expires_at": session_manager.session_expires_at}


@app_public.delete("/api/session")
async def delete_session(
    dori_session: Optional[str] = Cookie(None),
):
    if dori_session and dori_session == session_manager.current_token:
        ok = await session_manager.end_session()
        if not ok:
            raise HTTPException(
                status_code=503,
                detail="Session cleanup failed",
            )
    return {"status": "ok"}


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
        or not secrets.compare_digest(cookie_token, session_manager.current_token)
    ):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    if session_manager.active_ws and session_manager.active_ws is not websocket:
        try:
            await session_manager.active_ws.close(code=4000, reason="Replaced")
        except Exception:
            pass

    session_manager.active_ws = websocket
    session_manager.last_activity = time.time()

    if session_manager.state == SessionState.GRACE:
        session_manager.state = SessionState.ACTIVE
        if session_manager.grace_task:
            session_manager.grace_task.cancel()
        await session_manager.broadcast_display("state", {"status": "ACTIVE"})
        logger.info("Session Resumed from GRACE")

    try:
        while True:
            # Heartbeat 감지: 15초 동안 아무 메시지(핑 포함)가 없으면 Exception 발생
            data = await asyncio.wait_for(websocket.receive_text(), timeout=15.0)
            session_manager.last_activity = time.time()

            if len(data) > MAX_WS_MSG_SIZE:
                logger.warning("WS message exceeds size limit, dropping")
                continue

            try:
                payload = json.loads(data)
            except json.JSONDecodeError:
                logger.warning("Invalid JSON format in WS, dropping")
                continue  # 세션을 끊지 않고 해당 메시지만 무시

            # 제한된 자체 프로토콜 처리 (명령어 화이트리스트 필터링)
            cmd_type = payload.get("type")
            if cmd_type == "command":
                action = payload.get("action")
                if action == "STOP":
                    ros_node.pub_cancel.publish(Bool(data=True))
                # 상향 메시지(오디오, 카메라 등) 추가 구현 지점
            elif cmd_type == "heartbeat":
                pass

            if (
                time.time() - session_manager.last_activity
                > session_manager.idle_timeout
            ):
                logger.info("User idle timeout reached.")
                await session_manager.end_session()
                break

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
            if session_manager.state == SessionState.IDLE:
                nonce = nonce_manager.generate()
                yield f"event: qr_update\ndata: {json.dumps({'nonce': nonce, 'ttl': NONCE_TTL})}\n\n"

            try:
                # 다음 상태 변경 이벤트 대기 (timeout으로 30초 갱신 타이머 역할 병행)
                msg = await asyncio.wait_for(q.get(), timeout=NONCE_TTL)
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
    if not x_internal_token or not secrets.compare_digest(
        x_internal_token, _INTERNAL_TOKEN
    ):
        raise HTTPException(status_code=403, detail="Invalid internal token")

    return {
        "state": session_manager.state.value,
        "expires_at": session_manager.session_expires_at,
        "has_active_ws": session_manager.active_ws is not None,
    }


@app_display.delete("/internal/session")
async def delete_internal_session(x_internal_token: str = Header(None)):
    """관리자 권한으로 현재 세션을 강제 종료 (내부 호출용)"""
    if not x_internal_token or not secrets.compare_digest(
        x_internal_token, _INTERNAL_TOKEN
    ):
        raise HTTPException(status_code=403, detail="Invalid internal token")

    if session_manager.state != SessionState.IDLE:
        if await session_manager.end_session(admin_force=True):
            return {
                "status": "terminated",
                "message": "Session forcefully ended by admin",
            }
        else:
            return {"status": "error", "message": "Force termination failed"}

    return {"status": "already_idle", "message": "No active session to terminate"}


@app_display.get("/display/events")
async def display_events(request: Request):
    """로봇 화면으로 QR Nonce와 세션 상태(Pairing 등)를 실시간 푸시하는 SSE"""
    q = asyncio.Queue()
    session_manager.display_queues.add(q)
    return StreamingResponse(display_event_generator(q), media_type="text/event-stream")


# ─── Entrypoint & Runner ───────────────────────────────────────────────────


async def run_servers():
    config_public = uvicorn.Config(
        app_public, host=PUBLIC_HOST, port=PUBLIC_PORT, log_level="info"
    )
    config_display = uvicorn.Config(
        app_display, host="127.0.0.1", port=DISPLAY_PORT, log_level="warning"
    )

    server_public = uvicorn.Server(config_public)
    server_display = uvicorn.Server(config_display)

    # 한 이벤트 루프에서 두 서버를 동시에 비동기로 실행 (상태 및 큐 공유 문제 완전 해결)
    await asyncio.gather(server_public.serve(), server_display.serve())


if __name__ == "__main__":
    rclpy.init()
    global ros_node
    ros_node = BridgeNode()

    # 1. ROS 2 스핀 스레드 시작 (블로킹이므로 별도 스레드 유지)
    threading.Thread(target=lambda: rclpy.spin(ros_node), daemon=True).start()

    # 2. FastAPI 서버들을 단일 이벤트 루프로 실행
    logger.info(
        f"Starting Gateways: Public({PUBLIC_PORT}), Display(127.0.0.1:{DISPLAY_PORT})"
    )
    asyncio.run(run_servers())

    ros_node.destroy_node()
    rclpy.shutdown()

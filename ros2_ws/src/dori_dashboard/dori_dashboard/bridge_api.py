#!/usr/bin/env python3
"""
DORI WebSocket Gateway & Session Manager (bridge_api.py)
사용자 앱 서빙, QR 페어링, 세션 관리 및 제한된 ROS 프로토콜 게이트웨이를 담당합니다.
"""

import asyncio
import json
import logging
import secrets
import threading
import time
from enum import Enum
from typing import Dict, Optional, Set

import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger
from geometry_msgs.msg import Twist

import uvicorn
from fastapi import (
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
ALLOWED_ORIGINS = [
    "[https://app.dgist-dori.xyz](https://app.dgist-dori.xyz)",
    "http://localhost:3100",
]

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
        self.create_subscription(String, "/dori/llm/text", self.llm_callback, 10)

        # 상향(WS -> ROS) & 제어용 Publishers
        self.pub_wake = self.create_publisher(Bool, "/stt/wake_word_detected", 10)
        self.pub_chime = self.create_publisher(String, "/hri/audio_cue", 10)
        self.pub_cmd_vel = self.create_publisher(Twist, "/cmd_vel", 10)

        self.cli_llm_reset = self.create_client(Trigger, "/dori/llm/reset")

    def llm_callback(self, msg):
        # 활성 세션이 있으면 WS로 하향 전송
        if session_manager.state == SessionState.ACTIVE and session_manager.active_ws:
            asyncio.run_coroutine_threadsafe(
                session_manager.active_ws.send_json(
                    {"type": "llm_text", "data": msg.data}
                ),
                loop=session_manager.main_loop,
            )

    def trigger_pairing_success(self):
        """페어링 성공 시 웨이크워드 감지 및 차임벨 발생"""
        self.pub_wake.publish(Bool(data=True))
        self.pub_chime.publish(String(data="wake_chime"))
        logger.info("[ROS] Pairing success triggered to HRI")

    async def execute_cleanup(self, timeout_sec: float = 5.0) -> bool:
        """로봇 정지 및 LLM 대화 기록 초기화를 수행한다."""
        # 1. 로봇 정지 명령
        self.pub_cmd_vel.publish(Twist())

        # 2. LLM 리셋 서비스가 준비될 때까지 대기
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_sec

        while not self.cli_llm_reset.wait_for_service(timeout_sec=0.0):
            if loop.time() >= deadline:
                logger.error("LLM reset service unavailable")
                return False
            await asyncio.sleep(0.1)

        # 3. 서비스 요청
        request = Trigger.Request()
        ros_future = self.cli_llm_reset.call_async(request)
        async_future = loop.create_future()

        def on_done(future):
            try:
                result = future.result()
            except Exception as exc:

                def set_exception(error=exc):
                    if not async_future.done():
                        async_future.set_exception(error)

                loop.call_soon_threadsafe(set_exception)
            else:

                def set_result(value=result):
                    if not async_future.done():
                        async_future.set_result(value)

                loop.call_soon_threadsafe(set_result)

        ros_future.add_done_callback(on_done)

        try:
            response = await asyncio.wait_for(
                async_future,
                timeout=max(0.1, deadline - loop.time()),
            )
        except asyncio.TimeoutError:
            logger.error("LLM reset service timed out")
            return False
        except Exception:
            logger.exception("LLM reset service call failed")
            return False

        if not response.success:
            logger.error("LLM reset failed: %s", response.message)
            return False

        logger.info("[ROS] Session cleanup completed")
        return True


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
        self.main_loop = asyncio.get_event_loop()
        self.grace_task: Optional[asyncio.Task] = None

    async def broadcast_display(self, event_type: str, data: dict):
        payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        for q in list(self.display_queues):
            try:
                await q.put(payload)
            except Exception:
                self.display_queues.discard(q)

    async def start_session(self):
        self.state = SessionState.ACTIVE
        self.current_token = secrets.token_hex(32)
        self.session_expires_at = time.time() + SESSION_MAX_TIME
        if self.grace_task:
            self.grace_task.cancel()

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

    async def end_session(self):
        if self.state == SessionState.IDLE:
            return True

        self.state = SessionState.ENDING

        # 기존 세션의 접근 권한을 먼저 무효화
        self.current_token = None
        self.active_ws = None

        # 실제 LLM 초기화 완료까지 대기
        cleanup_ok = await ros_node.execute_cleanup()

        if not cleanup_ok:
            logger.error(
                "Session cleanup failed. "
                "Keeping the robot unavailable until reset succeeds."
            )
            await self.broadcast_display("state", {"status": "ENDING"})
            return False

        self.state = SessionState.IDLE
        await self.broadcast_display("state", {"status": "IDLE"})
        logger.info("Session ENDED and cleaned up")
        return True


nonce_manager = NonceManager()
session_manager = SessionManager()

# ─── FastAPI 1: Public App (Port 3100) ─────────────────────────────────────

app_public = FastAPI(title="DORI App Gateway")

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


@app_public.get("/internal/session")
async def get_internal_session(request: Request):
    """현재 세션 상태를 반환 (내부 호출용)"""
    # 보안 강화를 위해 로컬호스트 요청만 허용
    if request.client and request.client.host != "127.0.0.1":
        raise HTTPException(status_code=403, detail="Localhost only")

    return {
        "state": session_manager.state.value,
        "expires_at": session_manager.session_expires_at,
        "has_active_ws": session_manager.active_ws is not None,
    }


@app_public.delete("/internal/session")
async def delete_internal_session(request: Request):
    """관리자 권한으로 현재 세션을 강제 종료 (내부 호출용)"""
    if request.client and request.client.host != "127.0.0.1":
        raise HTTPException(status_code=403, detail="Localhost only")

    if session_manager.state != SessionState.IDLE:
        await session_manager.end_session()
        return {"status": "terminated", "message": "Session forcefully ended by admin"}

    return {"status": "already_idle", "message": "No active session to terminate"}


@app_public.websocket("/ws/user")
async def websocket_user(websocket: WebSocket):
    # 1. Origin 검증 (Cross-site WS Hijacking 방지)
    origin = websocket.headers.get("origin")
    if origin not in ALLOWED_ORIGINS:
        await websocket.close(code=1008)
        return

    # 2. 쿠키 기반 세션 토큰 검증
    cookie_token = websocket.cookies.get("dori_session")
    if not cookie_token or cookie_token != session_manager.current_token:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    session_manager.active_ws = websocket

    if session_manager.state == SessionState.GRACE:
        session_manager.state = SessionState.ACTIVE
        if session_manager.grace_task:
            session_manager.grace_task.cancel()
        await session_manager.broadcast_display("state", {"status": "ACTIVE"})
        logger.info("Session Resumed from GRACE")

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)

            # 제한된 자체 프로토콜 처리 (명령어 화이트리스트 필터링)
            cmd_type = payload.get("type")
            if cmd_type == "command":
                action = payload.get("action")
                if action == "STOP":
                    ros_node.pub_cmd_vel.publish(Twist())
                # 상향 메시지(오디오, 카메라 등) 추가 구현 지점
            elif cmd_type == "heartbeat":
                pass

    except WebSocketDisconnect:
        await session_manager.handle_disconnect()
    except Exception as e:
        logger.error(f"WS Error: {e}")
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


@app_display.get("/display/events")
async def display_events(request: Request):
    """로봇 화면으로 QR Nonce와 세션 상태(Pairing 등)를 실시간 푸시하는 SSE"""
    q = asyncio.Queue()
    session_manager.display_queues.add(q)
    return StreamingResponse(display_event_generator(q), media_type="text/event-stream")


# ─── Entrypoint & Runner ───────────────────────────────────────────────────


def run_ros_node():
    rclpy.init()
    global ros_node
    ros_node = BridgeNode()
    rclpy.spin(ros_node)
    ros_node.destroy_node()
    rclpy.shutdown()


def run_display_server():
    uvicorn.run(app_display, host="127.0.0.1", port=DISPLAY_PORT, log_level="warning")


if __name__ == "__main__":
    # 1. ROS 2 스핀 스레드 시작
    threading.Thread(target=run_ros_node, daemon=True).start()

    # 2. Display (127.0.0.1 전용) 스레드 시작
    threading.Thread(target=run_display_server, daemon=True).start()

    # 3. Public App (Tunnel) 메인 스레드 실행
    logger.info(f"Starting Public Gateway on port {PUBLIC_PORT}")
    uvicorn.run(app_public, host="0.0.0.0", port=PUBLIC_PORT, log_level="info")

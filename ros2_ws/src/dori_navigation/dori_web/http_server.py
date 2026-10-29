"""Small same-origin HTTP transport. ROS operations stay on the executor thread."""

from concurrent.futures import Future, TimeoutError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit
from .voice import GeminiNavigator


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, bridge, role="admin"):
        self.bridge = bridge
        self.role = role
        self.voice = GeminiNavigator() if role == "user" else None
        self.csrf = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, *_args):
        pass

    def send(self, status, content, mime="application/json; charset=utf-8"):
        if not isinstance(content, bytes):
            content = json.dumps(content, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'self'",
        )
        self.end_headers()
        try:
            self.wfile.write(content)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = urlsplit(self.path).path
        bridge = self.server.bridge
        if path == "/api/state":
            with bridge.lock:
                state = bridge.snapshot.copy()
                state["server_age"] = time.monotonic() - bridge.snapshot_time
            static = Path(__file__).parent / "static"
            state["ui_version"] = str(
                max(p.stat().st_mtime_ns for p in static.iterdir())
            )
            state["csrf"] = self.server.csrf
            return self.send(200, state)
        if path == "/api/session":
            return self.send(
                200,
                {
                    "csrf": self.server.csrf,
                    "role": self.server.role,
                    "voice_ready": bool(
                        self.server.voice and self.server.voice.configured()
                    ),
                    "voice_url": os.getenv("DORI_USER_HTTPS_URL", ""),
                },
            )
        if path == "/api/map.png":
            with bridge.lock:
                png = bridge.map_png
            return self.send(200 if png else 404, png or b"", "image/png")
        assets = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        if self.server.role == "user":
            assets = {
                "/": ("user.html", "text/html; charset=utf-8"),
                "/user.js": ("user.js", "text/javascript; charset=utf-8"),
                "/user-map.js": ("user-map.js", "text/javascript; charset=utf-8"),
                "/microphone.js": ("microphone.js", "text/javascript; charset=utf-8"),
                "/user.css": ("user.css", "text/css; charset=utf-8"),
            }
        if path in assets:
            name, mime = assets[path]
            return self.send(
                200, (Path(__file__).parent / "static" / name).read_bytes(), mime
            )
        self.send(404, {"error": "Not found"})

    def do_POST(self):
        origin = self.headers.get("Origin")
        host = self.headers.get("Host")
        if (
            self.headers.get("X-Dori-Control") != self.server.csrf
            or (origin and urlsplit(origin).netloc != host)
            or self.headers.get("Sec-Fetch-Site") == "cross-site"
        ):
            return self.send(403, {"error": "Please reload this page and try again."})
        path = urlsplit(self.path).path
        if path not in ("/api/command", "/api/chat", "/api/transcribe") or (
            path != "/api/command" and self.server.role != "user"
        ):
            return self.send(404, {"error": "Not found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if (
                not 0
                < length
                <= (
                    4000100
                    if path == "/api/transcribe"
                    else 8192 if path == "/api/chat" else 2048
                )
            ):
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError("Expected object")
            if path == "/api/transcribe":
                return self.send(
                    200,
                    self.server.voice.transcribe(
                        data.get("audio"), data.get("mime_type")
                    ),
                )
            if path == "/api/chat":
                with self.server.bridge.lock:
                    state = self.server.bridge.snapshot.copy()
                if time.monotonic() - self.server.bridge.snapshot_time > 2:
                    raise ValueError("The robot connection is unavailable.")
                result = self.server.voice.interpret(
                    data.get("text"),
                    state.get("destinations", []),
                    data.get("history"),
                    {
                        "moving": state.get("values", {}).get("active", False),
                        "retry": state.get("values", {}).get("retry"),
                        "destination": state.get("goal_name"),
                    },
                )
                return self.send(200, result)
            if self.server.role == "user" and data.get("action") not in (
                "enable",
                "stop",
                "heartbeat",
                "named_goal",
                "relative_goal",
            ):
                return self.send(
                    403,
                    {
                        "error": "This action is available only on the administrator page."
                    },
                )
            future = Future()
            self.server.bridge.commands.put_nowait((data, future))
            try:
                result = future.result(timeout=2)
            except TimeoutError:
                future.cancel()  # An expired request must never execute later.
                return self.send(
                    503, {"error": "Robot response timed out. Please check its status."}
                )
            if self.server.role == "user":
                result = {k: v for k, v in result.items() if k != "message"}
            self.send(200, result)
        except Exception as exc:
            message = str(exc)
            if self.server.role == "user" and any(
                "\uac00" <= c <= "\ud7a3" for c in message
            ):
                message = (
                    "Another browser is controlling Dori."
                    if "다른 브라우저" in message
                    else "Dori is not ready to move. Please check the robot status or ask the operator."
                )
            self.send(400, {"error": message})

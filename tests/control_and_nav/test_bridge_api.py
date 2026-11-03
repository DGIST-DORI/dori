"""Session and WebSocket regressions without starting ROS or using robot hardware."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from starlette.websockets import WebSocket


BRIDGE_PATH = (
    Path(__file__).resolve().parents[2]
    / "ros2_ws/src/dori_dashboard/dori_dashboard/bridge_api.py"
)
SPEC = importlib.util.spec_from_file_location("bridge_api_under_test", BRIDGE_PATH)
bridge = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bridge)


class ASGIConnection:
    """Exercise Starlette's real frame handling with an in-memory ASGI connection."""

    def __init__(self, token):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        self.processed = None
        self.websocket = WebSocket(
            {
                "type": "websocket",
                "path": "/ws/user",
                "headers": [
                    (b"origin", bridge.ALLOWED_ORIGINS[0].encode()),
                    (b"cookie", f"dori_session={token}".encode()),
                ],
            },
            self.receive,
            self.outgoing.put,
        )
        self.task = asyncio.create_task(bridge.websocket_user(self.websocket))

    async def receive(self):
        # Re-entering receive means the preceding frame has been handled.
        if self.processed is not None:
            self.processed.set()
        message, self.processed = await self.incoming.get()
        return message

    async def feed(self, message):
        processed = asyncio.Event()
        await self.incoming.put((message, processed))
        await asyncio.wait_for(processed.wait(), timeout=2)
        assert not self.task.done()


class BridgeAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = bridge.SessionManager()
        self.ros = SimpleNamespace(
            trigger_pairing_success=Mock(),
            pub_cancel=Mock(),
            execute_cleanup=AsyncMock(return_value=True),
        )
        self.clock = Mock(return_value=100.0)
        for target, value in (
            ("session_manager", self.manager),
            ("ros_node", self.ros),
            ("time", SimpleNamespace(time=bridge.time.time, monotonic=self.clock)),
        ):
            replacement = patch.object(bridge, target, value, create=True)
            replacement.start()
            self.addCleanup(replacement.stop)
        self.connections = []
        await self.manager.start_session()

    async def asyncTearDown(self):
        for connection in self.connections:
            connection.task.cancel()
        await asyncio.gather(
            *(connection.task for connection in self.connections),
            return_exceptions=True,
        )
        await self.manager._cancel_session_timers()

    async def connect(self):
        connection = ASGIConnection(self.manager.current_token)
        self.connections.append(connection)
        await connection.feed({"type": "websocket.connect"})
        self.assertEqual(
            (await connection.outgoing.get())["type"], "websocket.accept"
        )
        return connection

    async def test_invalid_json_shapes_and_binary_keep_session_active(self):
        connection = await self.connect()
        self.clock.return_value = 110.0
        frames = [
            {"text": text}
            for text in (
                "[]", "123", "null", "true", '"text"', "{", "{}",
                '{"type": "unknown"}',
                '{"type": "command", "action": "unknown"}',
                '{"type": "heartbeat"}',
            )
        ] + [{"bytes": b"\x00\xffcamera/audio"}, {"bytes": b""}]
        for frame in frames:
            with self.subTest(frame=frame):
                await connection.feed({"type": "websocket.receive", **frame})
                self.assertEqual(self.manager.state, bridge.SessionState.ACTIVE)
                self.assertIs(self.manager.active_ws, connection.websocket)
                self.assertEqual(self.manager.last_activity, 100.0)
                self.assertIsNone(self.manager.grace_task)
        self.ros.pub_cancel.publish.assert_not_called()
        await connection.feed({
            "type": "websocket.receive",
            "text": '{"type": "command", "action": "STOP"}',
        })
        self.ros.pub_cancel.publish.assert_called_once()
        self.assertTrue(self.ros.pub_cancel.publish.call_args.args[0].data)
        self.assertEqual(self.manager.last_activity, 110.0)

    async def test_idle_watcher_expires_without_incoming_messages(self):
        connection = await self.connect()
        idle_task = self.manager.idle_task
        max_task = self.manager.session_timer_task
        self.clock.return_value = 221.0
        await asyncio.wait_for(idle_task, timeout=2)
        self.assertEqual(self.manager.state, bridge.SessionState.IDLE)
        self.assertIsNone(self.manager.current_token)
        self.assertEqual(await connection.outgoing.get(), {
            "type": "websocket.close", "code": 1000, "reason": "",
        })
        self.assertTrue(max_task.cancelled())
        self.ros.execute_cleanup.assert_awaited_once()

    async def test_heartbeat_does_not_prevent_idle_expiry(self):
        connection = await self.connect()
        for now in (130.0, 160.0, 190.0, 219.0):
            self.clock.return_value = now
            await connection.feed({
                "type": "websocket.receive", "text": '{"type": "heartbeat"}',
            })
        self.assertEqual(self.manager.last_activity, 100.0)
        self.clock.return_value = 221.0
        await asyncio.wait_for(self.manager.idle_task, timeout=2)
        self.assertEqual(self.manager.state, bridge.SessionState.IDLE)

    async def test_stop_extends_idle_deadline(self):
        connection = await self.connect()
        self.clock.return_value = 219.0
        await connection.feed({
            "type": "websocket.receive",
            "text": '{"type": "command", "action": "STOP"}',
        })
        self.clock.return_value = 221.0
        # Run an independent watcher check beyond the original idle deadline.
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(self.manager._idle_watcher(), timeout=0.02)
        self.assertEqual(self.manager.state, bridge.SessionState.ACTIVE)
        self.clock.return_value = 340.0
        await asyncio.wait_for(self.manager.idle_task, timeout=2)
        self.assertEqual(self.manager.state, bridge.SessionState.IDLE)

    async def test_disconnect_uses_grace_and_reconnect_resumes(self):
        connection = await self.connect()
        await connection.incoming.put((
            {"type": "websocket.disconnect", "code": 1000}, asyncio.Event(),
        ))
        await asyncio.wait_for(connection.task, timeout=2)
        self.assertEqual(self.manager.state, bridge.SessionState.GRACE)
        grace_task = self.manager.grace_task
        idle_task = self.manager.idle_task
        self.clock.return_value = 221.0
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(self.manager._idle_watcher(), timeout=0.02)
        self.assertEqual(self.manager.state, bridge.SessionState.GRACE)
        resumed = await self.connect()
        self.assertEqual(self.manager.state, bridge.SessionState.ACTIVE)
        self.assertIs(self.manager.active_ws, resumed.websocket)
        self.assertIs(self.manager.idle_task, idle_task)
        self.assertEqual(self.manager.last_activity, 221.0)
        self.assertTrue(grace_task.cancelled())

    async def test_session_end_and_restart_do_not_leave_old_timers(self):
        old_tasks = (self.manager.idle_task, self.manager.session_timer_task)
        await self.manager.end_session()
        self.assertTrue(all(task.cancelled() for task in old_tasks))
        await self.manager.start_session()
        self.assertTrue(all(task.done() for task in old_tasks))
        self.assertEqual(self.manager.state, bridge.SessionState.ACTIVE)
        self.assertNotIn(self.manager.idle_task, old_tasks)

    async def test_max_and_grace_watchers_can_end_without_cancelling_themselves(self):
        for timeout in ("SESSION_MAX_TIME", "GRACE_TIMEOUT"):
            with self.subTest(timeout=timeout), patch.object(bridge, timeout, 0):
                await self.manager.start_session()
                if timeout == "GRACE_TIMEOUT":
                    await self.manager.handle_disconnect()
                    task = self.manager.grace_task
                else:
                    task = self.manager.session_timer_task
                await asyncio.wait_for(task, timeout=2)
                self.assertFalse(task.cancelled())
                self.assertEqual(self.manager.state, bridge.SessionState.IDLE)

    async def test_size_guard_uses_utf8_bytes_and_preserves_connection(self):
        connection = await self.connect()
        prefix = '{"type":"command","action":"STOP","padding":"'
        suffix = '"}'
        padding_size = bridge.MAX_WS_MSG_SIZE - len(prefix + suffix)
        at_limit = prefix + "x" * padding_size + suffix
        multibyte = prefix + "가" * (padding_size // 3 + 1) + suffix
        self.assertLess(len(multibyte), bridge.MAX_WS_MSG_SIZE)
        self.assertGreater(len(multibyte.encode()), bridge.MAX_WS_MSG_SIZE)
        for frame in (
            {"text": at_limit + " "}, {"text": multibyte},
            {"bytes": b"x" * (bridge.MAX_WS_MSG_SIZE + 1)},
        ):
            await connection.feed({"type": "websocket.receive", **frame})
        self.ros.pub_cancel.publish.assert_not_called()
        self.assertEqual(self.manager.last_activity, 100.0)
        await connection.feed({"type": "websocket.receive", "text": at_limit})
        self.ros.pub_cancel.publish.assert_called_once()
        self.assertEqual(self.manager.state, bridge.SessionState.ACTIVE)

    async def test_public_server_config_limits_messages_at_transport(self):
        with patch.object(bridge.uvicorn, "Server") as server:
            server.return_value.serve = AsyncMock()
            await bridge.run_servers()
        config = server.call_args_list[0].args[0]
        self.assertEqual(config.ws, "websockets")
        self.assertEqual(config.ws_max_size, bridge.MAX_WS_MSG_SIZE)
        config.load()
        from uvicorn.server import ServerState
        from websockets.exceptions import PayloadTooBig
        from websockets.frames import Frame, OP_BINARY, OP_CONT, OP_TEXT

        limit = bridge.MAX_WS_MSG_SIZE
        cases = (
            ([Frame(OP_TEXT, b"x" * limit)], "x" * limit),
            ([Frame(OP_BINARY, b"x" * limit)], b"x" * limit),
            ([Frame(OP_TEXT, b"x" * (limit + 1))], None),
            ([Frame(OP_BINARY, b"x" * (limit + 1))], None),
            ([Frame(OP_TEXT, ("가" * (limit // 3 + 1)).encode())], None),
            ([
                Frame(OP_TEXT, b"x" * (limit // 2), fin=False),
                Frame(OP_CONT, b"x" * (limit // 2 + 1)),
            ], None),
        )
        for index, (frames, expected) in enumerate(cases):
            with self.subTest(case=index):
                protocol = config.ws_protocol_class(config, ServerState(), {})
                protocol.reader.feed_data(b"".join(
                    frame.serialize(mask=True) for frame in frames
                ))
                # Use the actual configured transport parser, before ASGI receives
                # a message. Oversized and fragmented messages must fail here.
                if expected is None:
                    with self.assertRaises(PayloadTooBig):
                        await asyncio.wait_for(protocol.read_message(), timeout=2)
                else:
                    self.assertEqual(
                        await asyncio.wait_for(protocol.read_message(), timeout=2),
                        expected,
                    )


if __name__ == "__main__":
    unittest.main()

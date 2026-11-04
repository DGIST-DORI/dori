"""Security boundaries and deadman behavior; no ROS graph or hardware is started."""
import asyncio
import importlib.util
import json
import os
import subprocess
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import MethodType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from starlette.websockets import WebSocket

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / 'ros2_ws/src/dori_dashboard/dori_dashboard'
sys.path.insert(0, str(PACKAGE))
spec = importlib.util.spec_from_file_location('dashboard_security_backend', PACKAGE / 'backend_api.py')
backend = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = backend
spec.loader.exec_module(backend)
import bridge_api as bridge
from control_contract import validate_control, MOVE_TIMEOUT
from internal_auth import require_internal_token
from access_config import load_access_config


class AccessConfigTests(unittest.TestCase):
    def test_operator_alias_permits_control_but_not_administration(self):
        principal = backend.AuthPrincipal('operator', frozenset({'operator'}), 'jwt', time.time() + 60)
        self.assertTrue(backend._has_permission(principal, 'view'))
        self.assertTrue(backend._has_permission(principal, 'control'))
        self.assertFalse(backend._has_permission(principal, 'admin'))

    def test_persistent_settings_survive_without_shell_exports_and_env_overrides(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            (root / 'config').mkdir()
            config = {'team_domain': 'https://test.cloudflareaccess.com',
                      'audience': 'dashboard', 'role_map': ''}
            (root / 'config/dashboard_access.json').write_text(json.dumps(config))
            self.assertEqual(load_access_config(root), config)
            with patch.dict(os.environ, {'DORI_CF_AUDIENCE': 'another-app',
                                         'DORI_CF_ROLE_MAP': 'admin@example.org:admin'}):
                self.assertEqual(load_access_config(root), {
                    **config, 'audience': 'another-app', 'role_map': 'admin@example.org:admin'})
            with patch.dict(os.environ, {'DORI_CF_TEAM_DOMAIN': '', 'DORI_CF_AUDIENCE': ''}):
                self.assertEqual(load_access_config(root)['team_domain'], '')
                self.assertEqual(load_access_config(root)['audience'], '')

    def test_missing_file_still_supports_environment_only_and_local_fallback(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            self.assertEqual(load_access_config(Path(folder)), {
                'team_domain': '', 'audience': '', 'role_map': ''})
            with patch.dict(os.environ, {'DORI_CF_TEAM_DOMAIN': 'https://test.cloudflareaccess.com',
                                         'DORI_CF_AUDIENCE': 'dashboard'}):
                self.assertEqual(load_access_config(Path(folder))['audience'], 'dashboard')

    def test_malformed_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {}, clear=True):
            root = Path(folder)
            (root / 'config').mkdir()
            for content in ('{', '[]', '{"audience": 123}'):
                (root / 'config/dashboard_access.json').write_text(content)
                with self.subTest(content=content), self.assertRaises(RuntimeError):
                    load_access_config(root)


class DashboardSecurityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.secret = 'test-jwt-key-' * 4
        self.admin = backend.AuthPrincipal('admin', frozenset({'admin'}), 'jwt', time.time() + 300)
        self.stack = []
        for target, value in (
            ('_JWT_SECRET', self.secret), ('_JWT_AUDIENCE', ''), ('_JWT_ISSUER', ''),
            ('_CONTROL_EXECUTOR', 'dry-run'), ('_BREAK_GLASS_ENABLED', False),
            ('_CF_TEAM_DOMAIN', 'https://test.cloudflareaccess.com'), ('_CF_AUDIENCE', 'dashboard'),
            ('_CF_ROLE_MAP_RAW', 'admin@example.org:admin'),
        ):
            patcher = patch.object(backend, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.dict(os.environ, {'DORI_INTERNAL_TOKEN': 'test-internal-' * 4})
        patcher.start()
        self.addCleanup(patcher.stop)
        backend._auth_sessions.clear()
        backend._ws_tickets.clear()
        backend._control_rate_events.clear()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url='https://dash.test')
        self.addAsyncCleanup(self.client.aclose)

    def token(self, **changes):
        payload = {'sub': 'admin', 'roles': ['admin'], 'exp': time.time() + 300}
        payload.update(changes)
        return jwt.encode(payload, self.secret, algorithm='HS256')

    async def login(self, **changes):
        return await self.client.post('/api/auth/session', headers={'Authorization': f'Bearer {self.token(**changes)}'})

    async def test_jwt_expiration_is_required_and_malformed_values_are_401(self):
        claims = [None, 'bad', '9999999999', float('nan'), float('inf'), True, 0, {}, []]
        for exp in claims:
            with self.subTest(exp=exp):
                response = await self.login(exp=exp)
                self.assertEqual(response.status_code, 401)
        token = jwt.encode({'sub': 'admin'}, self.secret, algorithm='HS256')
        response = await self.client.get('/api/auth/session', headers={'Authorization': f'Bearer {token}'})
        self.assertEqual(response.status_code, 401)

    async def test_cf_requires_issuer_audience_exp_and_rs256(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        client = SimpleNamespace(get_signing_key_from_jwt=Mock(return_value=SimpleNamespace(key=key.public_key())))
        payload = {'sub': '123', 'email': 'admin@example.org', 'iss': backend._CF_TEAM_DOMAIN,
                   'aud': 'dashboard', 'exp': time.time() + 300}
        with patch.object(backend, '_jwks_client', client):
            principal = await backend._authenticate_request(None, None, jwt.encode(payload, key, algorithm='RS256'))
            self.assertEqual(principal.roles, frozenset({'admin'}))
            for field, value in [('iss', 'https://evil.cloudflareaccess.com'), ('aud', 'other'), ('exp', None)]:
                broken = dict(payload, **{field: value})
                with self.subTest(field=field), self.assertRaises(HTTPException) as exc:
                    await backend._authenticate_request(None, None, jwt.encode(broken, key, algorithm='RS256'))
                self.assertEqual(exc.exception.status_code, 401)
            for field in ('iss', 'aud', 'exp', 'sub'):
                broken = {k: v for k, v in payload.items() if k != field}
                with self.subTest(missing=field), self.assertRaises(HTTPException):
                    await backend._authenticate_request(None, None, jwt.encode(broken, key, algorithm='RS256'))
            with self.assertRaises(HTTPException):
                await backend._authenticate_request(None, None, self.token())

    async def test_jwks_miss_does_not_block_event_loop(self):
        started, release = threading.Event(), threading.Event()
        def blocked_verify(token):
            started.set()
            release.wait(2)
            return self.admin
        with patch.object(backend, '_verify_cf_jwt', blocked_verify):
            task = asyncio.create_task(backend._authenticate_request(None, None, 'test'))
            try:
                for _ in range(100):
                    if started.is_set():
                        break
                    await asyncio.sleep(.001)
                self.assertTrue(started.is_set())
                response = await asyncio.wait_for(self.client.get('/api/tunnel-url'), .5)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(task.done())
            finally:
                release.set()
                await task

    async def test_cf_browser_session_works_without_local_login_and_after_logout(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwks = SimpleNamespace(get_signing_key_from_jwt=Mock(
            return_value=SimpleNamespace(key=key.public_key())))
        payload = {'sub': '123', 'email': 'viewer@example.org', 'iss': backend._CF_TEAM_DOMAIN,
                   'aud': 'dashboard', 'exp': time.time() + 300}
        headers = {'Cf-Access-Jwt-Assertion': jwt.encode(payload, key, algorithm='RS256')}
        with patch.object(backend, '_jwks_client', jwks):
            for _ in range(2):
                response = await self.client.get('/api/auth/session', headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['auth_type'], 'cf_access')
                self.assertEqual(response.json()['roles'], ['viewer'])
                self.assertFalse(backend._auth_sessions)
                response = await self.client.delete('/api/auth/session', headers=headers)
                self.assertEqual(response.json()['logout_url'], '/cdn-cgi/access/logout')
                self.assertEqual((await self.client.get('/api/auth/session')).status_code, 401)

    async def test_missing_cf_config_is_server_error_not_invalid_user_credentials(self):
        with patch.object(backend, '_jwks_client', None):
            response = await self.client.get('/api/auth/session',
                                             headers={'Cf-Access-Jwt-Assertion': 'test'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()['detail'], 'Cloudflare Access not configured')

    async def test_static_tokens_require_explicit_break_glass(self):
        with patch.object(backend, '_ACCESS_ROLE_MAP', {'emergency': self.admin}):
            response = await self.client.get('/api/auth/session', headers={'Access': 'emergency'})
            self.assertEqual(response.status_code, 401)
            with patch.object(backend, '_BREAK_GLASS_ENABLED', True):
                response = await self.client.get('/api/auth/session', headers={'Access': 'emergency'})
                self.assertEqual(response.status_code, 200)
                with self.assertRaises(HTTPException):
                    await backend._authenticate_request(None, '한글', None)

    async def test_browser_session_expiry_permissions_and_logout(self):
        response = await self.login()
        self.assertEqual(response.status_code, 200)
        self.assertIn('HttpOnly', response.headers['set-cookie'])
        self.assertIn('Secure', response.headers['set-cookie'])
        self.assertIn('SameSite=strict', response.headers['set-cookie'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertEqual((await self.client.get('/api/auth/session')).status_code, 200)
        self.assertEqual((await self.client.post('/api/auth/ws-ticket')).status_code, 200)
        cookie = self.client.cookies.get(backend._AUTH_COOKIE)
        expiry = backend._auth_sessions[cookie][0]
        self.assertLessEqual(expiry, time.time() + 301)
        await self.client.post('/api/auth/session')
        renewed = self.client.cookies.get(backend._AUTH_COOKIE)
        self.assertLessEqual(backend._auth_sessions[renewed][0], expiry)
        await self.client.post('/api/auth/ws-ticket')
        await self.client.delete('/api/auth/session')
        self.assertNotIn(renewed, backend._auth_sessions)
        self.assertFalse(any(r[2] == renewed for r in backend._ws_tickets.values()))
        self.assertEqual((await self.client.get('/api/auth/session')).status_code, 401)
        await self.login(roles=['viewer'])
        self.assertEqual((await self.client.post('/api/auth/ws-ticket')).status_code, 403)
        self.assertEqual((await self.client.post('/api/control/actions', json={'action': 'stop'})).status_code, 403)

    async def test_cookie_expires_and_cannot_be_extended(self):
        await self.login()
        cookie = self.client.cookies.get(backend._AUTH_COOKIE)
        backend._auth_sessions[cookie] = (time.time() - 1, self.admin)
        self.assertEqual((await self.client.post('/api/auth/session')).status_code, 401)

    async def test_viewer_cannot_control_via_navigation_proxy(self):
        await self.login(roles=['viewer'])
        response = await self.client.post('/navigation/api/command', json={'action': 'stop'})
        self.assertEqual(response.status_code, 403)

    async def test_offline_token_issuer_matches_backend_and_caps_lifetime(self):
        command = [sys.executable, str(ROOT / 'tools/auth/issue_dashboard_token.py'),
                   '--user', 'operator', '--role', 'control', '--ttl', '60']
        env = {**os.environ, 'DORI_API_JWT_SECRET': self.secret,
               'DORI_API_JWT_ISSUER': '', 'DORI_API_JWT_AUDIENCE': ''}
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0)
        principal = backend._verify_fallback_jwt(result.stdout.strip())
        self.assertEqual(principal.user_id, 'operator')
        self.assertEqual(principal.roles, frozenset({'control'}))
        self.assertLessEqual(principal.expires_at, time.time() + 60)
        result = subprocess.run(command[:-1] + ['901'], env=env, capture_output=True, text=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')

    async def test_origin_blocks_cross_site_but_allows_preflight_for_access(self):
        response = await self.client.post('/api/auth/session', headers={'Origin': 'https://evil.test', 'Authorization': f'Bearer {self.token()}'})
        self.assertEqual(response.status_code, 403)
        response = await self.client.options('/api/auth/session', headers={
            'Origin': 'https://dash.dgist-dori.xyz', 'Access-Control-Request-Method': 'DELETE',
            'Access-Control-Request-Headers': 'Access',
        })
        self.assertEqual(response.status_code, 200)
        with patch.object(backend, '_DEV_MODE', True):
            response = await self.client.get('/api/tunnel-url', headers={'Origin': 'https://localhost.evil.test'})
            self.assertEqual(response.status_code, 403)

    async def test_controls_reject_nonfinite_bool_unsupported_modes_and_default_dry_run(self):
        await self.login()
        for value in ('NaN', 'Infinity', '-Infinity', 'true', '"0.1"', '1e999'):
            for field in ('linear_x', 'linear_y', 'angular_z'):
                response = await self.client.post('/api/control/actions', content='{"action":"move","params":{"'+field+'":'+value+'}}', headers={'Content-Type': 'application/json'})
                self.assertEqual(response.status_code, 400, (value, field, response.text))
        for mode in ('dock', 'idle', 'safe'):
            self.assertEqual((await self.client.post('/api/control/actions', json={'action': 'set_mode', 'params': {'mode': mode}})).status_code, 400)
        for mode in ('manual', 'auto'):
            response = await self.client.post('/api/control/actions', json={'action': 'set_mode', 'params': {'mode': mode}})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json()['executed'])
        for params in ({'linear_y': .1}, {'angular_z': 1.1}):
            self.assertEqual((await self.client.post('/api/control/actions', json={'action': 'move', 'params': params})).status_code, 400)

    async def test_live_controls_only_use_authenticated_local_bridge(self):
        client = AsyncMock()
        client.post.return_value = httpx.Response(200, json={'executed': True, 'executor': 'bridge'})
        manager = Mock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=None)
        with patch.object(backend, '_CONTROL_EXECUTOR', 'bridge'), patch.object(backend.httpx, 'AsyncClient', return_value=manager) as factory:
            self.assertTrue((await backend._execute_control_action('stop', {}))['executed'])
            self.assertEqual(client.post.call_args.args[0], 'http://127.0.0.1:3001/internal/control')
            self.assertIn('X-Internal-Token', client.post.call_args.kwargs['headers'])
            self.assertFalse(factory.call_args.kwargs['trust_env'])
        with patch.object(backend, '_CONTROL_EXECUTOR', 'ros2_cli'), self.assertRaises(HTTPException):
            await backend._execute_control_action('move', {})

    async def test_tunnel_url_cannot_enable_legacy_raw_ws(self):
        with patch.dict(os.environ, {'DORI_WS_URL': 'wss://ws.evil.test', 'DORI_EXPOSE_ROSBRIDGE_TUNNEL': 'true'}):
            data = (await self.client.get('/api/tunnel-url')).json()
        self.assertEqual(data['ws_url'], 'wss://dash.test/ws/admin')
        self.assertFalse(data['ws_exposed'])

    async def call_ws(self, query='', origin='https://dash.test', upstream=None, close_client=True):
        incoming = asyncio.Queue()
        await incoming.put({'type': 'websocket.connect'})
        if close_client:
            await incoming.put({'type': 'websocket.disconnect', 'code': 1000})
        outgoing = []
        ws = WebSocket({'type': 'websocket', 'scheme': 'wss', 'path': '/ws/admin',
                        'query_string': query.encode(), 'headers': [(b'host', b'dash.test'), (b'origin', origin.encode())],
                        'server': ('dash.test', 443), 'client': ('127.0.0.1', 9999)},
                       incoming.get, AsyncMock(side_effect=outgoing.append))
        with patch.object(backend.websockets, 'connect', return_value=upstream):
            await asyncio.wait_for(backend.admin_ws_proxy(ws), 2)
        return outgoing

    async def test_ws_ticket_single_use_origin_and_no_static_query(self):
        await self.login()
        ticket = (await self.client.post('/api/auth/ws-ticket')).json()['ticket']
        class Upstream:
            def __init__(self): self.cancelled = False
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def __aiter__(self): return self
            async def __anext__(self):
                try: await asyncio.Future()
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
            async def send(self, data): pass
        upstream = Upstream()
        bad_origin = await self.call_ws(f'ticket={ticket}', origin='https://evil.test')
        self.assertEqual(bad_origin[0]['type'], 'websocket.close')
        result = await self.call_ws(f'ticket={ticket}', upstream=upstream)
        self.assertEqual(result[0]['type'], 'websocket.accept')
        self.assertTrue(upstream.cancelled)
        replay = await self.call_ws(f'ticket={ticket}')
        self.assertEqual(replay[0]['code'], 1008)
        self.assertEqual((await self.call_ws('access=emergency'))[0]['code'], 1008)
        expired = (await self.client.post('/api/auth/ws-ticket')).json()['ticket']
        record = backend._ws_tickets[expired]
        backend._ws_tickets[expired] = (time.time() - 1, record[1], record[2])
        self.assertEqual((await self.call_ws(f'ticket={expired}'))[0]['code'], 1008)

    async def test_internal_routes_are_local_and_fail_closed(self):
        for method in ('GET', 'DELETE'):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bridge.app_public), base_url='http://test') as client:
                self.assertEqual((await client.request(method, '/internal/session')).status_code, 404)
        with patch.dict(os.environ, {'DORI_INTERNAL_TOKEN': ''}):
            with self.assertRaises(HTTPException) as exc:
                require_internal_token('default-internal-secret')
            self.assertEqual(exc.exception.status_code, 503)
            with self.assertRaises(RuntimeError):
                async with backend.lifespan(backend.app):
                    pass
        with self.assertRaises(HTTPException):
            require_internal_token('default-internal-secret')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bridge.app_display), base_url='http://test') as client:
            self.assertEqual((await client.get('/internal/session')).status_code, 403)
            headers = {'X-Internal-Token': os.environ['DORI_INTERNAL_TOKEN']}
            self.assertEqual((await client.get('/internal/session', headers=headers)).status_code, 200)
            with patch.dict(os.environ, {'DORI_CONTROL_EXECUTOR': 'bridge'}), patch.object(bridge, 'ros_node', Mock()) as node:
                response = await client.post('/internal/control', headers=headers, json={'action': 'move', 'params': {'linear_y': .1}})
                self.assertEqual(response.status_code, 400)
                node.control_action.assert_not_called()


class BridgeDeadmanTests(unittest.TestCase):
    def setUp(self):
        self.node = SimpleNamespace(_control_lock=threading.RLock(), _move_command=None,
            _move_deadline=0, _action_state=0, _mode=0, pub_stop=Mock(), pub_cancel=Mock(),
            pub_manual=Mock(), pub_mode=Mock(), count_publishers=Mock(return_value=1))
        self.node.pub_manual.get_subscription_count.return_value = 1
        self.node.pub_stop.get_subscription_count.return_value = 1
        for name in ('request_stop', 'control_action', '_control_tick', '_on_mode', '_on_state'):
            setattr(self.node, name, MethodType(getattr(bridge.BridgeNode, name), self.node))

    def test_deadman_expires_without_http_activity_and_stop_wins(self):
        with patch.object(bridge.time, 'monotonic', return_value=10):
            self.node.control_action(*validate_control({'action': 'move', 'params': {'linear_x': .2}}))
        self.assertEqual(self.node._move_deadline, 10 + MOVE_TIMEOUT)
        with patch.object(bridge.time, 'monotonic', return_value=10.1):
            self.node._control_tick()
        self.assertEqual(self.node.pub_manual.publish.call_count, 2)
        with patch.object(bridge.time, 'monotonic', return_value=11):
            self.node._control_tick()
        self.node.pub_stop.publish.assert_called_once()
        self.assertTrue(self.node.pub_stop.publish.call_args.args[0].data)
        self.assertIsNone(self.node._move_command)
        with self.assertRaises(HTTPException):
            self.node.control_action(*validate_control({'action': 'move'}))
        self.node._control_tick()
        self.assertEqual(self.node.pub_manual.publish.call_count, 2)

    def test_stop_cancels_move_and_modes_match_supervisor(self):
        self.node.control_action(*validate_control({'action': 'move'}))
        self.node.request_stop()
        self.node._control_tick()
        self.node.pub_cancel.publish.assert_called_once()
        self.assertEqual(self.node.pub_manual.publish.call_count, 1)
        for mode, code in [('manual', 0), ('auto', 1)]:
            self.node.control_action('set_mode', {'mode': mode})
            self.assertEqual(self.node.pub_mode.publish.call_args.args[0].data, code)

    def test_competing_manual_publisher_and_unsafe_mode_are_rejected(self):
        self.node.count_publishers.return_value = 2
        with self.assertRaises(HTTPException):
            self.node.control_action(*validate_control({'action': 'move'}))
        self.node.pub_manual.publish.assert_not_called()
        self.node.count_publishers.return_value = 1
        self.node._mode = 1
        with self.assertRaises(HTTPException):
            self.node.control_action(*validate_control({'action': 'move'}))
        self.node._mode = 0
        self.node.control_action(*validate_control({'action': 'move'}))
        self.node.count_publishers.return_value = 2
        self.node._control_tick()
        self.node.pub_stop.publish.assert_called_once()

"""Visitor media, cancellation, and HTTP boundaries without hardware/network AI."""
import asyncio
import base64
import io
import json
import tempfile
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch
import sys
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ros2_ws/src/dori_dashboard/dori_dashboard'))
for package in ('dori_hri', 'dori_llm'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ros2_ws/src' / package))
import bridge_api as bridge
from visitor_voice import VisitorVoice, validate_audio, validate_text, MAX_TEXT_CHARS


def wav_payload(seconds=1, rate=16000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as wav:
        wav.setparams((1, 2, rate, 0, 'NONE', ''))
        wav.writeframes(b'\0\0' * int(rate * seconds))
    return dict(type='ptt_audio', audio_b64=base64.b64encode(output.getvalue()).decode(),
                format='wav_pcm16', sample_rate=16000, channels=1)


class AudioValidationTests(TestCase):
    def test_text_must_be_a_bounded_nonblank_string(self):
        self.assertEqual(validate_text({'text': '  안녕하세요\n  '}), '안녕하세요')
        self.assertEqual(validate_text({'text': '가' * MAX_TEXT_CHARS}), '가' * MAX_TEXT_CHARS)
        for value in (None, '', ' \n\t ', 123, [], {}, '가' * (MAX_TEXT_CHARS + 1)):
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(ValueError): validate_text({'text': value})

    def test_valid_and_invalid_audio(self):
        self.assertEqual(validate_audio(wav_payload(10))['sample_rate'], 16000)
        for payload in [wav_payload(.1), wav_payload(10.1), wav_payload(1, 48000),
                        {**wav_payload(), 'audio_b64': '%%%%'},
                        {**wav_payload(), 'channels': 2}]:
            with self.subTest(payload_size=len(payload['audio_b64'])):
                with self.assertRaises(ValueError): validate_audio(payload)
        payload = wav_payload()
        payload['audio_b64'] = base64.b64encode(base64.b64decode(payload['audio_b64'])[:-2]).decode()
        with self.assertRaises(ValueError): validate_audio(payload)


class VisitorAssetsTests(IsolatedAsyncioTestCase):
    async def test_gateway_leaves_shutdown_signals_with_uvicorn(self):
        manager = bridge.SessionManager()
        node = Mock(_move_command=None)
        with patch.object(bridge, 'session_manager', manager), \
             patch.object(bridge, 'ros_node', None), \
             patch.object(bridge, 'internal_token'), \
             patch.object(bridge, 'BridgeNode', return_value=node), \
             patch.object(bridge.threading, 'Thread'), \
             patch.object(bridge.rclpy, 'ok', side_effect=[False, True]), \
             patch.object(bridge.rclpy, 'init') as initialize, \
             patch.object(bridge.rclpy, 'shutdown'):
            async with bridge.public_lifespan(bridge.app_public):
                initialize.assert_called_once_with(signal_handler_options=bridge.SignalHandlerOptions.NO)
        node.destroy_node.assert_called_once()

    async def test_colcon_symlink_install_serves_assets_without_path_escape(self):
        from fastapi import FastAPI

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'web' / 'dist-visitor'
            installed = root / 'install' / 'visitor_web'
            for directory in (source / 'assets', installed / 'assets'):
                directory.mkdir(parents=True)
            files = {
                'index.html': '<script type="module" src="/assets/app.js"></script>',
                'recorder.js': '/* audio worklet */',
                'assets/app.js': 'document.body.textContent = "DORI";',
                'assets/app.css': 'body { color: green; }',
            }
            for name, content in files.items():
                (source / name).write_text(content)
                (installed / name).symlink_to(source / name)
            (installed / 'private.txt').write_text('must not be served')

            app = FastAPI()
            bridge.mount_visitor_assets(app, installed)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
                for url, name in (('/p', 'index.html'), ('/recorder.js', 'recorder.js'),
                                  ('/assets/app.js', 'assets/app.js'), ('/assets/app.css', 'assets/app.css')):
                    response = await client.get(url)
                    self.assertEqual(response.status_code, 200, url)
                    self.assertEqual(response.text, files[name])
                self.assertIn('javascript', (await client.get('/assets/app.js')).headers['content-type'])
                self.assertEqual((await client.get('/assets/missing.js')).status_code, 404)
                self.assertEqual((await client.get('/assets/%2e%2e/private.txt')).status_code, 404)


class VisitorHTTPTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = bridge.SessionManager()
        self.node = SimpleNamespace(prepare_visitor=AsyncMock(return_value=True),
                                    trigger_pairing_success=Mock(), cancel_visitor=Mock(),
                                    execute_cleanup=AsyncMock(return_value=True),
                                    voice=SimpleNamespace(media={'key': b'mp3'}))
        self.patches = [patch.object(bridge, 'session_manager', self.manager),
                        patch.object(bridge, 'nonce_manager', bridge.NonceManager()),
                        patch.object(bridge, 'pair_claim_manager', bridge.PairClaimManager()),
                        patch.object(bridge, 'ros_node', self.node)]
        for p in self.patches: p.start()
        bridge.pair_attempts.clear()
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=bridge.app_public),
                                       base_url='https://app.dgist-dori.xyz',
                                       headers={'Origin': 'https://app.dgist-dori.xyz'})

    async def asyncTearDown(self):
        await self.client.aclose()
        await self.manager._cancel_session_timers()
        if self.manager.cleanup_task:
            self.manager.cleanup_task.cancel()
            await asyncio.gather(self.manager.cleanup_task, return_exceptions=True)
        for p in reversed(self.patches): p.stop()

    async def pair(self):
        nonce = bridge.nonce_manager.generate()
        return await asyncio.wait_for(self.client.post('/api/pair', json={'nonce': nonce, 'consent': True}), 3)

    async def test_pair_cookie_and_scoped_media(self):
        response = await self.pair()
        self.assertEqual(response.status_code, 200)
        cookie = response.headers['set-cookie'].lower()
        for flag in ('secure', 'httponly', 'samesite=strict'): self.assertIn(flag, cookie)
        self.assertEqual((await self.client.get('/api/audio/key')).content, b'mp3')
        self.assertEqual((await self.client.get('/api/audio/unknown')).status_code, 404)
        await self.client.delete('/api/session')
        self.assertEqual((await self.client.get('/api/audio/key')).status_code, 401)

    async def test_origin_rate_limit_and_nonce_expiry(self):
        response = await self.client.post('/api/pair', json={}, headers={'Origin': 'https://evil.example'})
        self.assertEqual(response.status_code, 403)
        response = await self.client.post('/api/pair', json={'nonce': 'expired', 'consent': True})
        self.assertEqual(response.status_code, 410)
        bridge.pair_attempts.extend([bridge.time.monotonic()] * 30)
        self.assertEqual((await self.pair()).status_code, 429)

    async def test_oversize_pair_and_internal_routes(self):
        response = await self.client.post('/api/pair', content=b'x' * 1025)
        self.assertEqual(response.status_code, 413)
        self.assertEqual((await self.client.get('/internal/session')).status_code, 404)
        self.assertEqual((await self.client.get('/display/events')).status_code, 404)

    async def test_unsafe_profile_does_not_issue_cookie(self):
        self.node.prepare_visitor.return_value = False
        response = await self.pair()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('set-cookie', response.headers)

    async def test_readiness_failure_does_not_consume_qr(self):
        self.node.prepare_visitor.return_value = False
        nonce = bridge.nonce_manager.generate()
        for _ in range(2):
            response = await self.client.post('/api/pair', json={'nonce': nonce, 'consent': True})
            self.assertEqual(response.status_code, 503)
            self.assertTrue(bridge.nonce_manager.is_valid(nonce))
        self.node.prepare_visitor.return_value = True
        response = await self.client.post('/api/pair', json={'nonce': nonce, 'consent': True})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(bridge.nonce_manager.is_valid(nonce))

    async def test_scan_claim_survives_qr_rotation_and_failed_readiness(self):
        clock = Mock(return_value=bridge.time.time())
        with patch.object(bridge, 'time', SimpleNamespace(time=clock, monotonic=bridge.time.monotonic)):
            nonce = bridge.nonce_manager.generate()
            response = await self.client.post('/api/pair/claim', json={'nonce': nonce})
            self.assertEqual(response.status_code, 200)
            for flag in ('secure', 'httponly', 'samesite=strict'):
                self.assertIn(flag, response.headers['set-cookie'].lower())
            self.node.prepare_visitor.assert_not_awaited()
            self.node.trigger_pairing_success.assert_not_called()
            self.assertEqual(self.manager.state, bridge.SessionState.IDLE)
            self.assertIsNone(self.manager.current_token)
            clock.return_value += bridge.NONCE_TTL + bridge.NONCE_GRACE + 1
            bridge.nonce_manager.generate()
            self.assertFalse(bridge.nonce_manager.is_valid(nonce))
            self.assertEqual((await self.client.get('/api/pair/claim')).status_code, 200)
            self.assertEqual((await self.client.post('/api/pair', json={'consent': False})).status_code, 400)
            self.node.prepare_visitor.return_value = False
            for _ in range(2):
                self.assertEqual((await self.client.post('/api/pair', json={'consent': True})).status_code, 503)
            self.node.prepare_visitor.return_value = True
            self.assertEqual((await self.client.post('/api/pair', json={'consent': True})).status_code, 200)
            self.assertEqual(bridge.pair_claim_manager.claims, {})
            self.assertEqual(self.manager.state, bridge.SessionState.ACTIVE)

    async def test_claim_expiry_is_not_extended_by_reload(self):
        clock = Mock(return_value=bridge.time.time())
        with patch.object(bridge, 'time', SimpleNamespace(time=clock, monotonic=bridge.time.monotonic)):
            nonce = bridge.nonce_manager.generate()
            first = await self.client.post('/api/pair/claim', json={'nonce': nonce})
            expiry = first.json()['expires_at']
            clock.return_value += 10
            repeated = await self.client.post('/api/pair/claim', json={'nonce': nonce})
            self.assertEqual(repeated.json()['expires_at'], expiry)
            clock.return_value = expiry + 1
            self.assertEqual((await self.client.get('/api/pair/claim')).status_code, 410)
            self.assertEqual((await self.client.post('/api/pair', json={'consent': True})).status_code, 410)
            self.node.prepare_visitor.assert_not_awaited()

    async def test_claim_requires_valid_qr_origin_and_rate_budget(self):
        self.assertEqual((await self.client.post('/api/pair/claim', json={'nonce': 'expired'})).status_code, 410)
        nonce = bridge.nonce_manager.generate()
        response = await self.client.post('/api/pair/claim', json={'nonce': nonce}, headers={'Origin': 'https://evil.example'})
        self.assertEqual(response.status_code, 403)
        bridge.pair_attempts.extend([bridge.time.monotonic()] * 30)
        self.assertEqual((await self.client.post('/api/pair/claim', json={'nonce': nonce})).status_code, 429)

    async def test_rescanning_a_new_qr_replaces_the_previous_claim(self):
        clock = Mock(return_value=bridge.time.time())
        with patch.object(bridge, 'time', SimpleNamespace(time=clock, monotonic=bridge.time.monotonic)):
            first = await self.client.post('/api/pair/claim', json={'nonce': bridge.nonce_manager.generate()})
            old_token = self.client.cookies.get('dori_pair_claim')
            clock.return_value += bridge.NONCE_TTL + 1
            second = await self.client.post('/api/pair/claim', json={'nonce': bridge.nonce_manager.generate()})
            self.assertEqual(second.status_code, 200)
            self.assertGreater(second.json()['expires_at'], first.json()['expires_at'])
            self.assertNotEqual(self.client.cookies.get('dori_pair_claim'), old_token)
            self.assertIsNone(bridge.pair_claim_manager.expires_at(old_token))
            self.node.prepare_visitor.assert_not_awaited()

    async def test_competing_claims_admit_only_one_visitor(self):
        nonce = bridge.nonce_manager.generate()
        tokens = []
        for _ in range(2):
            response = bridge.Response()
            await bridge.claim_pairing(bridge.PairClaimRequest(nonce=nonce), response)
            tokens.append(response.headers['set-cookie'].split(';')[0].split('=', 1)[1])
        results = await asyncio.gather(*(
            bridge.pair_device(bridge.PairRequest(consent=True), bridge.Response(), token)
            for token in tokens
        ), return_exceptions=True)
        self.assertEqual(sum(isinstance(value, dict) for value in results), 1)
        self.assertEqual([value.status_code for value in results if isinstance(value, bridge.HTTPException)], [409])

    async def test_admin_cannot_bypass_failed_cleanup(self):
        await self.manager.start_session()
        self.node.execute_cleanup.return_value = False
        with patch.object(bridge.asyncio, 'sleep', AsyncMock()):
            self.assertFalse(await self.manager.end_session(admin_force=True))
        self.assertEqual(self.manager.state, bridge.SessionState.ENDING)
        self.assertIsNone(self.manager.current_token)

    async def test_display_qr_local_only(self):
        nonce = bridge.nonce_manager.generate()
        response = await bridge.qr_image(nonce)
        self.assertIn(b'<svg', response.body)
        await self.manager.start_session()
        with self.assertRaises(bridge.HTTPException): await bridge.qr_image(nonce)


class VoiceTurnTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = SimpleNamespace(active_ws=SimpleNamespace(send_json=AsyncMock()), main_loop=asyncio.get_running_loop())
        with patch('visitor_voice.ActionClient'):
            self.voice = VisitorVoice(Mock(create_publisher=Mock(side_effect=lambda *args: Mock())), self.manager)

    async def asyncTearDown(self):
        self.voice.cancel()
        if self.voice.task:
            self.voice.task.cancel()
            await asyncio.gather(self.voice.task, return_exceptions=True)

    async def test_cancel_before_scheduled_turn_does_not_publish_audio(self):
        self.voice.start(wav_payload())
        self.voice.cancel()
        await self.voice.task
        self.voice.audio_pub.publish.assert_not_called()

    async def test_text_skips_stt_and_shares_reply_and_motion_restrictions(self):
        self.voice.audio_pub.get_subscription_count.return_value = 0
        self.voice._action = AsyncMock(side_effect=[
            SimpleNamespace(intent='navigation', response_text='Go to library'),
            SimpleNamespace(success=True),
        ])
        self.voice.start_text({'text': '  도서관으로 안내해 주세요  '})
        with self.assertRaises(ValueError): self.voice.start_text({'text': 'second'})
        with self.assertRaises(ValueError): self.voice.start(wav_payload())
        await self.voice.task
        self.voice.audio_pub.publish.assert_not_called()
        events = [call.args[0] for call in self.manager.active_ws.send_json.call_args_list]
        self.assertEqual(events[0], {'type': 'user_text', 'data': '도서관으로 안내해 주세요'})
        self.assertNotIn('stt_text', [event['type'] for event in events])
        reply = next(event['data'] for event in events if event['type'] == 'llm_text')
        self.assertIn('이동 안내와 추종은 아직 지원하지 않아요', reply)
        calls = self.voice._action.call_args_list
        self.assertEqual(calls[0].args[2].text, '도서관으로 안내해 주세요')
        self.assertEqual(calls[1].args[2].text, reply)
        self.assertTrue(calls[1].kwargs['remote'])
        self.assertEqual(events[-1], {'type': 'robot_state', 'status': 'READY'})

    async def test_text_cannot_overlap_audio_and_cancel_prevents_dispatch(self):
        self.voice.start(wav_payload())
        with self.assertRaises(ValueError): self.voice.start_text({'text': 'hello'})
        self.voice.cancel()
        await self.voice.task
        self.voice._action = AsyncMock()
        self.voice.start_text({'text': 'not delivered'})
        self.voice.cancel()
        await self.voice.task
        self.voice._action.assert_not_awaited()
        self.manager.active_ws.send_json.assert_not_awaited()

    async def test_stale_stt_and_audio_are_discarded(self):
        self.voice.turn = 'new'
        self.voice.stt_waiter = asyncio.get_running_loop().create_future()
        self.voice._receive_stt({'request_id': 'old', 'text': 'private'})
        self.assertFalse(self.voice.stt_waiter.done())
        self.voice.audio_id = 'new-audio'
        self.voice._receive_audio({'event_type': 'remote_audio', 'id': 'old-audio', 'audio_b64': 'bXAz'})
        self.assertEqual(self.voice.media, {})
        await self.voice.emit('old', 'llm_text', data='private')
        self.manager.active_ws.send_json.assert_not_awaited()

    async def test_complete_turn_waits_for_remote_playback(self):
        release = asyncio.Event()
        async def action(turn, client, goal, remote=False):
            if remote:
                self.voice.audio_id = 'audio'
                self.voice._receive_audio({'event_type': 'remote_audio', 'id': 'audio', 'audio_b64': 'bXAz'})
                await release.wait()
                return SimpleNamespace(success=True)
            return SimpleNamespace(intent='navigation', response_text='Reply')
        self.voice._action = action
        self.voice.start(wav_payload())
        await asyncio.sleep(0)
        self.voice._receive_stt({'request_id': self.voice.turn, 'event': 'stt_result', 'text': 'hello'})
        for _ in range(5): await asyncio.sleep(0)
        self.assertTrue(self.voice.draining)
        self.assertTrue(self.voice.media)
        self.voice.playback({'id': 'wrong', 'status': 'ended'})
        self.voice.playback_pub.publish.assert_not_called()
        self.voice.playback({'id': 'audio', 'status': 'ended'})
        self.voice.playback_pub.publish.assert_called_once()
        release.set()
        await self.voice.task
        self.assertEqual(self.voice.media, {})
        types = [c.args[0]['type'] for c in self.manager.active_ws.send_json.call_args_list]
        self.assertIn('stt_text', types)
        self.assertIn('llm_text', types)
        self.assertIn('tts_audio', types)

    async def test_late_action_acceptance_is_canceled_and_drained(self):
        self.voice.turn = 'old'
        accepted = asyncio.get_running_loop().create_future()
        result = asyncio.get_running_loop().create_future()
        handle = Mock(accepted=True)
        handle.get_result_async.return_value = result
        client = Mock()
        client.send_goal_async.return_value = accepted
        task = asyncio.create_task(self.voice._action('old', client, Mock()))
        await asyncio.sleep(0)
        self.voice.cancel()
        accepted.set_result(handle)
        for _ in range(4): await asyncio.sleep(0)
        handle.cancel_goal_async.assert_called_once()
        self.assertFalse(task.done())
        result.set_result(SimpleNamespace(status=5, result=None))
        with self.assertRaises(asyncio.CancelledError): await task

class RemoteTTSTests(TestCase):
    def test_remote_action_synthesizes_and_waits_for_phone_ack(self):
        import tempfile
        import threading
        from types import MethodType
        from dori_hri.tts_node import TTSNode
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'voice.mp3'
            path.write_bytes(b'synthesized-mp3')
            goal = Mock(is_cancel_requested=False)
            goal.request.text = 'Hello'
            goal.goal_id.uuid = list(range(16))
            node = SimpleNamespace(
                _speech_lock=threading.Lock(), _remote_results={}, _remote_cancel=False,
                playback_mode='publish_only', gcp_client=None,
                _pub_speaking=Mock(), _finish_speaking=Mock(), get_logger=Mock(),
                _synthesize_gtts=Mock(return_value=str(path)),
            )
            node._play_remote = MethodType(TTSNode._play_remote, node)
            node._cleanup_temp_file = MethodType(TTSNode._cleanup_temp_file, node)
            def audio_event(kind, data):
                self.assertEqual(kind, 'remote_audio')
                self.assertEqual(base64.b64decode(data['audio_b64']), b'synthesized-mp3')
                goal.succeed.assert_not_called()
                TTSNode._on_remote_playback(node, SimpleNamespace(data=json.dumps({'id': data['id'], 'status': 'ended'})))
            node._publish_audio_event = audio_event
            with patch('dori_hri.tts_node.rclpy.ok', return_value=True), patch('dori_hri.tts_node.subprocess.Popen') as player:
                result = TTSNode.execute_callback(node, goal, remote=True)
            self.assertTrue(result.success)
            goal.succeed.assert_called_once()
            player.assert_not_called()
            self.assertFalse(path.exists())
            self.assertEqual(node._remote_results, {})

    def test_reset_refuses_busy_tts_and_llm(self):
        import threading
        from dori_hri.tts_node import TTSNode
        from dori_llm.llm_node import LLMNode
        node = SimpleNamespace(_speech_lock=threading.Lock(), _busy=True, _remote_cancel=False)
        response = SimpleNamespace()
        TTSNode._remote_reset(node, None, response)
        self.assertFalse(response.success)
        self.assertTrue(node._remote_cancel)
        llm = SimpleNamespace(_busy_lock=threading.Lock(), _busy=True, conversation_history=['old'])
        LLMNode._on_reset_history(llm, None, response)
        self.assertFalse(response.success)
        self.assertEqual(llm.conversation_history, ['old'])

class STTDrainTests(TestCase):
    def test_reset_clears_buffers_and_discards_queued_old_requests(self):
        import queue
        import importlib.util
        path = Path(__file__).resolve().parents[2] / 'ros2_ws/src/dori_hri/dori_hri/stt_node.py'
        spec = importlib.util.spec_from_file_location('stt_drain_under_test', path)
        module = importlib.util.module_from_spec(spec)
        # Only buffer/drain behavior is under test; do not load inference runtimes.
        with patch.dict(sys.modules, {
            'sounddevice': Mock(), 'openwakeword': Mock(),
            'openwakeword.model': SimpleNamespace(Model=Mock()),
            'faster_whisper': SimpleNamespace(WhisperModel=Mock()),
        }):
            spec.loader.exec_module(module)
        STTNode = module.STTNode
        node = SimpleNamespace(buffer=[b'audio'], audio_queue=queue.Queue(),
                               state='LISTENING', audio_input_mode='topic', dori_speaking=False)
        node.audio_queue.put(b'audio')
        response = SimpleNamespace()
        STTNode._reset_input(node, None, response)
        self.assertTrue(response.success)
        self.assertFalse(node.buffer)
        self.assertTrue(node.audio_queue.empty())
        # No decoder/model/logger is needed: stale queued audio must return first.
        STTNode._on_audio_input_topic(node, SimpleNamespace(data=json.dumps({'request_id': 'old', 'created_at': 0})))
        self.assertFalse(node.buffer)

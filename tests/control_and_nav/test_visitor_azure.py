"""Visitor turn integration: Azure stream ownership, cancellation and recovery."""
import asyncio
import base64
import os
from pathlib import Path
import sys
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ros2_ws/src/dori_dashboard/dori_dashboard'))
import visitor_voice as module

ID = 'a' * 32
START = dict(id=ID, format='pcm16', sample_rate=16000, channels=1)


class Session:
    def __init__(self, config, endpoint):
        self.on_endpoint = endpoint
        self.input_closed = False
        self.pcm = []
        self.done = asyncio.get_running_loop().create_future()
        self.closed = False
    async def start(self): pass
    async def result(self): return await self.done
    def write(self, data): self.pcm.append(data)
    def finish(self, reason):
        self.input_closed = True
        self.on_endpoint(reason)
    def fail(self, code):
        self.finish('error')
        self.done.set_exception(module.AzureSpeechError(code))
    def cancel(self):
        self.finish('canceled')
        self.done.cancel()
    async def close(self): self.closed = True


class VisitorAzureTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = NS(active_ws=NS(send_json=AsyncMock()), main_loop=asyncio.get_running_loop())
        with patch.dict(os.environ, {'DORI_VISITOR_STT': 'azure'}), patch.object(module, 'ActionClient'):
            self.voice = module.VisitorVoice(Mock(), self.manager)
        self.factory = patch.object(module, 'AzureSpeechStream', side_effect=Session).start()
        patch.object(module, 'load_config', return_value=object()).start()
        self.addCleanup(patch.stopall)
        self.voice._action = AsyncMock(side_effect=[NS(intent='greeting', response_text='안녕하세요'), NS(success=True)])
    async def asyncTearDown(self):
        self.voice.cancel()
        if self.voice.task: await asyncio.gather(self.voice.task, return_exceptions=True)
    async def start(self):
        self.voice.start_stream(START)
        await asyncio.sleep(0)
        return self.voice.stream
    def events(self): return [call.args[0] for call in self.manager.active_ws.send_json.call_args_list]
    def chunk(self, **kwargs):
        self.voice.stream_audio(dict(id=ID, seq=0, audio_b64=base64.b64encode(bytes(3200)).decode(), **kwargs))

    async def test_streamed_turn_uses_full_text_once_and_reuses_llm_tts_pipeline(self):
        stream = await self.start()
        self.assertIn({'type': 'stt_ready', 'id': ID}, self.events())
        self.chunk()
        self.assertEqual(stream.pcm, [bytes(3200)])
        stream.finish('azure_final')
        stream.done.set_result('잠시만요. 도서관은 어디인가요?')
        await self.voice.task
        self.assertTrue(stream.closed)
        self.assertEqual(self.voice._action.call_args_list[0].args[2].text, '잠시만요. 도서관은 어디인가요?')
        self.assertEqual(sum(e['type'] == 'stt_text' for e in self.events()), 1)
        self.assertIn({'type': 'llm_text', 'data': '안녕하세요'}, self.events())
        self.assertIsNone(self.voice.stream_id)
        self.voice.audio_pub.publish.assert_not_called()

    async def test_wrong_sequence_fails_turn_and_next_text_turn_recovers(self):
        stream = await self.start()
        self.voice.stream_audio(dict(id=ID, seq=3, audio_b64='AAAA'))
        await self.voice.task
        self.assertFalse(stream.pcm)
        self.assertIn('stt_invalid_audio', [e.get('code') for e in self.events()])
        self.voice._action.assert_not_awaited()
        self.voice.start_text({'text': '안녕'})
        await self.voice.task
        self.assertIn({'type': 'llm_text', 'data': '안녕하세요'}, self.events())

    async def test_stale_ids_cannot_feed_or_close_current_stream(self):
        stream = await self.start()
        self.voice.stream_audio(dict(id='old', seq=0, audio_b64='AAAA'))
        self.voice.finish_stream(dict(id='old', seq=0))
        self.voice.cancel_stream(dict(id='old'))
        self.assertFalse(stream.pcm)
        self.assertFalse(stream.input_closed)
        self.assertEqual(self.voice.stream_id, ID)

    async def test_cancel_before_start_does_not_open_cloud_session(self):
        self.voice.start_stream(START)
        self.voice.cancel()
        await self.voice.task
        self.factory.assert_not_called()
        self.voice._action.assert_not_awaited()

    async def test_cancelled_turn_does_not_forward_text_or_late_ui_events(self):
        stream = await self.start()
        before = len(self.events())
        self.voice.cancel()
        await self.voice.task
        self.assertTrue(stream.closed)
        self.assertEqual(len(self.events()), before)
        self.voice._action.assert_not_awaited()

    async def test_manual_finish_is_correlated_and_legacy_upload_is_rejected(self):
        stream = await self.start()
        self.chunk()
        self.voice.finish_stream(dict(id=ID, seq=1))
        self.assertTrue(stream.input_closed)
        stream.done.set_result('안녕')
        await self.voice.task
        with self.assertRaises(ValueError): self.voice.start({})

    async def test_pairing_cleanup_does_not_require_disabled_whisper(self):
        from bridge_api import BridgeNode
        def client():
            future = NS(result=lambda: NS(success=True))
            future.add_done_callback = lambda cb: cb(future)
            return NS(service_is_ready=lambda: True, call_async=lambda _: future)
        node = NS(cancel_visitor=Mock(), voice=NS(draining=False, provider='azure'),
            cli_llm_reset=client(), cli_bt_clear=client(), cli_tts_reset=client(),
            cli_stt_reset=Mock())
        self.assertTrue(await BridgeNode.execute_cleanup(node))
        node.cli_stt_reset.service_is_ready.assert_not_called()

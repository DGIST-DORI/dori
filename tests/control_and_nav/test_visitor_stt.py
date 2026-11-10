"""Phone speech endpoint result handling; no microphone, model or ROS graph needed."""
import asyncio
import importlib.util
import json
import math
import base64
import io
import wave
import sys
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'ros2_ws/src/dori_dashboard/dori_dashboard'))
from visitor_voice import VisitorVoice


def load_stt():
    spec = importlib.util.spec_from_file_location('visitor_stt_under_test', ROOT / 'ros2_ws/src/dori_hri/dori_hri/stt_node.py')
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        'sounddevice': Mock(), 'openwakeword': Mock(),
        'openwakeword.model': SimpleNamespace(Model=Mock()),
        'faster_whisper': SimpleNamespace(WhisperModel=Mock()),
    }):
        spec.loader.exec_module(module)
    return module.STTNode


class TranscriptionTests(TestCase):
    def setUp(self):
        cls = load_stt()
        self.node = SimpleNamespace(
            buffer=[np.zeros(16000, dtype=np.float32)], min_confidence=.55,
            visitor_min_confidence=.4, whisper=Mock(), get_logger=Mock(),
            visitor_result_pub=Mock(), result_pub=Mock(),
            audio_input_mode='topic', dori_speaking=False, _input_epoch=1,
        )
        for name in ('_transcribe', '_on_audio_input_topic', '_publish_stt_error'):
            setattr(self.node, name, MethodType(getattr(cls, name), self.node))

    def result(self, confidence=.46, no_speech_prob=.01, text='안녕'):
        segment = SimpleNamespace(text=text, avg_logprob=math.log(confidence), no_speech_prob=no_speech_prob)
        self.node.whisper.transcribe.return_value = (iter([segment]), SimpleNamespace(language='ko'))

    def published(self, visitor=True):
        publisher = self.node.visitor_result_pub if visitor else self.node.result_pub
        return json.loads(publisher.publish.call_args.args[0].data)

    def test_observed_short_greeting_is_accepted_for_phone_only(self):
        self.result()
        self.node._transcribe(request_id='phone')
        self.assertEqual(self.published()['event'], 'stt_result')
        self.assertEqual(self.published()['text'], '안녕')
        self.assertEqual(self.published()['request_id'], 'phone')
        options = self.node.whisper.transcribe.call_args.kwargs
        self.assertTrue(options['vad_filter'])
        self.assertEqual(options['beam_size'], 1)
        self.assertTrue(options['without_timestamps'])
        self.assertIsNone(options['language'])
        self.node.result_pub.publish.assert_not_called()
        self.result()
        self.node._transcribe()
        self.assertEqual(self.published(visitor=False)['event'], 'stt_empty_or_low_conf')
        self.assertEqual(self.node.whisper.transcribe.call_args.kwargs['beam_size'], 5)

    def test_unclear_and_silence_hallucinations_remain_rejected(self):
        for confidence, no_speech, text in [(.3, .01, '안녕'), (.8, .9, '구독해 주세요'), (.8, .01, '')]:
            with self.subTest(confidence=confidence, no_speech=no_speech):
                self.result(confidence, no_speech, text)
                self.node._transcribe(request_id='phone')
                self.assertEqual(self.published()['event'], 'stt_empty_or_low_conf')

    def test_decoder_failure_returns_correlated_error_without_timeout(self):
        def segments():
            raise RuntimeError('decoder failed')
            yield  # Whisper decodes lazily while iterating.
        self.node.whisper.transcribe.return_value = (segments(), SimpleNamespace(language='ko'))
        self.node._transcribe(request_id='phone')
        self.assertEqual(self.published()['event'], 'stt_error')
        self.assertEqual(self.published()['code'], 'stt_failed')
        self.assertEqual(self.published()['request_id'], 'phone')

    def test_bad_input_and_busy_report_errors_but_stale_requests_are_dropped(self):
        for payload in ({'format': 'mp3'}, {'format': 'wav_pcm16', 'audio_b64': '%%%%'}):
            self.node._on_audio_input_topic(SimpleNamespace(data=json.dumps({**payload, 'request_id': 'phone', 'created_at': 2})))
            self.assertEqual(self.published()['code'], 'stt_invalid_audio')
            self.assertFalse(self.node.buffer)
        self.node.dori_speaking = True
        self.node._on_audio_input_topic(SimpleNamespace(data=json.dumps({'request_id': 'phone', 'created_at': 2})))
        self.assertEqual(self.published()['code'], 'stt_busy')
        self.node.visitor_result_pub.reset_mock()
        self.node._on_audio_input_topic(SimpleNamespace(data=json.dumps({'request_id': 'old', 'created_at': 0})))
        self.node.visitor_result_pub.publish.assert_not_called()
        self.node.whisper.transcribe.assert_not_called()

    def test_long_phone_wav_reaches_transcription_without_truncation(self):
        output = io.BytesIO()
        with wave.open(output, 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', ''))
            wav.writeframes(b'\0\0' * 16000 * 120)
        captured = []
        self.node._transcribe = lambda **kw: captured.append((len(self.node.buffer[0]), kw))
        payload = {'request_id': 'long-phone', 'created_at': 2, 'format': 'wav_pcm16',
                   'audio_b64': base64.b64encode(output.getvalue()).decode()}
        self.node._on_audio_input_topic(SimpleNamespace(data=json.dumps(payload)))
        self.assertEqual(captured, [(16000 * 120, {'request_id': 'long-phone'})])
        self.assertFalse(self.node.buffer)


class TurnFailureTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.manager = SimpleNamespace(active_ws=SimpleNamespace(send_json=AsyncMock()), main_loop=asyncio.get_running_loop())
        with patch('visitor_voice.ActionClient'):
            self.voice = VisitorVoice(Mock(), self.manager)
        self.voice._action = AsyncMock(side_effect=[SimpleNamespace(intent='greeting', response_text='안녕하세요'), SimpleNamespace(success=True)])

    def events(self):
        return [call.args[0] for call in self.manager.active_ws.send_json.call_args_list]

    async def test_stt_failure_releases_turn_and_allows_next_text_turn(self):
        for event, code in [('stt_empty_or_low_conf', 'stt_unclear'), ('stt_error', 'stt_failed')]:
            self.manager.active_ws.send_json.reset_mock()
            self.voice._start_turn(audio={})
            await asyncio.sleep(0)
            self.voice._receive_stt({'request_id': self.voice.turn, 'event': event, 'text': ''})
            await self.voice.task
            error = next(e for e in self.events() if e['type'] == 'error')
            self.assertEqual(error['code'], code)
            self.assertIn('텍스트', error['message'])
            self.assertEqual(self.events()[-1], {'type': 'robot_state', 'status': 'READY'})
            self.assertIsNone(self.voice.turn)
            self.voice._action.assert_not_awaited()
        self.voice.start_text({'text': '안녕'})
        await self.voice.task
        self.assertIn({'type': 'llm_text', 'data': '안녕하세요'}, self.events())

    async def test_recognition_timeout_is_identified(self):
        self.voice.turn = 'phone'
        with patch('visitor_voice.asyncio.wait_for', AsyncMock(side_effect=asyncio.TimeoutError)):
            await self.voice._run('phone', audio={})
        error = next(e for e in self.events() if e['type'] == 'error')
        self.assertEqual(error['code'], 'stt_timeout')
        self.voice._action.assert_not_awaited()

    async def test_reply_and_playback_errors_are_distinguished(self):
        for responses, code in [([RuntimeError('llm unavailable')], 'llm_failed'),
                                ([SimpleNamespace(intent='greeting', response_text='안녕하세요'), SimpleNamespace(success=False)], 'tts_failed')]:
            self.manager.active_ws.send_json.reset_mock()
            self.voice._action = AsyncMock(side_effect=responses)
            self.voice.start_text({'text': '안녕'})
            await self.voice.task
            error = next(e for e in self.events() if e['type'] == 'error')
            self.assertEqual(error['code'], code)
            if code == 'tts_failed':
                self.assertIn({'type': 'llm_text', 'data': '안녕하세요'}, self.events())

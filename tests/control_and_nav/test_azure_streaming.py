"""Production Azure session lifecycle with native-thread callback simulation."""
import asyncio
import os
import math
import struct
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'ros2_ws/src/dori_dashboard/dori_dashboard'))
from azure_speech import AzureConfig, AzureSpeechError, AzureSpeechStream, load_config, MAX_SECONDS


def speech_chunk():
    return b''.join(struct.pack('<h', int(3000 * math.sin(2 * math.pi * 220 * i / 16000))) for i in range(1600))


class Signal:
    def __init__(self): self.handlers = []
    def connect(self, callback): self.handlers.append(callback)
    def disconnect_all(self): self.handlers.clear()
    def emit(self, event=None):
        for handler in self.handlers[:]: handler(event)


class SDK:
    PropertyId = NS(SpeechServiceConnection_LanguageIdMode='lid',
        SpeechServiceConnection_InitialSilenceTimeoutMs='initial', SpeechServiceConnection_EnableAudioLogging='logging')
    ResultReason = NS(RecognizedSpeech='speech', NoMatch='no_match')
    CancellationReason = NS(Error='error')
    def __init__(self):
        self.properties, self.writes, self.stops = {}, [], 0
        self.closed = False
        self.gate = None
        self.suffix = None
        self.audio = NS(AudioStreamFormat=lambda **kw: kw, PushAudioInputStream=lambda **kw: self,
                        AudioConfig=lambda **kw: kw)
        self.languageconfig = NS(AutoDetectSourceLanguageConfig=lambda **kw: kw)
        self.recognized, self.canceled, self.session_stopped = Signal(), Signal(), Signal()
    def SpeechConfig(self, **kw): return NS(set_property=self.properties.__setitem__)
    def SpeechRecognizer(self, **kw): return self
    def AutoDetectSourceLanguageResult(self, result): return NS(language='ko-KR')
    def start_continuous_recognition_async(self):
        return NS(get=lambda: self.gate.wait(2) if self.gate else None)
    def stop_continuous_recognition_async(self):
        def stop(): self.stops += 1
        return NS(get=stop)
    def final(self, text, offset=0):
        self.recognized.emit(NS(result=NS(reason='speech', text=text, offset=offset, duration=1000000)))
    def write(self, pcm): self.writes.append(pcm)
    def close(self):
        if self.closed: return
        self.closed = True
        if self.suffix: self.final(self.suffix, 2000000)
        self.canceled.emit(NS(cancellation_details=NS(reason='eof')))
        self.session_stopped.emit()


class StreamingTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sdk, self.endpoints = SDK(), []
        self.stream = AzureSpeechStream(AzureConfig('private-key', 'koreacentral'), self.endpoints.append, sdk=self.sdk)
    async def asyncTearDown(self): await self.stream.close()

    async def test_finals_keep_capture_open_and_drain_all_segments_at_silence(self):
        await self.stream.start()
        self.stream.write(bytes(3200))
        self.sdk.suffix = '도서관은 어디인가요?'
        await asyncio.to_thread(self.sdk.final, '잠시만요.')
        await asyncio.sleep(0)
        self.assertFalse(self.stream.input_closed)
        for _ in range(120): self.stream.write(speech_chunk())
        self.assertFalse(self.stream.input_closed)
        for _ in range(15): self.stream.write(bytes(3200))
        self.assertEqual(await self.stream.result(), '잠시만요. 도서관은 어디인가요?')
        self.assertEqual(self.endpoints, ['speech_end'])
        self.stream.write(bytes(3200))
        self.assertEqual(len(self.sdk.writes), 136)
        self.assertEqual(self.sdk.properties, {'lid': 'AtStart', 'initial': '8000', 'logging': 'false'})

    async def test_cancel_during_native_start_never_accepts_late_text(self):
        self.sdk.gate = threading.Event()
        starting = asyncio.create_task(self.stream.start())
        await asyncio.sleep(.01)
        self.stream.cancel()
        self.sdk.gate.set()
        with self.assertRaises(asyncio.CancelledError): await starting
        await asyncio.to_thread(self.sdk.final, '취소된 답변')
        with self.assertRaises(asyncio.CancelledError): await self.stream.result()
        self.assertFalse(self.stream.segments)

    async def test_provider_failure_never_exposes_error_details(self):
        await self.stream.start()
        self.sdk.canceled.emit(NS(cancellation_details=NS(reason='error', error_details='private-key')))
        with self.assertRaisesRegex(AzureSpeechError, '^stt_failed$'):
            await self.stream.result()

    async def test_no_match_does_not_close_input_but_initial_silence_does(self):
        await self.stream.start()
        self.sdk.recognized.emit(NS(result=NS(reason='no_match')))
        await asyncio.sleep(0)
        self.assertFalse(self.stream.input_closed)
        for _ in range(80): self.stream.write(bytes(3200))
        with self.assertRaisesRegex(AzureSpeechError, 'stt_unclear'):
            await self.stream.result()
        self.assertEqual(self.endpoints, ['error'])

    async def test_missing_phone_frames_abort_without_waiting_for_speech_endpoint(self):
        await self.stream.start()
        with self.assertRaisesRegex(AzureSpeechError, 'stt_interrupted'):
            await self.stream.result()
        self.assertTrue(self.sdk.closed)

    async def test_invalid_pcm_does_not_reach_sdk(self):
        await self.stream.start()
        self.stream.write(b'odd')
        with self.assertRaisesRegex(AzureSpeechError, 'stt_invalid_audio'):
            await self.stream.result()
        self.assertFalse(self.sdk.writes)

    async def test_audio_budget_closes_stream_without_silence_detection(self):
        await self.stream.start()
        self.sdk.suffix = '긴 발화'
        for _ in range(MAX_SECONDS * 10): self.stream.write(speech_chunk())
        self.assertEqual(await self.stream.result(), '긴 발화')
        self.assertEqual(self.endpoints, ['limit'])
        self.stream.write(bytes(3200))
        self.assertEqual(len(self.sdk.writes), MAX_SECONDS * 10)

    async def test_late_callbacks_after_disposal_are_ignored(self):
        await self.stream.start()
        callbacks = self.sdk.recognized.handlers[:]
        self.stream.cancel()
        await self.stream.close()
        callbacks[0](NS(result=NS(reason='speech', text='늦은 결과', offset=0, duration=1)))
        await asyncio.sleep(0)
        self.assertFalse(self.stream.segments)
        self.assertFalse(self.sdk.recognized.handlers)


class ConfigTests(TestCase):
    def test_private_file_is_data_and_requires_explicit_f0(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'azure.env'
            with patch.dict(os.environ, {'DORI_AZURE_ENV_FILE': str(config),
                'AZURE_SPEECH_KEY': '', 'AZURE_SPEECH_REGION': '', 'AZURE_SPEECH_TIER': ''}):
                config.write_text('AZURE_SPEECH_KEY="private-key"\nAZURE_SPEECH_REGION=koreacentral\nAZURE_SPEECH_TIER=S0\n')
                with self.assertRaisesRegex(AzureSpeechError, '^stt_unavailable$'): load_config()
                config.write_text(config.read_text().replace('S0', 'F0'))
                loaded = load_config()
                self.assertEqual(loaded.key, 'private-key')
                self.assertNotIn('private-key', repr(loaded))

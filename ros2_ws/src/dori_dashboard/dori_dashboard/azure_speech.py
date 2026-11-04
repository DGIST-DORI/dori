"""Per-turn Azure PCM streaming. Credentials and provider errors stay on the server."""
import asyncio
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shlex

MAX_SECONDS = 10
MAX_PCM_BYTES = 16000 * 2 * MAX_SECONDS
MAX_CHUNK_BYTES = 8000


class AzureSpeechError(ValueError):
    def __init__(self, code='stt_failed'):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class AzureConfig:
    key: str = field(repr=False)
    region: str
    languages: tuple = ('ko-KR', 'en-US')


def load_config():
    root = Path(os.environ.get('DORI_WS', Path(__file__).resolve().parents[4]))
    path = Path(os.environ.get('DORI_AZURE_ENV_FILE', root / '.state/voice/azure.env'))
    names = ('AZURE_SPEECH_KEY', 'AZURE_SPEECH_REGION', 'AZURE_SPEECH_TIER')
    values = {}
    try:
        if path.is_file():
            for line in path.read_text().splitlines():
                name, separator, value = line.strip().removeprefix('export ').partition('=')
                if separator and name.strip() in names:
                    parts = shlex.split(value, comments=True)
                    if len(parts) > 1:
                        raise ValueError()
                    values[name.strip()] = parts[0] if parts else ''
        for name in names:
            if os.environ.get(name, '').strip():
                values[name] = os.environ[name].strip()
        key, region = values.get(names[0], ''), values.get(names[1], '')
        if values.get(names[2]) != 'F0' or not key or any(c.isspace() for c in key):
            raise ValueError()
        if not re.fullmatch(r'[a-z][a-z0-9]{1,39}', region):
            raise ValueError()
    except (ValueError, OSError):
        raise AzureSpeechError('stt_unavailable') from None
    return AzureConfig(key, region)


class AzureSpeechStream:
    """All state/callback delivery belongs to the owning asyncio loop.

    Azure's first final stops input. Already-buffered final segments are drained
    before returning one text turn. A manual finish/ten-second cap may also close
    input; there is no client silence endpoint or paid language-ID fallback.
    """
    def __init__(self, config, on_endpoint, *, sdk=None):
        self.config, self.on_endpoint = config, on_endpoint
        if sdk is None:
            try:
                import azure.cognitiveservices.speech as sdk
            except ImportError:
                raise AzureSpeechError('stt_unavailable') from None
        self.sdk = sdk
        self.loop = asyncio.get_running_loop()
        self.completed = self.loop.create_future()
        self.endpoint = asyncio.Event()
        self.segments = {}
        self.recognizer = self.stream = self.opening = None
        self.signals = []
        self.input_closed = self.canceled = self.closed = False
        self.ready = False
        self.bytes_received = 0
        self.limit_timer = self.idle_timer = None

    def _open(self):
        try:
            sdk = self.sdk
            config = sdk.SpeechConfig(subscription=self.config.key, region=self.config.region)
            config.set_property(sdk.PropertyId.SpeechServiceConnection_LanguageIdMode, 'AtStart')
            config.set_property(sdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, '5000')
            config.set_property(sdk.PropertyId.SpeechServiceConnection_EnableAudioLogging, 'false')
            self.stream = sdk.audio.PushAudioInputStream(stream_format=sdk.audio.AudioStreamFormat(
                samples_per_second=16000, bits_per_sample=16, channels=1))
            self.recognizer = sdk.SpeechRecognizer(speech_config=config,
                audio_config=sdk.audio.AudioConfig(stream=self.stream),
                auto_detect_source_language_config=sdk.languageconfig.AutoDetectSourceLanguageConfig(
                    languages=self.config.languages))
            for name in ('recognized', 'canceled', 'session_stopped'):
                signal = getattr(self.recognizer, name)
                def receive(event, kind=name):
                    if not self.loop.is_closed():
                        self.loop.call_soon_threadsafe(self._receive, kind, event)
                signal.connect(receive)
                self.signals.append(signal)
            self.recognizer.start_continuous_recognition_async().get()
        except Exception:
            raise AzureSpeechError('stt_unavailable') from None

    async def start(self):
        self.opening = asyncio.create_task(asyncio.to_thread(self._open))
        try:
            await asyncio.wait_for(asyncio.shield(self.opening), 8)
        except asyncio.TimeoutError:
            raise AzureSpeechError('stt_timeout') from None
        if self.canceled:
            raise asyncio.CancelledError()
        self.ready = True
        if not self.input_closed:
            self.limit_timer = self.loop.call_later(MAX_SECONDS, self.finish, 'limit')
            self._reset_idle()

    def _reset_idle(self):
        if self.idle_timer:
            self.idle_timer.cancel()
        self.idle_timer = self.loop.call_later(3, self.fail, 'stt_interrupted')

    def write(self, pcm):
        if self.input_closed or self.canceled:
            return  # In-flight frames after the service endpoint are harmless.
        if not self.ready or not isinstance(pcm, bytes) or not 0 < len(pcm) <= MAX_CHUNK_BYTES or len(pcm) % 2:
            self.fail('stt_invalid_audio')
            return
        if self.bytes_received + len(pcm) > MAX_PCM_BYTES:
            self.fail('stt_invalid_audio')
            return
        self.bytes_received += len(pcm)
        try:
            self.stream.write(pcm)
        except Exception:
            self.fail('stt_failed')
            return
        self._reset_idle()
        if self.bytes_received == MAX_PCM_BYTES:
            self.finish('limit')

    def finish(self, reason='manual'):
        if self.input_closed:
            return
        self.input_closed = True
        for timer in (self.limit_timer, self.idle_timer):
            if timer:
                timer.cancel()
        if self.stream:
            try:
                self.stream.close()
            except Exception:
                if not self.completed.done():
                    self.completed.set_result({'error': 'stt_failed'})
        self.endpoint.set()
        self.on_endpoint(reason)

    def fail(self, code):
        if not self.completed.done():
            self.completed.set_result({'error': code})
        self.finish('error')

    def cancel(self):
        self.canceled = True
        self.finish('canceled')
        if not self.completed.done():
            self.completed.set_result({'error': 'canceled'})

    def _receive(self, kind, event):
        if self.closed or self.canceled:
            return
        try:
            if kind == 'recognized':
                result = event.result
                if result.reason == self.sdk.ResultReason.RecognizedSpeech and result.text.strip():
                    language = self.sdk.AutoDetectSourceLanguageResult(result).language
                    self.segments[(result.offset, result.duration)] = (result.text.strip(), language)
                    self.finish('azure_final')
                elif result.reason == self.sdk.ResultReason.NoMatch:
                    self.finish('azure_no_match')
            elif kind == 'canceled' and event.cancellation_details.reason == self.sdk.CancellationReason.Error:
                self.fail('stt_failed')
            elif kind in ('session_stopped', 'canceled'):
                if not self.input_closed:
                    self.fail('stt_interrupted')
                elif not self.completed.done():
                    self.completed.set_result({'text': ' '.join(self.segments[key][0] for key in sorted(self.segments))})
        except Exception:
            self.fail('stt_failed')

    async def result(self):
        try:
            await asyncio.wait_for(self.endpoint.wait(), MAX_SECONDS + 1)
            result = await asyncio.wait_for(asyncio.shield(self.completed), 8)
        except asyncio.TimeoutError:
            self.fail('stt_timeout')
            raise AzureSpeechError('stt_timeout') from None
        if self.canceled:
            raise asyncio.CancelledError()
        if result.get('error'):
            raise AzureSpeechError(result['error'])
        if not result.get('text'):
            raise AzureSpeechError('stt_unclear')
        return result['text']

    async def close(self):
        self.finish('closed')
        self.closed = True
        # Keep the turn's drain barrier until native start/stop have completed.
        if self.opening:
            await asyncio.gather(asyncio.shield(self.opening), return_exceptions=True)
        def dispose():
            for signal in self.signals:
                signal.disconnect_all()
            if self.stream:
                self.stream.close()
            if self.recognizer:
                self.recognizer.stop_continuous_recognition_async().get()
        try:
            await asyncio.to_thread(dispose)
        except Exception:
            raise AzureSpeechError('stt_failed') from None

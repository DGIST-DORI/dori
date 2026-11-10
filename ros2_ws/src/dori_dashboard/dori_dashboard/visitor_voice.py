"""Bounded visitor voice turns. ROS action UUIDs identify work, never users."""
import asyncio
import base64
import io
import json
import secrets
import wave
import time
import os
import re

try:
    from .azure_speech import AzureSpeechStream, AzureSpeechError, load_config, MAX_CHUNK_BYTES, MAX_SECONDS
except ImportError:
    from azure_speech import AzureSpeechStream, AzureSpeechError, load_config, MAX_CHUNK_BYTES, MAX_SECONDS

from rclpy.action import ActionClient
from dori_msgs.action import LLMQuery, Speak, NavigateNamed
from std_msgs.msg import String
from unique_identifier_msgs.msg import UUID

MAX_AUDIO_BYTES = 44 + 16000 * 2 * MAX_SECONDS
MAX_ENCODED_AUDIO = (MAX_AUDIO_BYTES + 2) // 3 * 4
MAX_TEXT_CHARS = 1000


class VoiceTurnError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def validate_text(data):
    text = data.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
        raise ValueError('메시지를 1~1,000자 이내로 입력해 주세요.')
    return text.strip()


def validate_audio(data):
    if (data.get('format'), data.get('sample_rate'), data.get('channels')) != ('wav_pcm16', 16000, 1):
        raise ValueError('Expected 16kHz mono PCM16 WAV')
    encoded = data.get('audio_b64')
    if not isinstance(encoded, str) or len(encoded) > MAX_ENCODED_AUDIO:
        raise ValueError('Audio exceeds 120 seconds')
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_AUDIO_BYTES:
            raise ValueError('Audio exceeds limit')
        with wave.open(io.BytesIO(raw), 'rb') as wav:
            n = wav.getnframes()
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getcomptype()) != (16000, 1, 2, 'NONE'):
                raise ValueError('Invalid WAV format')
            if not 8000 <= n <= 16000 * MAX_SECONDS or len(wav.readframes(n)) != n * 2:
                raise ValueError('Audio must contain 0.5 to 120 seconds')
    except (wave.Error, EOFError, base64.binascii.Error) as exc:
        raise ValueError('Invalid WAV') from exc
    return {k: data[k] for k in ('audio_b64', 'format', 'sample_rate', 'channels')}


async def ros_future(future):
    loop = asyncio.get_running_loop()
    result = loop.create_future()
    def done(f):
        def deliver():
            if not result.done():
                try:
                    result.set_result(f.result())
                except Exception as exc:
                    result.set_exception(exc)
        loop.call_soon_threadsafe(deliver)
    future.add_done_callback(done)
    return await result


class VisitorVoice:
    def __init__(self, node, manager):
        self.node, self.manager = node, manager
        self.turn = None
        self.task = None
        self.stt_waiter = None
        self.goal = None
        self.navigation_id = self.navigation_task = self.navigation_goal = None
        self.navigation = {'status': 'IDLE'}
        self.response_stop_requested = False
        self.audio_id = None
        self.media = {}
        self.provider = os.environ.get('DORI_VISITOR_STT', 'whisper')
        if self.provider not in ('azure', 'whisper'):
            raise ValueError('DORI_VISITOR_STT must be azure or whisper')
        self.stream = self.stream_id = None
        self.stream_sequence = 0
        self.llm = ActionClient(node, LLMQuery, 'llm/query')
        self.tts = ActionClient(node, Speak, 'tts/speak_remote')
        self.nav = ActionClient(node, NavigateNamed, 'nav/navigate_named')
        self.audio_pub = node.create_publisher(String, 'stt/audio_input', 1)
        self.playback_pub = node.create_publisher(String, 'tts/remote_playback', 10)
        node.create_subscription(String, 'stt/visitor_result', self._stt, 10)
        node.create_subscription(String, 'tts/audio_event', self._audio, 10)

    def _dispatch(self, callback, msg):
        try:
            data = json.loads(msg.data)
            if isinstance(data, dict) and self.manager.main_loop:
                self.manager.main_loop.call_soon_threadsafe(callback, data)
        except ValueError:
            pass

    def _stt(self, msg):
        self._dispatch(self._receive_stt, msg)

    def _receive_stt(self, data):
        if self.turn and data.get('request_id') == self.turn and self.stt_waiter and not self.stt_waiter.done():
            self.stt_waiter.set_result(data)

    def _audio(self, msg):
        self._dispatch(self._receive_audio, msg)

    def _receive_audio(self, data):
        if not self.turn or data.get('event_type') != 'remote_audio' or data.get('id') != self.audio_id:
            return
        try:
            raw = base64.b64decode(data['audio_b64'], validate=True)
            if not 0 < len(raw) <= 4 * 1024 * 1024:
                return
        except (KeyError, ValueError):
            return
        key = secrets.token_urlsafe(24)
        self.media = {key: raw}
        asyncio.create_task(self.emit(self.turn, 'tts_audio', id=self.audio_id, url=f'/api/audio/{key}'))

    async def emit(self, turn, kind, **data):
        if turn == self.turn and self.manager.active_ws:
            try:
                await self.manager.active_ws.send_json({'type': kind, **data})
            except (RuntimeError, ConnectionError):
                pass  # The WS owner handles disconnect and cancels this turn.

    @property
    def draining(self):
        return self.conversation_busy or self.navigation_busy

    @property
    def conversation_busy(self):
        return self.task is not None and not self.task.done()

    @property
    def navigation_busy(self):
        return self.navigation_task is not None and not self.navigation_task.done()

    def start(self, payload):
        if self.provider == 'azure':
            raise ValueError('새 음성 연결을 사용하려면 페이지를 새로고침해 주세요.')
        audio = validate_audio(payload)
        self._start_turn(audio=audio)

    def start_stream(self, payload):
        stream_id = payload.get('id')
        if self.provider != 'azure':
            raise ValueError('실시간 음성 서비스가 준비되지 않았습니다.')
        if (not isinstance(stream_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}', stream_id)
                or (payload.get('format'), payload.get('sample_rate'), payload.get('channels')) != ('pcm16', 16000, 1)):
            raise ValueError('음성 연결 형식이 올바르지 않습니다.')
        self._start_turn(stream_id=stream_id)

    def stream_audio(self, payload):
        if not self.turn or payload.get('id') != self.stream_id:
            return
        stream = self.stream
        if not stream or stream.input_closed:
            return
        try:
            if type(payload.get('seq')) is not int or payload['seq'] != self.stream_sequence:
                raise ValueError()
            encoded = payload.get('audio_b64')
            if not isinstance(encoded, str) or len(encoded) > (MAX_CHUNK_BYTES + 2) // 3 * 4:
                raise ValueError()
            pcm = base64.b64decode(encoded, validate=True)
        except ValueError:
            stream.fail('stt_invalid_audio')
            return
        self.stream_sequence += 1
        stream.write(pcm)

    def finish_stream(self, payload):
        if self.turn and payload.get('id') == self.stream_id and self.stream:
            if type(payload.get('seq')) is not int or payload['seq'] != self.stream_sequence:
                self.stream.fail('stt_invalid_audio')
            else:
                self.stream.finish('manual')

    def cancel_stream(self, payload):
        if self.turn and payload.get('id') == self.stream_id:
            self.cancel_response()

    def start_text(self, payload):
        self._start_turn(text=validate_text(payload))

    def start_navigation(self, payload):
        if self.navigation_busy:
            raise ValueError('길안내 중입니다. 목적지를 바꾸려면 길안내를 먼저 중지해 주세요.')
        identifier = payload.get('destination_id')
        matches = [g for g in self.node.destinations if g['id'] == identifier]
        if not isinstance(identifier, str) or len(matches) != 1:
            raise ValueError('현재 지도에서 목적지를 찾을 수 없습니다. 목록에서 다시 선택해 주세요.')
        if not self.nav.server_is_ready():
            raise ValueError('길안내 서비스가 아직 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.')
        self._start_turn(destination=dict(matches[0]))

    def _start_turn(self, audio=None, text=None, stream_id=None, destination=None):
        if self.conversation_busy:
            raise ValueError('이전 답변을 처리 중입니다. 잠시 후 보내 주세요.')
        if ((destination is None and not self.llm.server_is_ready()) or not self.tts.server_is_ready()
                or (audio is not None and not self.audio_pub.get_subscription_count())):
            raise ValueError('대화 서비스가 아직 준비되지 않았습니다.')
        self.turn = secrets.token_hex(16)
        self.response_stop_requested = False
        self.stream_id, self.stream_sequence = stream_id, 0
        self.task = asyncio.create_task(self._run(
            self.turn, audio=audio, text=text, stream_id=stream_id, destination=destination))

    def cancel(self):
        self.cancel_response()
        self.cancel_navigation()

    def cancel_response(self, *, notify=False):
        self.response_stop_requested = notify
        self.turn = None
        self.media.clear()
        self.audio_id = None
        if self.stream:
            self.stream.cancel()
        if self.goal:
            self.goal.cancel_goal_async()
        if self.stt_waiter and not self.stt_waiter.done():
            self.stt_waiter.cancel()

    def cancel_navigation(self):
        self.navigation_id = None
        if self.navigation_goal:
            self.navigation_goal.cancel_goal_async()
        if self.navigation_busy:
            self.navigation = {**self.navigation, 'status': 'STOPPING'}
        else:
            self.navigation = {'status': 'IDLE'}

    def playback(self, data):
        if self.turn and data.get('id') == self.audio_id and data.get('status') in ('ended', 'failed', 'canceled'):
            self.playback_pub.publish(String(data=json.dumps({'id': self.audio_id, 'status': data['status']})))
            self.media.clear()

    async def _action(self, turn, client, goal, remote=False, timeout=100, on_accepted=None, navigation=False):
        def current():
            return turn == (self.navigation_id if navigation else self.turn)
        if not current():
            raise asyncio.CancelledError()
        # Do not cancel this task: late goal acceptance must still be canceled and drained.
        goal_id = secrets.token_bytes(16)
        if remote:
            self.audio_id = goal_id.hex()
        handle = await ros_future(client.send_goal_async(goal, goal_uuid=UUID(uuid=list(goal_id))))
        if not handle or not handle.accepted:
            raise ValueError('Voice service is busy')
        if navigation:
            self.navigation_goal = handle
        else:
            self.goal = handle
        if remote:
            self.audio_id = bytes(handle.goal_id.uuid).hex()
        if not current():
            handle.cancel_goal_async()
        elif on_accepted:
            await on_accepted()
        pending = asyncio.create_task(ros_future(handle.get_result_async()))
        try:
            result = await asyncio.wait_for(asyncio.shield(pending), timeout)
        except asyncio.TimeoutError:
            handle.cancel_goal_async()
            # Keep the drain barrier until the server actually completes.
            await pending
            raise ValueError('Voice service timed out')
        finally:
            if navigation:
                self.navigation_goal = None
            else:
                self.goal = None
        if not current():
            raise asyncio.CancelledError()
        if result.status != 4:
            raise ValueError('Voice request canceled or failed')
        return result.result

    async def _dispatch_navigation(self, turn, destination):
        if turn != self.turn:
            raise asyncio.CancelledError()
        if self.navigation_busy:
            raise VoiceTurnError('navigation_busy', '길안내 중입니다. 목적지를 바꾸려면 길안내를 먼저 중지해 주세요.')
        if not self.nav.server_is_ready():
            raise VoiceTurnError('navigation_unavailable', '길안내 서비스가 아직 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.')
        name = next((g['name'] for g in self.node.destinations if g['id'] == destination), destination)
        self.navigation_id = secrets.token_hex(16)
        self.navigation = {'status': 'STARTING', 'destination': destination, 'name': name}
        self.navigation_task = asyncio.create_task(self._run_navigation(self.navigation_id, destination, self.manager.active_ws))
        await self.emit(turn, 'navigation_state', **self.navigation)

    async def _run_navigation(self, identifier, destination, owner):
        # Navigation owns a separate action handle and drain barrier. Its events
        # must never reset a conversation or appear in a replacement session.
        async def publish(status):
            self.navigation = {**self.navigation, 'status': status}
            if owner and self.manager.active_ws is owner:
                try:
                    await owner.send_json({'type': 'navigation_state', **self.navigation})
                except (RuntimeError, ConnectionError):
                    pass
        try:
            result = await self._action(
                identifier, self.nav, NavigateNamed.Goal(destination=destination), timeout=940,
                on_accepted=lambda: publish('NAVIGATING'), navigation=True,
            )
            if result.code != NavigateNamed.Result.SUCCESS:
                raise ValueError('Navigation failed')
            # Arrival is displayed independently, without interrupting a user's
            # microphone or competing with an in-progress spoken answer.
            await publish('ARRIVED')
        except asyncio.CancelledError:
            await publish('IDLE')
        except Exception as exc:
            self.node.get_logger().warning(f'Visitor navigation failed: {type(exc).__name__}')
            await publish('FAILED' if identifier == self.navigation_id else 'IDLE')
        finally:
            if self.navigation_id == identifier:
                self.navigation_id = None

    async def _stream_ended(self, turn, stream_id, reason):
        await self.emit(turn, 'stt_closed', id=stream_id, reason=reason)
        await self.emit(turn, 'robot_state', status='TRANSCRIBING')

    async def _recognize_stream(self, turn, stream_id):
        try:
            stream = AzureSpeechStream(load_config(), lambda reason: asyncio.create_task(
                self._stream_ended(turn, stream_id, reason)))
            self.stream = stream
            try:
                await stream.start()
                if turn != self.turn:
                    stream.cancel()
                    raise asyncio.CancelledError()
                if not stream.input_closed:
                    await self.emit(turn, 'stt_ready', id=stream_id)
                return await stream.result()
            finally:
                await stream.close()
                self.stream = None
        except AzureSpeechError as exc:
            messages = {
                'stt_unavailable': '음성 인식 서비스가 준비되지 않았습니다. 텍스트로 보내 주세요.',
                'stt_timeout': '음성 인식 시간이 초과되었습니다. 다시 말씀하거나 텍스트로 보내 주세요.',
                'stt_unclear': '음성을 알아듣지 못했어요. 다시 말씀하거나 텍스트로 보내 주세요.',
                'stt_interrupted': '음성 연결이 끊겼습니다. 다시 말씀해 주세요.',
            }
            raise VoiceTurnError(exc.code, messages.get(exc.code, '음성을 처리하지 못했습니다. 다시 말씀하거나 텍스트로 보내 주세요.')) from None

    async def _run(self, turn, audio=None, text=None, stream_id=None, destination=None):
        owner = self.manager.active_ws
        stage = 'stt' if audio is not None or stream_id is not None else 'llm'
        try:
            if turn != self.turn:
                return
            if destination is not None:
                text = f"{destination['name']} 안내해줘"
            if stream_id is not None:
                text = await self._recognize_stream(turn, stream_id)
                if turn != self.turn:
                    raise asyncio.CancelledError()
                await self.emit(turn, 'stt_text', data=text)
            elif audio is not None:
                self.stt_waiter = asyncio.get_running_loop().create_future()
                self.audio_pub.publish(String(data=json.dumps({**audio, 'request_id': turn, 'created_at': time.time()})))
                audio.clear()
                await self.emit(turn, 'robot_state', status='TRANSCRIBING')
                try:
                    result = await asyncio.wait_for(self.stt_waiter, 45)
                except asyncio.TimeoutError as exc:
                    raise VoiceTurnError('stt_timeout', '음성 인식 시간이 초과되었습니다. 짧게 다시 말씀하시거나 텍스트로 보내 주세요.') from exc
                if result.get('event') == 'stt_error':
                    raise VoiceTurnError('stt_failed', '음성을 처리하지 못했습니다. 다시 녹음하거나 텍스트로 보내 주세요.')
                if result.get('event') != 'stt_result' or not result.get('text'):
                    raise VoiceTurnError('stt_unclear', '말씀을 정확히 알아듣지 못했어요. 마이크 가까이에서 다시 말씀하시거나 텍스트로 보내 주세요.')
                text = result['text']
                await self.emit(turn, 'stt_text', data=text)
            else:
                await self.emit(turn, 'user_text', data=text)
            stage = 'llm'
            await self.emit(turn, 'robot_state', status='THINKING')
            if destination is not None:
                answer = LLMQuery.Result(intent='navigation', target_location=destination['id'],
                                         response_text=f"{destination['name']}(으)로 안내하겠습니다.")
            else:
                answer = await self._action(turn, self.llm, LLMQuery.Goal(text=text, location_context=''))
            if answer.intent in ('error', 'canceled') or not answer.response_text:
                raise ValueError('Unable to generate an answer')
            if answer.intent == 'navigation':
                stage = 'navigation'
                if self.navigation_busy:
                    raise VoiceTurnError('navigation_busy', '길안내 중입니다. 목적지를 바꾸려면 길안내를 먼저 중지해 주세요.')
                if not answer.target_location:
                    raise VoiceTurnError('navigation_rejected', '목적지를 확인하지 못했습니다. 목록에서 선택하거나 목적지 이름을 말씀해 주세요.')
                if not self.nav.server_is_ready():
                    raise VoiceTurnError('navigation_unavailable', '길안내 서비스가 아직 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.')
            if answer.intent == 'follow':
                answer.response_text = '현재 스마트폰 연결에서는 캠퍼스에 관한 대화와 길안내만 가능합니다. 추종은 지원하지 않아요.'
            # Provenance travels alongside the answer and never enters Speak.Goal.
            sources = []
            try:
                metadata = json.loads(getattr(answer, 'sources_json', '') or '[]')
                if isinstance(metadata, list):
                    sources = [s for s in metadata if isinstance(s, dict) and isinstance(s.get('title'), str)]
            except (ValueError, TypeError):
                pass
            await self.emit(turn, 'llm_text', data=answer.response_text, **({'sources': sources} if sources else {}))
            stage = 'tts'
            await self.emit(turn, 'robot_state', status='SPEAKING')
            spoken = await self._action(turn, self.tts, Speak.Goal(text=answer.response_text), remote=True)
            if not spoken.success:
                raise ValueError('Phone playback failed')

            if answer.intent == 'navigation':
                stage = 'navigation'
                await self._dispatch_navigation(turn, answer.target_location)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            self.node.get_logger().warning(f"Visitor turn failed at {stage}: {type(exc).__name__}")
            messages = {
                'stt': '음성을 처리하지 못했습니다. 다시 녹음하거나 텍스트로 보내 주세요.',
                'llm': '답변을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.',
                'tts': '답변 음성을 재생하지 못했습니다. 답변은 화면에서 확인해 주세요.',
                'navigation': '길안내를 완료하지 못했습니다. 현재 지도와 로봇 상태를 확인한 뒤 다시 시도해 주세요.',
            }
            code = exc.code if isinstance(exc, VoiceTurnError) else f'{stage}_failed'
            message = str(exc) if isinstance(exc, VoiceTurnError) else messages[stage]
            await self.emit(turn, 'error', code=code, message=message)
        finally:
            if stream_id is not None:
                await self.emit(turn, 'stt_closed', id=stream_id, reason='finished')
                self.stream_id = None
            self.stt_waiter = None
            self.media.clear()
            self.audio_id = None
            await self.emit(turn, 'robot_state', status='READY')
            if self.response_stop_requested and owner and self.manager.active_ws is owner:
                try:
                    await owner.send_json({'type': 'robot_state', 'status': 'READY'})
                except (RuntimeError, ConnectionError):
                    pass
            if self.turn == turn:
                self.turn = None

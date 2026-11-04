"""Bounded visitor voice turns. ROS action UUIDs identify work, never users."""
import asyncio
import base64
import io
import json
import secrets
import wave
import time

from rclpy.action import ActionClient
from dori_msgs.action import LLMQuery, Speak
from std_msgs.msg import String
from unique_identifier_msgs.msg import UUID

MAX_AUDIO_BYTES = 320044
MAX_TEXT_CHARS = 1000


def validate_text(data):
    text = data.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT_CHARS:
        raise ValueError('메시지를 1~1,000자 이내로 입력해 주세요.')
    return text.strip()


def validate_audio(data):
    if (data.get('format'), data.get('sample_rate'), data.get('channels')) != ('wav_pcm16', 16000, 1):
        raise ValueError('Expected 16kHz mono PCM16 WAV')
    encoded = data.get('audio_b64')
    if not isinstance(encoded, str) or len(encoded) > 430000:
        raise ValueError('Audio exceeds 10 seconds')
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > MAX_AUDIO_BYTES:
            raise ValueError('Audio exceeds limit')
        with wave.open(io.BytesIO(raw), 'rb') as wav:
            n = wav.getnframes()
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getcomptype()) != (16000, 1, 2, 'NONE'):
                raise ValueError('Invalid WAV format')
            if not 8000 <= n <= 160000 or len(wav.readframes(n)) != n * 2:
                raise ValueError('Audio must contain 0.5 to 10 seconds')
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
        self.audio_id = None
        self.media = {}
        self.llm = ActionClient(node, LLMQuery, 'llm/query')
        self.tts = ActionClient(node, Speak, 'tts/speak_remote')
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
        return self.task is not None and not self.task.done()

    def start(self, payload):
        audio = validate_audio(payload)
        self._start_turn(audio=audio)

    def start_text(self, payload):
        self._start_turn(text=validate_text(payload))

    def _start_turn(self, audio=None, text=None):
        if self.draining:
            raise ValueError('이전 답변을 처리 중입니다. 잠시 후 보내 주세요.')
        if (not self.llm.server_is_ready() or not self.tts.server_is_ready()
                or (audio is not None and not self.audio_pub.get_subscription_count())):
            raise ValueError('대화 서비스가 아직 준비되지 않았습니다.')
        self.turn = secrets.token_hex(16)
        self.task = asyncio.create_task(self._run(self.turn, audio=audio, text=text))

    def cancel(self):
        self.turn = None
        self.media.clear()
        self.audio_id = None
        if self.goal:
            self.goal.cancel_goal_async()
        if self.stt_waiter and not self.stt_waiter.done():
            self.stt_waiter.cancel()

    def playback(self, data):
        if self.turn and data.get('id') == self.audio_id and data.get('status') in ('ended', 'failed', 'canceled'):
            self.playback_pub.publish(String(data=json.dumps({'id': self.audio_id, 'status': data['status']})))
            self.media.clear()

    async def _action(self, turn, client, goal, remote=False):
        if turn != self.turn:
            raise asyncio.CancelledError()
        # Do not cancel this task: late goal acceptance must still be canceled and drained.
        goal_id = secrets.token_bytes(16)
        if remote:
            self.audio_id = goal_id.hex()
        handle = await ros_future(client.send_goal_async(goal, goal_uuid=UUID(uuid=list(goal_id))))
        if not handle.accepted:
            raise ValueError('Voice service is busy')
        self.goal = handle
        if remote:
            self.audio_id = bytes(handle.goal_id.uuid).hex()
        if turn != self.turn:
            handle.cancel_goal_async()
        pending = asyncio.create_task(ros_future(handle.get_result_async()))
        try:
            result = await asyncio.wait_for(asyncio.shield(pending), 100)
        except asyncio.TimeoutError:
            handle.cancel_goal_async()
            # Keep the drain barrier until the server actually completes.
            await pending
            raise ValueError('Voice service timed out')
        finally:
            self.goal = None
        if turn != self.turn:
            raise asyncio.CancelledError()
        if result.status != 4:
            raise ValueError('Voice request canceled or failed')
        return result.result

    async def _run(self, turn, audio=None, text=None):
        try:
            if turn != self.turn:
                return
            if audio is not None:
                self.stt_waiter = asyncio.get_running_loop().create_future()
                self.audio_pub.publish(String(data=json.dumps({**audio, 'request_id': turn, 'created_at': time.time()})))
                audio.clear()
                await self.emit(turn, 'robot_state', status='TRANSCRIBING')
                result = await asyncio.wait_for(self.stt_waiter, 45)
                if result.get('event') != 'stt_result' or not result.get('text'):
                    raise ValueError('Speech unclear; please try again')
                text = result['text']
                await self.emit(turn, 'stt_text', data=text)
            else:
                await self.emit(turn, 'user_text', data=text)
            await self.emit(turn, 'robot_state', status='THINKING')
            answer = await self._action(turn, self.llm, LLMQuery.Goal(text=text, location_context=''))
            if answer.intent in ('error', 'canceled') or not answer.response_text:
                raise ValueError('Unable to generate an answer')
            if answer.intent in ('navigation', 'follow'):
                answer.response_text = '현재 스마트폰 연결에서는 캠퍼스에 관한 대화만 가능합니다. 이동 안내와 추종은 아직 지원하지 않아요.'
            # Intents are deliberately never dispatched to robot motion in visitor v1.
            await self.emit(turn, 'llm_text', data=answer.response_text)
            await self.emit(turn, 'robot_state', status='SPEAKING')
            spoken = await self._action(turn, self.tts, Speak.Goal(text=answer.response_text), remote=True)
            if not spoken.success:
                raise ValueError('Phone playback failed')
        except asyncio.CancelledError:
            pass
        except Exception:
            await self.emit(turn, 'error', code='voice_failed', message='대화 처리에 실패했습니다. 잠시 후 다시 시도해 주세요.')
        finally:
            self.stt_waiter = None
            self.media.clear()
            self.audio_id = None
            await self.emit(turn, 'robot_state', status='READY')
            if self.turn == turn:
                self.turn = None

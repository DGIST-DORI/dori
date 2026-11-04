"""Production ROS voice actions/BT with fake STT and synthesis, isolated domain only."""
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import wave
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from std_msgs.msg import String
from std_srvs.srv import SetBool, Trigger
from dori_dashboard import bridge_api as bridge
from dori_hri.tts_node import TTSNode
from dori_llm.llm_node import LLMNode


def test_visitor_pair_voice_playback_cancel_and_cleanup(tmp_path):
    assert os.environ.get('ROS_DOMAIN_ID') == '96'
    assert os.environ.get('ROS_LOCALHOST_ONLY') == '1'
    asyncio.run(run_flow(tmp_path))


async def run_flow(tmp_path):
    async def until(predicate, seconds=12):
        deadline = asyncio.get_running_loop().time() + seconds
        while not predicate():
            if asyncio.get_running_loop().time() > deadline:
                raise AssertionError('ROS condition timed out')
            await asyncio.sleep(.05)

    rclpy.init(args=['--ros-args', '-r', '__ns:=/dori', '-p', 'playback_mode:=publish_only',
                    '-p', 'use_external_llm:=false'])
    manager = bridge.SessionManager()
    manager.main_loop = asyncio.get_running_loop()
    follow_requests = []
    stt_requests = []
    def synthesize(_self, _text):
        path = tmp_path / 'reply.mp3'
        path.write_bytes(b'test-mp3')
        return str(path)
    with patch.object(bridge, 'session_manager', manager), patch.object(TTSNode, '_synthesize_gtts', synthesize), patch.object(TTSNode, '_on_audio_cue', lambda *_: None):
        node, llm, tts, probe = bridge.BridgeNode(), LLMNode(), TTSNode(), Node('visitor_probe')
        bridge.ros_node = node
        publisher = probe.create_publisher(String, 'stt/visitor_result', 10)
        def transcribe(message):
            request = json.loads(message.data)
            stt_requests.append(request['request_id'])
            publisher.publish(String(data=json.dumps({'request_id': request['request_id'], 'event': 'stt_result', 'text': 'hello'})))
        probe.create_subscription(String, 'stt/audio_input', transcribe, 10)
        def stt_reset(_request, response):
            response.success = True
            return response
        probe.create_service(Trigger, 'stt/reset', stt_reset)
        def follow(request, response):
            follow_requests.append(request.data)
            response.success = True
            return response
        probe.create_service(SetBool, 'hri/set_follow_mode', follow)
        executor = MultiThreadedExecutor(num_threads=8)
        for n in (node, llm, tts, probe): executor.add_node(n)
        worker = threading.Thread(target=executor.spin, daemon=True)
        worker.start()
        log = (tmp_path / 'bt.log').open('w')
        bt = subprocess.Popen(['ros2', 'run', 'dori_bt', 'dori_tree_executor', '--ros-args', '-r', '__ns:=/dori', '-p', 'visitor_mode:=true'], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            await until(lambda: node.cli_stt_reset.service_is_ready() and node.cli_visitor_ready.service_is_ready() and node.cli_tts_reset.service_is_ready() and node.cli_llm_reset.service_is_ready() and node.cli_bt_clear.service_is_ready() and node.voice.llm.server_is_ready() and node.voice.tts.server_is_ready() and node.voice.audio_pub.get_subscription_count())
            assert await node.prepare_visitor()
            await manager.start_session()
            manager.active_ws = SimpleNamespace(send_json=AsyncMock(), close=AsyncMock())
            output = io.BytesIO()
            with wave.open(output, 'wb') as wav:
                wav.setparams((1, 2, 16000, 0, 'NONE', ''))
                wav.writeframes(b'\0\0' * 16000)
            payload = dict(format='wav_pcm16', sample_rate=16000, channels=1, audio_b64=base64.b64encode(output.getvalue()).decode())
            node.voice.start(payload)
            await until(lambda: bool(node.voice.media))
            assert node.voice.draining
            assert list(node.voice.media.values()) == [b'test-mp3']
            node.voice.playback({'id': node.voice.audio_id, 'status': 'ended'})
            await until(lambda: not node.voice.draining)
            assert llm.conversation_history
            assert not node.voice.media
            node.voice.start(payload)
            await until(lambda: bool(node.voice.media))
            node.cancel_visitor()
            await until(lambda: not node.voice.draining)
            assert not node.voice.media
            assert manager.state == bridge.SessionState.ACTIVE
            audio_count = len(stt_requests)
            node.voice.start_text({'text': '안녕하세요'})
            await until(lambda: bool(node.voice.media))
            assert len(stt_requests) == audio_count
            assert any(call.args[0] == {'type': 'user_text', 'data': '안녕하세요'}
                       for call in manager.active_ws.send_json.call_args_list)
            node.voice.playback({'id': node.voice.audio_id, 'status': 'ended'})
            await until(lambda: not node.voice.draining)
            assert llm.conversation_history[-1]['user'] == '안녕하세요'
            assert await manager.end_session()
            assert manager.state == bridge.SessionState.IDLE
            assert not llm.conversation_history
            assert True not in follow_requests
            assert bt.poll() is None
        finally:
            node.cancel_visitor()
            await manager._cancel_session_timers()
            if bt.poll() is None:
                os.killpg(bt.pid, signal.SIGINT)
                try: bt.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    os.killpg(bt.pid, signal.SIGKILL)
                    bt.wait(timeout=2)
            executor.shutdown(timeout_sec=3)
            worker.join(timeout=3)
            for n in (probe, tts, llm, node): n.destroy_node()
            rclpy.shutdown()
            log.close()
            bridge.ros_node = None

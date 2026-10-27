"""Production BT + LLM + TTS + named/DORI adapters, with a controllable Nav2 peer.

Speech recognition and physical sound are outside this fixture: STT JSON is
injected and TTS uses the production browser-publish path without a network API.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import time

import pytest
import rclpy
from dori_hri.tts_node import TTSNode
from dori_hri.emotion_publisher_node import EmotionPublisherNode
from dori_llm.llm_node import LLMNode, IntentClassifier
from dori_navigation.named_goal_adapter import NamedGoalAdapter
from dori_navigation.nav2_adapter import Nav2Adapter
from nav_msgs.msg import OccupancyGrid
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, DurabilityPolicy
from std_msgs.msg import String, Int32, Bool
from .test_action_flow import Backend, wait


@pytest.fixture
def flow(tmp_path, request):
    assert os.getenv('ROS_DOMAIN_ID') == '96' and os.getenv('ROS_LOCALHOST_ONLY') == '1'
    rclpy.init(args=['--ros-args', '-r', '__ns:=/dori', '-p', 'playback_mode:=publish_only'])
    backend, adapter, named, llm, tts = Backend(), Nav2Adapter(), NamedGoalAdapter(), LLMNode(), TTSNode()
    emotion = EmotionPublisherNode()
    probe = Node('hri_probe')
    executor = MultiThreadedExecutor(num_threads=12)
    nodes = [backend, adapter, named, llm, tts, emotion, probe]
    for node in nodes:
        executor.add_node(node)
    worker = threading.Thread(target=executor.spin)
    worker.start()
    latch = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    hardware = probe.create_publisher(Int32, '/system/action_state', latch)
    mode = probe.create_publisher(Int32, '/NAVIGATION_MODE', 10)
    maps = probe.create_publisher(OccupancyGrid, '/map', latch)
    stt = probe.create_publisher(String, '/dori/stt/result', 10)
    tracking = probe.create_publisher(String, '/dori/hri/tracking_state', 10)
    mic = probe.create_publisher(Bool, '/dori/hri/mic_attached', 10)
    gesture = probe.create_publisher(String, '/dori/hri/gesture_command', 10)
    expression = probe.create_publisher(String, '/dori/hri/expression_command', 10)
    trigger = probe.create_publisher(Bool, '/dori/hri/interaction_trigger', 10)
    access = probe.create_publisher(Bool, '/dori/hri/access_blocked', 10)
    states, spoken = [], []
    probe.create_subscription(String, '/dori/hri/manager_state',
        lambda m: states.append(json.loads(m.data)['state']), latch)
    probe.create_subscription(String, '/dori/tts/audio_event',
        lambda m: spoken.append(json.loads(m.data)), 10)
    wait(lambda: hardware.get_subscription_count()>0 and maps.get_subscription_count()>0)
    hardware.publish(Int32(data=1))
    map_msg = OccupancyGrid()
    map_msg.header.frame_id = 'map'
    map_msg.info.width = map_msg.info.height = 100
    map_msg.info.resolution = .1
    map_msg.info.origin.orientation.w = 1.
    map_msg.data = [0]*10000
    maps.publish(map_msg)
    wait(lambda: named._key is not None)
    path = tmp_path/'goals.json'
    path.write_text(json.dumps({'version':1, 'maps':{named._key:[
        dict(id='lobby-id', name='Lobby', x=1., y=0., yaw=0.)]}}))
    named.set_parameters([Parameter('goals_file',value=str(path))])
    wait(lambda: len(llm.registered)==1)
    logfile = (tmp_path/'bt.log').open('w')
    proc = subprocess.Popen(['ros2','run','dori_bt','dori_tree_executor','--ros-args',
        '-r','__ns:=/dori','-p','require_mic_return:=true',
        '-p','require_user_tracking:='+str(getattr(request,'param',False)).lower()], stdout=logfile, stderr=subprocess.STDOUT,
        start_new_session=True)
    try:
        wait(lambda: stt.get_subscription_count()>0 and states, 8)
        def text(value, confidence=1.):
            stt.publish(String(data=json.dumps(dict(text=value, confidence=confidence, event='stt_result'))))
        yield dict(backend=backend, adapter=adapter, named=named, llm=llm, states=states,
                   spoken=spoken, text=text, mic=mic, tracking=tracking, access=access, proc=proc,
                   gesture=gesture, expression=expression, trigger=trigger, emotion=emotion,
                   log=tmp_path/'bt.log')
        assert proc.poll() is None, (tmp_path/'bt.log').read_text()
    finally:
        backend.finish = True
        mode.publish(Int32(data=0))
        if proc.poll() is None:
            proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
        wait(lambda: backend.active==0 and not adapter._busy and not named._busy, 8)
        executor.shutdown(timeout_sec=3)
        worker.join(timeout=3)
        for node in reversed(nodes):
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
        logfile.close()


def test_qa_mic_return_and_unknown_destination_never_drive(flow):
    f=flow
    f['mic'].publish(Bool(data=False))
    wait(lambda: 'LISTENING' in f['states'])
    f['text']('hello')
    wait(lambda: 'WAIT_MIC_RETURN' in f['states'])
    assert f['spoken'] and f['backend'].accepted == 0
    f['mic'].publish(Bool(data=True))
    wait(lambda: f['states'][-1]=='IDLE')
    count=len(f['spoken'])
    f['text']('Please take me to an unregistered room')
    wait(lambda: len(f['spoken'])>count)
    wait(lambda: f['states'][-1]=='IDLE')
    assert f['backend'].accepted == 0 and not f['adapter']._enabled
    f['text']('Please take me to Lobby', confidence=.2)
    time.sleep(.3)
    assert f['backend'].accepted == 0


def test_guidance_waits_for_navigation_arrival_then_speaks(flow):
    f=flow
    f['text']('Please take me to Lobby')
    wait(lambda: f['backend'].active==1, 8)
    assert f['states'][-1]=='GUIDING'
    wait(lambda: f['emotion']._resolve_emotion()==('HAPPY','state'))
    time.sleep(.3)
    assert 'ARRIVED' not in f['states']
    f['backend'].finish = True
    wait(lambda: 'ARRIVED' in f['states'])
    wait(lambda: f['states'][-1]=='IDLE')
    assert f['backend'].max_active==1
    assert any('목적지에 도착' in json.dumps(m,ensure_ascii=False) for m in f['spoken'])


def test_voice_stop_cancels_and_does_not_announce_arrival(flow):
    f=flow
    f['text']('Lobby로 안내해줘')
    wait(lambda: f['backend'].active==1, 8)
    f['text']('멈춰줘')
    wait(lambda: f['backend'].cancel_seen and not f['adapter']._enabled)
    assert 'CANCELED' in f['states'] and 'ARRIVED' not in f['states']


def test_access_blocked_cancels_then_recovery_reissues_one_goal(flow):
    f=flow
    f['text']('Lobby로 안내해줘')
    wait(lambda: f['backend'].active==1, 8)
    f['access'].publish(Bool(data=True))
    wait(lambda: f['states'][-1]=='ACCESS_HELP' and f['backend'].cancel_seen)
    assert not f['adapter']._enabled
    f['access'].publish(Bool(data=False))
    wait(lambda: f['backend'].accepted==2 and f['backend'].active==1, 8)
    assert f['backend'].max_active==1
    f['backend'].finish=True
    wait(lambda: 'ARRIVED' in f['states'])


def test_information_is_not_a_motion_request():
    for text in ('Where is Lobby?', 'Lobby가 뭐야?', 'How to get to Lobby?'):
        assert IntentClassifier.classify(text) != 'navigation'
    for text in ('Lobby로 안내해줘', 'Please take me to Lobby'):
        assert IntentClassifier.classify(text) == 'navigation'


@pytest.mark.parametrize('flow', [True], indirect=True)
def test_tracking_loss_stops_and_reacquisition_resumes(flow):
    f=flow
    running=threading.Event()
    running.set()
    visible=[True]
    def tracker():
        while running.is_set():
            if visible[0]:
                f['tracking'].publish(String(data=json.dumps(dict(state='tracking',last_distance_m=1.))))
            time.sleep(.1)
    thread=threading.Thread(target=tracker); thread.start()
    try:
        time.sleep(.2)
        f['text']('Lobby로 안내해줘')
        wait(lambda: f['backend'].active==1, 8)
        visible[0]=False
        wait(lambda: 'USER_LOST_CONFIRM' in f['states'] and f['backend'].cancel_seen)
        assert not f['adapter']._enabled and 'ARRIVED' not in f['states']
        visible[0]=True
        wait(lambda: f['backend'].accepted==2, 8)
        f['backend'].finish=True
        wait(lambda: 'ARRIVED' in f['states'])
        assert f['backend'].max_active==1
    finally:
        running.clear(); thread.join(2)


def test_perception_commands_cannot_fake_arrival_and_stop_cancels(flow):
    f=flow
    f['trigger'].publish(Bool(data=True))
    wait(lambda: f['states'][-1]=='LISTENING')
    f['text']('Lobby로 안내해줘')
    wait(lambda: f['backend'].active==1, 8)
    f['expression'].publish(String(data='{"command":"GUIDANCE_COMPLETE"}'))
    time.sleep(.3)
    assert f['states'][-1]=='GUIDING' and 'ARRIVED' not in f['states']
    f['gesture'].publish(String(data='{"command":"STOP"}'))
    wait(lambda: f['backend'].cancel_seen and not f['adapter']._enabled)
    assert 'CANCELED' in f['states'] and 'ARRIVED' not in f['states']

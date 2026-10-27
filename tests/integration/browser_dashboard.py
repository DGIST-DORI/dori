#!/usr/bin/env python3
"""Real dashboard + map HTTP + rosbridge + Firefox; no actuators (domain 97).

Run after web/ROS build. Requires Firefox --headless --marionette on port 2828
and marionette_driver installed. SpeechSynthesis is observed, not acoustic audio.
"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

import httpx
from marionette_driver.marionette import Marionette
from marionette_driver.by import By
import rclpy
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import String
from nav_msgs.msg import OccupancyGrid, Odometry
from geometry_msgs.msg import TransformStamped
from rclpy.qos import QoSProfile, DurabilityPolicy
from tf2_ros import StaticTransformBroadcaster

ROOT = Path(__file__).resolve().parents[2]
URL = 'http://127.0.0.1:13000'


def wait(fn, seconds=12):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            if fn(): return
        except (httpx.HTTPError, ConnectionError):
            pass
        time.sleep(.1)
    raise AssertionError('Browser/ROS condition timed out')


def main():
    assert os.getenv('ROS_DOMAIN_ID')=='97' and os.getenv('ROS_LOCALHOST_ONLY')=='1'
    processes=[]; logs=[]
    browser=None; executor=None; probe=None; worker=None
    with tempfile.TemporaryDirectory() as directory:
        def start(name, cmd):
            log=open(Path(directory)/(name+'.log'),'w'); logs.append(log)
            processes.append(subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True))
        try:
            start('viewer',[sys.executable,str(ROOT/'ros2_ws/src/robot_navigation/scripts/web_viewer.py'),
                '--mode','monitor','--host','127.0.0.1','--port','8080','--user-port','0',
                '--goals-file',str(Path(directory)/'goals.json')])
            start('api',[sys.executable,str(ROOT/'ros2_ws/src/dori_dashboard/dori_dashboard/knowledge_api.py'),
                '--repo-root',str(ROOT),'--web-dir',str(ROOT/'web/dist'),'--port','13000'])
            start('rosbridge',['ros2','run','rosbridge_server','rosbridge_websocket','--ros-args','-p','port:=9090'])
            start('rosapi',['ros2','run','rosapi','rosapi_node'])
            client=httpx.Client(base_url=URL,timeout=4,trust_env=False)
            wait(lambda: client.get('/navigation/api/state').status_code==200)
            assert client.get('/api/deploy/status').json()['enabled'] is False
            assert client.post('/api/deploy/trigger').status_code==423
            assert client.get('/api/not-an-api').status_code==404
            assert client.get('/navigation/not-an-asset').status_code==404
            csrf=client.get('/navigation/api/session').json()['csrf']
            assert client.post('/navigation/api/command',json={'action':'stop','client':'test-browser'}).status_code==403
            assert client.post('/navigation/api/command',headers={'X-Dori-Control':csrf,'Origin':'https://foreign.invalid'},
                               json={'action':'stop','client':'test-browser'}).status_code==403
            assert client.post('/navigation/api/command',headers={'X-Dori-Control':csrf,'Origin':URL},
                               json={'action':'stop','client':'test-browser'}).status_code==200
            rclpy.init(); probe=rclpy.create_node('dashboard_validation_probe')
            pub=probe.create_publisher(String,'/dori/tts/audio_event',10)
            maps=probe.create_publisher(OccupancyGrid,'/map',QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL))
            odoms=probe.create_publisher(Odometry,'/odom',10)
            transforms=StaticTransformBroadcaster(probe)
            transform=TransformStamped(); transform.header.frame_id='map'; transform.child_frame_id='base_link'
            transform.transform.rotation.w=1.; transforms.sendTransform(transform)
            grid=OccupancyGrid(); grid.header.frame_id='map'
            grid.info.width=grid.info.height=80; grid.info.resolution=.05
            grid.info.origin.position.x=grid.info.origin.position.y=-2.; grid.info.origin.orientation.w=1.
            grid.data=[100 if x in (0,79) or y in (0,79) else 0 for y in range(80) for x in range(80)]
            maps.publish(grid)
            def telemetry():
                odom=Odometry(); odom.header.frame_id='map'; odom.child_frame_id='base_link'
                odom.header.stamp=probe.get_clock().now().to_msg(); odom.pose.pose.orientation.w=1.
                odoms.publish(odom)
            probe.create_timer(.1,telemetry)
            executor=SingleThreadedExecutor(); executor.add_node(probe)
            worker=threading.Thread(target=executor.spin); worker.start()
            browser=Marionette('127.0.0.1',port=2828); browser.start_session()
            js=lambda code: browser.execute_script(code,sandbox=None)
            browser.navigate(URL)
            wait(lambda: js('return !!document.querySelector(".sb-search-btn")'))
            browser.find_element(By.CSS_SELECTOR,'.sb-search-btn').click()
            browser.find_element(By.CSS_SELECTOR,'.sb-search-input').send_keys('Robot Map')
            wait(lambda: js('return document.querySelectorAll(".sb-leaf").length===1'))
            time.sleep(.4)  # sidebar expand transition must finish before a real pointer click
            browser.find_element(By.CSS_SELECTOR,'.sb-leaf').click()
            wait(lambda: js('return !!document.querySelector("iframe")?.contentDocument?.querySelector("canvas")'))
            assert js('return document.querySelector("iframe").src')==URL+'/navigation/'
            wait(lambda: client.get('/navigation/api/state').json().get('robot') is not None)
            wait(lambda: js('return document.querySelector("iframe").contentWindow.performance.getEntriesByType("resource").some(r=>r.name.includes("api/map.png"))'))
            browser.find_element(By.CSS_SELECTOR,'.hdr-btn').click()
            wait(lambda: js('return !!document.querySelector(".sb-status.connected")'))
            wait(lambda: pub.get_subscription_count()>0)
            js('window.testSpeech=[];speechSynthesis.speak=u=>{if(u.text.trim())window.testSpeech.push(u.text);u.onend?.()};speechSynthesis.cancel=()=>{}')
            def say(text,mode='publish_only'):
                pub.publish(String(data=json.dumps(dict(event_type='tts_text',text=text,playback_mode=mode,timestamp=time.time()))))
            say('통합 음성 출력 검증')
            wait(lambda: js('return window.testSpeech.includes("통합 음성 출력 검증")'))
            say('로봇 스피커 전용','local_only'); time.sleep(.3)
            assert '로봇 스피커 전용' not in js('return window.testSpeech')
            # Real disconnect/reconnect must preserve the String type of audio events.
            browser.find_element(By.CSS_SELECTOR,'.hdr-btn').click()
            wait(lambda: js('return !document.querySelector(".sb-status.connected")'))
            browser.find_element(By.CSS_SELECTOR,'.hdr-btn').click()
            wait(lambda: js('return !!document.querySelector(".sb-status.connected")'))
            wait(lambda: pub.get_subscription_count()>0)
            say('재연결 출력 검증')
            wait(lambda: js('return window.testSpeech.includes("재연결 출력 검증")'))
            search=browser.find_element(By.CSS_SELECTOR,'.sb-search-input')
            search.clear(); search.send_keys('Topic Publisher')
            wait(lambda: js('return document.querySelectorAll(".sb-leaf").length===1'))
            time.sleep(.4)
            browser.find_element(By.CSS_SELECTOR,'.sb-leaf').click()
            wait(lambda: js('return !!document.querySelector("#tp-topic")'))
            topics=js('return Array.from(document.querySelector("#tp-topic").options,o=>o.value)')
            assert all('cmd_vel' not in topic for topic in topics),topics
            assert '/dori/stt/result' in topics and '/dori/tts/text' in topics,topics
            assert all(p.poll() is None for p in processes)
            report=dict(ok=True,mode='real HTTP + rosbridge + headless Firefox, ROS domain 97',
                navigation_iframe=True,synthetic_map_and_robot_rendered=True,api_routes=True,csrf_and_origin=True,live_deploy_locked=True,
                tts_output_and_reconnect=True,local_only_not_duplicated=True,
                no_legacy_velocity_publisher=True,
                physical_audio_verified=False,hardware_actuated=False)
            out=ROOT/'log/validation'; out.mkdir(parents=True,exist_ok=True)
            (out/'dashboard-browser.json').write_text(json.dumps(report,indent=2)+'\n')
            import base64
            (out/'dashboard.png').write_bytes(base64.b64decode(browser.screenshot()))
            print(json.dumps(report,ensure_ascii=False))
        except Exception:
            for log in logs:
                log.flush(); print(Path(log.name).read_text()[-4000:],file=sys.stderr)
            raise
        finally:
            if browser: browser.delete_session()
            if executor: executor.shutdown(timeout_sec=3)
            if worker: worker.join(3)
            if probe: probe.destroy_node()
            if rclpy.ok(): rclpy.shutdown()
            for process in reversed(processes):
                if process.poll() is None: os.killpg(process.pid,signal.SIGINT)
            for process in processes:
                try: process.wait(6)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL); process.wait(2)
            for log in logs: log.close()


if __name__=='__main__': main()

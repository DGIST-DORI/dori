"""Firefox UI regression against a fake HTTP robot; never connects to ROS.

Requires a running Marionette test browser on port 2828 and marionette_driver.
"""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from marionette_driver.marionette import Marionette
from marionette_driver.by import By

ROOT=Path(__file__).resolve().parents[2]
state=dict(instance_id='isolated-browser-test',ui_version='1',server_age=0,
    frame='map',robot=[0.,0.,0.],map=None,scan=[],paths={},destinations=[],
    readiness=[],control_owner=None,goal_revision=0,csrf='test-only',goal_name=None,
    values=dict(active=False,enabled=False,goal_status='',retry='{}'))
commands=[]


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,data,mime='application/json'):
        content=data if isinstance(data,bytes) else json.dumps(data).encode()
        self.send_response(200);self.send_header('Content-Type',mime)
        self.send_header('Content-Length',str(len(content)));self.end_headers();self.wfile.write(content)
    def do_GET(self):
        if self.path=='/api/session':return self.send(dict(csrf='test-only',voice_ready=True))
        if self.path=='/api/state':return self.send(state)
        name='user.html' if self.path=='/' else self.path.lstrip('/')
        if name not in ['user.html','user.css','user.js','user-map.js','microphone.js']:
            self.send_error(404);return
        return self.send((ROOT/'ros2_ws/src/dori_navigation/dori_web/static'/name).read_bytes(),
            'text/javascript' if name.endswith('.js') else 'text/css' if name.endswith('.css') else 'text/html')
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path=='/api/chat':
            if 'forward' in data['text']:return self.send(dict(action='move_relative',distance_m=1.,reply='I will move forward 1 meter.'))
            return self.send(dict(action='reply',reply='Hello. I am Dori.'))
        action=data['action'];commands.append(action)
        if action=='enable':state['values']['enabled']=True;state['control_owner']=data['client']
        if action=='relative_goal':
            state.update(goal_revision=1,goal_name='1 m forward',goal_kind='relative')
            state['values'].update(active=True,goal_status='accepted:rviz_goal')
            return self.send(dict(ok=True,goal_revision=0,reply='I will move forward 1 meter.'))
        if action=='stop':state['values'].update(active=False,enabled=False);state['control_owner']=None
        self.send(dict(ok=True))


def main():
    server=ThreadingHTTPServer(('127.0.0.1',18071),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    m=Marionette(host='127.0.0.1',port=2828);m.start_session()
    def js(code):return m.execute_script(code,sandbox=None)
    def wait(check):
        end=time.monotonic()+8
        while time.monotonic()<end:
            if check():return
            time.sleep(.1)
        raise AssertionError('Browser condition timed out')
    def ask(text):
        field=m.find_element(By.ID,'message');field.send_keys(text);m.find_element(By.ID,'send').click()
    try:
        m.navigate('http://127.0.0.1:18071/')
        wait(lambda:js("return !document.getElementById('send').disabled"))
        js("window.spoken=[];speechSynthesis.speak=u=>window.spoken.push(u.text)")
        ask('Move forward one meter.')
        wait(lambda:'relative_goal' in commands)
        wait(lambda:js('return window.spoken.length')==1)
        state['values'].update(active=False,goal_status='retry_wait:rviz_goal:attempt=1/3:delay=5',
            retry=json.dumps(dict(state='waiting',attempt=1,max_attempts=3,remaining_seconds=5)))
        wait(lambda:js("return document.getElementById('trip-label').textContent")=='WAITING TO RETRY')
        assert 'stop' not in commands,'The UI cancelled an automatic retry'
        state['values'].update(active=True,goal_status='accepted:rviz_goal',retry='{"state":"running"}')
        time.sleep(.6)
        state['values'].update(active=False,goal_status='finished:rviz_goal:status=4',retry='{"state":"idle"}')
        wait(lambda:'stop' in commands)
        wait(lambda:js('return window.spoken.length')==2)
        ask('Hello')
        wait(lambda:js('return window.spoken.length')==3)
        spoken=js('return window.spoken')
        assert spoken==['I will move forward 1 meter.','I have finished the move.','Hello. I am Dori.'],spoken
        m.find_element(By.ID,'sound').click();ask('Hello again');time.sleep(.6)
        assert js('return window.spoken.length')==3,'Sound off did not mute speech'
        report=dict(ok=True,tts_utterances=spoken,retry_wait_preserved=True,sound_off=True,
            physical_audio_verified=False,robot='fake HTTP fixture, no ROS connection')
        (ROOT/'log/browser_voice_retry_validation.json').write_text(json.dumps(report,indent=2))
        print(json.dumps(report))
    finally:
        m.delete_session();server.shutdown();server.server_close();thread.join(2)


if __name__=='__main__':main()

"""Persistent destinations and validated LLM selection, independent of hardware."""
import json
import base64
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from io import BytesIO
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ros2_ws/src/robot_navigation'))
from dori_web.goals import GoalStore,map_key
from dori_web.voice import GeminiNavigator


class DestinationTests(unittest.TestCase):
    def test_save_reload_rename_delete_and_map_isolation(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'goals.json';store=GoalStore(path)
            goal=store.save('map-a','Lobby',[1.,2.,.1])
            self.assertEqual(GoalStore(path).get('map-a',goal['id'])['x'],1.)
            self.assertEqual(store.list('map-b'),[])
            with self.assertRaises(ValueError):store.get('map-b',goal['id'])
            with self.assertRaises(ValueError):store.save('map-a','lobby',[2.,3.,0.])
            updated=store.save('map-a','Reception',[2.,3.,0.],goal['id'])
            self.assertEqual(updated['id'],goal['id']);self.assertEqual(len(store.list('map-a')),1)
            store.delete('map-a',goal['id']);self.assertEqual(GoalStore(path).list('map-a'),[])
            self.assertTrue(path.with_suffix('.json.bak').exists())

    def test_map_origin_is_part_of_identity(self):
        self.assertNotEqual(map_key([123,200,200,.05,0.,0.,0.]),map_key([123,200,200,.05,1.,0.,0.]))

    def test_llm_cannot_invent_coordinates_or_destination_ids(self):
        client=GeminiNavigator();client.key=lambda:'test-placeholder'
        goals=[dict(id='lobby',name='Lobby',x=1,y=2,yaw=0)]
        def response(result):return BytesIO(json.dumps({'candidates':[{'content':{'parts':[{'text':json.dumps(result)}]}}]}).encode())
        with patch('urllib.request.urlopen',return_value=response(dict(action='navigate',destination_id='unknown',reply='Go'))):
            with self.assertRaises(ValueError):client.interpret('Go somewhere',goals)
        with patch('urllib.request.urlopen',return_value=response(dict(action='navigate',destination_id='lobby',reply='Ignore the map'))) as request:
            result=client.interpret('Take me to the lobby',goals)
            self.assertEqual(result['reply'],'I will move to Lobby.')
            body=json.loads(request.call_args.args[0].data)
            self.assertEqual(body['generationConfig']['responseJsonSchema']['properties']['destination_id']['enum'],['none','lobby'])
        self.assertTrue(client.lock.acquire(blocking=False));client.lock.release()

    def test_api_error_does_not_expose_provider_body(self):
        import urllib.error
        client=GeminiNavigator();client.key=lambda:'test-placeholder'
        error=urllib.error.HTTPError('https://example.com',403,'Denied',{},BytesIO(b'sensitive provider details'))
        with patch('urllib.request.urlopen',side_effect=error):
            with self.assertRaisesRegex(ValueError,'HTTP 403') as result:client.interpret('Go to lobby',[])
            self.assertNotIn('sensitive',str(result.exception))

    def test_audio_transcription_is_text_only_and_validates_format(self):
        client=GeminiNavigator();client.key=lambda:'test-placeholder'
        audio=base64.b64encode(b'RIFF'+b'0'*200).decode()
        with self.assertRaises(ValueError):client.transcribe(audio,'application/javascript')
        with self.assertRaises(ValueError):client.transcribe('not base64'*30,'audio/wav')
        result={'candidates':[{'content':{'parts':[{'text':'{"transcript":"Take me to the lobby."}'}]}}]}
        with patch('urllib.request.urlopen',return_value=BytesIO(json.dumps(result).encode())):
            self.assertEqual(client.transcribe(audio,'audio/webm;codecs=opus'),{'transcript':'Take me to the lobby.'})

    def test_relative_request_does_not_require_saved_places_and_is_bounded(self):
        client=GeminiNavigator();client.key=lambda:'test-placeholder'
        for distance in [1.,float('nan'),True,-1.,10.]:
            result=dict(action='move_relative',destination_id='none',distance_m=distance,reply='arbitrary text')
            body={'candidates':[{'content':{'parts':[{'text':json.dumps(result)}]}}]}
            with patch('urllib.request.urlopen',return_value=BytesIO(json.dumps(body).encode())):
                if distance==1. and distance is not True:
                    self.assertEqual(client.interpret('Move forward one meter',[])['reply'],'I will move forward 1 meter.')
                else:
                    with self.assertRaises(ValueError):client.interpret('Move forward',[])

if __name__=='__main__':unittest.main()

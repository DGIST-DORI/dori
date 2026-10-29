import json
import math
import queue
import sys
import threading
import time
import unittest
import urllib.request
import tempfile
from urllib.error import HTTPError
from pathlib import Path
from concurrent.futures import Future
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ros2_ws/src/dori_navigation'))
import rclpy
from nav_msgs.msg import OccupancyGrid, Odometry
from sensor_msgs.msg import LaserScan
from dori_web.bridge import WebBridge
from dori_web.geometry import free_cell, pose_values
from dori_web.http_server import ViewerServer


class WebViewer(unittest.TestCase):
    @classmethod
    def setUpClass(cls): rclpy.init()
    @classmethod
    def tearDownClass(cls): rclpy.shutdown()
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.node=WebBridge('mapping',Path(self.directory.name)/'goals.json')
    def tearDown(self):self.node.destroy_node();self.directory.cleanup()

    def test_raw_scan_without_map_or_odometry_and_with_old_map(self):
        scan=LaserScan();scan.header.frame_id='laser';scan.header.stamp=self.node.get_clock().now().to_msg()
        scan.angle_min=-1.;scan.angle_increment=.1;scan.range_min=.1;scan.range_max=16.;scan.ranges=[2.]*20
        self.node.receive('scan',scan);self.node.refresh()
        self.assertEqual(self.node.snapshot['frame'],'laser')
        self.assertEqual(len(self.node.snapshot['scan']),20)
        grid=OccupancyGrid();grid.header.frame_id='map';grid.info.width=grid.info.height=2;grid.info.resolution=.05;grid.info.origin.orientation.w=1.;grid.data=[0,100,-1,0]
        self.node.receive_map(grid);self.node.refresh()
        self.assertIsNotNone(self.node.snapshot['map'])
        self.assertEqual(self.node.snapshot['frame'],'map')
        self.assertIsNone(self.node.snapshot['robot'])
        self.assertTrue(self.node.snapshot['map_available'])
        self.assertEqual(len(self.node.snapshot['scan']),0)

    def test_nonfinite_telemetry_does_not_freeze_snapshot(self):
        self.node.values['pitch_deg'] = float('nan')
        self.node.refresh()
        self.assertIsNone(self.node.snapshot['values']['pitch_deg'])
        json.dumps(self.node.snapshot, allow_nan=False)

    def test_commands_require_navigation_mode_and_valid_pose(self):
        with self.assertRaises(ValueError):self.node.command(dict(action='goal',client='test-browser',x=0.,y=0.,yaw=0.))
        for pose in [dict(x=float('nan'),y=0,yaw=0),dict(x=True,y=0,yaw=0),dict(x=0,y=0)]:
            with self.assertRaises(ValueError):pose_values(pose)

    def test_rotated_map_bounds_and_unknown_cells(self):
        grid=OccupancyGrid();grid.info.width=grid.info.height=2;grid.info.resolution=1.;grid.data=[0,-1,100,0]
        grid.info.origin.position.x=3.;grid.info.origin.position.y=2.;grid.info.origin.orientation.z=math.sin(math.pi/4);grid.info.origin.orientation.w=math.cos(math.pi/4)
        free_cell(grid,2.5,2.5)
        for x,y in [(2.5,3.5),(1.5,2.5),(9.,9.)]:
            with self.assertRaises(ValueError):free_cell(grid,x,y)

    def test_controller_lease_is_exclusive_and_times_out(self):
        self.node.mode='navigation';self.node.readiness=lambda:[];self.node.mode_pub=Mock()
        self.node.command(dict(action='enable',client='browser-one'))
        with self.assertRaises(ValueError):self.node.command(dict(action='enable',client='browser-two'))
        self.node.lease_until=time.monotonic()-1;self.node.refresh()
        self.assertIsNone(self.node.owner)
        self.assertEqual(self.node.mode_pub.publish.call_args.args[0].data,0)

    def test_expired_http_request_is_not_executed(self):
        future=Future();future.cancel();self.node.commands.put(({'action':'stop'},future));self.node.command=Mock()
        self.node.process_commands();self.node.command.assert_not_called()

    def test_http_assets_csrf_and_restart_identity(self):
        self.node.refresh()
        server=ViewerServer(('127.0.0.1',0),self.node)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            with urllib.request.urlopen(base) as response:
                self.assertIn(b'<canvas',response.read())
                self.assertIn("frame-ancestors 'self'",response.headers['Content-Security-Policy'])
            data=json.load(urllib.request.urlopen(base+'/api/state'))
            self.assertEqual(data['instance_id'],self.node.instance_id)
            self.assertLess(data['server_age'],2.)
            for headers in [{},{'X-Dori-Control':server.csrf,'Origin':'http://untrusted.example'}]:
                request=urllib.request.Request(base+'/api/command',data=b'{"action":"stop","client":"test-browser"}',headers=headers)
                with self.assertRaises(HTTPError) as caught:urllib.request.urlopen(request)
                self.assertEqual(caught.exception.code,403)
            self.assertTrue(self.node.commands.empty())
            with self.assertRaises(HTTPError) as caught:urllib.request.urlopen(base+'/../bridge.py')
            self.assertEqual(caught.exception.code,404)
        finally:
            server.shutdown();server.server_close();thread.join(2)

    def test_named_goal_uses_stored_pose_and_existing_goal_publisher(self):
        grid=OccupancyGrid();grid.header.frame_id='map';grid.info.width=grid.info.height=10;grid.info.resolution=1.;grid.info.origin.orientation.w=1.;grid.data=[0]*100
        self.node.receive_map(grid);self.node.mode='navigation'
        goal=self.node.command(dict(action='save_destination',client='test-browser',name='Lobby',x=2.,y=3.,yaw=.2))['destination']
        self.node.owner='test-browser';self.node.values['enabled']=True;self.node.readiness=lambda:[];self.node.goal_pub=Mock()
        self.node.command(dict(action='named_goal',client='test-browser',id=goal['id'],x=9.,y=9.,yaw=0.))
        pose=self.node.goal_pub.publish.call_args.args[0]
        self.assertEqual((pose.pose.position.x,pose.pose.position.y),(2.,3.))
        self.assertEqual(self.node.selected_goal_name,'Lobby')

    def test_user_port_cannot_edit_destinations_or_initial_pose(self):
        self.node.refresh();server=ViewerServer(('127.0.0.1',0),self.node,role='user')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        base='http://127.0.0.1:'+str(server.server_port)
        try:
            self.assertIn(b'Your robot guide',urllib.request.urlopen(base).read())
            for action in ('save_destination','delete_destination','initial_pose','goal'):
                request=urllib.request.Request(base+'/api/command',data=json.dumps(dict(action=action,client='user-browser')).encode(),headers={'X-Dori-Control':server.csrf})
                with self.assertRaises(HTTPError) as result:urllib.request.urlopen(request)
                self.assertEqual(result.exception.code,403)
            self.assertTrue(self.node.commands.empty())
        finally:server.shutdown();server.server_close();thread.join(2)

    def test_relative_goal_uses_dori_heading_and_rejects_motion_or_obstacles(self):
        grid=OccupancyGrid();grid.header.frame_id='map';grid.info.width=grid.info.height=10;grid.info.resolution=1.;grid.info.origin.orientation.w=1.;grid.data=[0]*100
        self.node.receive_map(grid);self.node.mode='navigation';self.node.readiness=lambda:[]
        self.node.owner='test-browser';self.node.values['enabled']=True;self.node.goal_pub=Mock()
        self.node.messages['odom']=Odometry();self.node.tf_pose=lambda *_:[2.,3.,math.pi/2]
        self.node.relative_goal_pub=Mock()
        request=dict(action='relative_goal',client='test-browser',distance_m=1.,x=9.,y=9.,yaw=0.)
        result=self.node.command(request)
        self.assertAlmostEqual(result['target'][0],2.);self.assertAlmostEqual(result['target'][1],4.)
        self.assertEqual(result['reply'],'I will move forward 1 meter.')
        self.node.goal_pub.publish.assert_not_called()
        self.assertEqual(self.node.relative_goal_pub.publish.call_count,1)
        self.node.relative_goal_pub.reset_mock()
        self.node.goal_pub.reset_mock()
        for invalid in [True,float('nan'),-.5,0.,10.]:
            with self.assertRaises(ValueError):self.node.command(dict(request,distance_m=invalid))
        self.node.values['active']=True
        with self.assertRaises(ValueError):self.node.command(request)
        self.node.values['active']=False;self.node.values['retry']='{"state":"waiting"}'
        with self.assertRaises(ValueError):self.node.command(request)
        self.node.values['retry']='{}';self.node.messages['odom'].twist.twist.linear.x=.1
        with self.assertRaises(ValueError):self.node.command(request)
        self.node.messages['odom'].twist.twist.linear.x=0.;grid.data[42]=100
        with self.assertRaises(ValueError):self.node.command(request)
        self.node.goal_pub.publish.assert_not_called()
        self.node.relative_goal_pub.publish.assert_not_called()

if __name__=='__main__':unittest.main()

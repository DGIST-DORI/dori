#!/usr/bin/env python3
"""LiDAR + real Nav2/control + HTTP goal interface, software plant in domain 95 only."""
import argparse,json,math,os,signal,subprocess,threading,time,tempfile,sys
import urllib.request
from urllib.error import HTTPError
from pathlib import Path
if os.getenv('ROS_DOMAIN_ID')!='95' or os.getenv('ROS_LOCALHOST_ONLY')!='1':raise RuntimeError('Use isolated domain 95')
import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from sensor_msgs.msg import JointState,LaserScan,Imu
from control_msgs.msg import DynamicJointState,InterfaceValue
from geometry_msgs.msg import PoseWithCovarianceStamped
from std_msgs.msg import Int32,String
from dori_msgs.msg import MitCommand
from nav_msgs.msg import Odometry
from lifecycle_msgs.srv import GetState
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from drive_contract import check_drive_contract


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--hri-test',action='store_true',help='Real BT, offline LLM, TTS publish path and Nav2; inject an STT transcript')
    parser.add_argument('--motor-dynamics',action='store_true')
    parser.add_argument('--calibrated-response',action='store_true',help='Use measured joystick deadzone and ground response instead of ideal wheel kinematics')
    parser.add_argument('--goal-x',type=float,default=.8)
    parser.add_argument('--reverse-recovery',action='store_true')
    parser.add_argument('--blocked-rear',action='store_true')
    parser.add_argument('--heading-test',action='store_true',help='Verify opposing goal headings do not cause alignment loops')
    parser.add_argument('--retry-test',action='store_true',help='Remove a transient goal obstacle during the automatic retry wait')
    parser.add_argument('--relative-test',action='store_true',help='Real Gemini forward distance -> public relative goal -> Nav2')
    parser.add_argument('--auto-alignment-test',action='store_true',help='Repair a small AMCL drift without movement or odometry reset')
    parser.add_argument('--offline-intent',action='store_true',help='Use a fixed intent fixture; no Gemini/API dependency')
    parser.add_argument('--web-user-test',action='store_true',help='Real Gemini -> registered goal -> existing navigation pipeline')
    args=parser.parse_args();goal_x=args.goal_x
    (ROOT/'log').mkdir(exist_ok=True)
    if args.relative_test:args.web_user_test=True
    if args.offline_intent and not args.web_user_test:parser.error('--offline-intent requires --web-user-test or --relative-test')
    if args.blocked_rear and not args.reverse_recovery:parser.error('--blocked-rear requires --reverse-recovery')
    processes=[];handles=[];passed=False;trace=[]
    with tempfile.TemporaryDirectory() as td:
        d=Path(td);img=Image.new('L',(200,200),254);draw=ImageDraw.Draw(img);draw.rectangle((0,0,199,199),outline=0,width=2);img.save(d/'map.pgm')
        mp=d/'map.yaml';mp.write_text('image: map.pgm\nresolution: 0.05\norigin: [-5, -5, 0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n')
        params=[];heading_comparison={}
        if args.heading_test:
            import yaml,copy
            settings=yaml.safe_load((ROOT/'ros2_ws/src/dori_navigation/config/nav2_real.yaml').read_text())
            planner=settings['planner_server']['ros__parameters']
            planner['planner_plugins'].append('ExactHeading')
            planner['ExactHeading']=copy.deepcopy(planner['GridBased'])
            planner['ExactHeading']['plugin']='nav2_smac_planner/SmacPlannerHybrid'
            (d/'nav.yaml').write_text(yaml.safe_dump(settings));params=['params_file:='+str(d/'nav.yaml')]
        points=d/'points.csv';points.write_text('name,x,y,yaw_deg,frame_id\nalpha,0.8,0,0,map\n')
        rclpy.init();n=Node('software_lidar_web_dori_test');executor=SingleThreadedExecutor();executor.add_node(n)
        joint=n.create_publisher(JointState,'/joint_states',20);scan=n.create_publisher(LaserScan,'/scan',10)
        imu=n.create_publisher(Imu,'/imu/data_raw',20)
        dynamic=n.create_publisher(DynamicJointState,'/dynamic_joint_states',20)
        initial=n.create_publisher(PoseWithCovarianceStamped,'/initialpose',10)
        mode=n.create_publisher(Int32,'/NAVIGATION_MODE',10);text=n.create_publisher(String,'/NAVIGATION_TEXT',10)
        state={'target_l':0.,'target_r':0.,'torque_l':0.,'torque_r':0.,'x':0.0,'y':0.0,'yaw':0.0,'l':0.0,'r':0.0,'vl':0.0,'vr':0.0,'last':time.monotonic(),'command':0.0,'status':[],'odom':None,'distance':0.0}
        state['hri_states']=[];state['speech']=[];state['locations']=[]
        stt=n.create_publisher(String,'/dori/stt/result',10)
        n.create_subscription(String,'/dori/hri/manager_state',lambda m:state['hri_states'].append(json.loads(m.data)['state']),10)
        n.create_subscription(String,'/dori/tts/audio_event',lambda m:state['speech'].append(json.loads(m.data)),10)
        from rclpy.qos import QoSProfile,DurabilityPolicy
        n.create_subscription(String,'/dori/nav/locations',lambda m:state.update(locations=json.loads(m.data).get('goals',[])),QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL))
        state.update(reverse_distance=0.,backup_seen=False,block_rear=False,block_goal=False)
        def on_motor(m):
            side='l' if m.motor_id==1 else 'r'
            state['target_'+side]=m.v_des;state['torque_'+side]=m.tau_ff;state['command']=time.monotonic()
        n.create_subscription(MitCommand,'/bldc_mit_speed_cmd',on_motor,100)
        n.create_subscription(String,'/named_goal_status',lambda m:state['status'].append(m.data),10)
        n.create_subscription(Odometry,'/odom',lambda m:state.update(odom=m),20)
        def plant():
            now=time.monotonic();dt=min(now-state['last'],0.05);state['last']=now
            for side in ('l','r'):
                target=state['target_'+side] if now-state['command']<.3 else 0.
                if args.motor_dynamics:
                    actual=state['v'+side]
                    torque=3.*(target-actual)+(math.copysign(.35,target) if abs(target)>.05 else 0.)
                    torque+=state['torque_'+side] if now-state['command']<.3 else 0.
                    friction=1.3
                    if abs(actual)<.001 and abs(torque)<friction:
                        actual=0.
                    else:
                        next_actual=actual+dt*(torque-math.copysign(friction,actual if abs(actual)>.001 else torque)-.3*actual)/.4
                        actual=0. if next_actual*actual<0 and abs(torque)<friction else next_actual
                    state['v'+side]=actual
                else:state['v'+side]=target
            if args.calibrated_response or args.reverse_recovery or args.heading_test or args.web_user_test or args.retry_test:
                # Deliberately blocked forward travel until a real BackUp action
                # moves 25cm; manual-calibrated response after the drive limiter.
                u=.234*(state['target_l']+state['target_r'])/2/1.72
                turn=.234*(state['target_r']-state['target_l'])/.184/7.
                v=.62*math.copysign(max(abs(u)-.22,0.),u)
                w=1.67*turn
                if args.reverse_recovery and v>0 and state['reverse_distance']<.25:v=w=0.
                if v<0:state['reverse_distance']+=abs(v)*dt;state['backup_seen']=True
                state['vl']=(v-w*.184/2)/.234;state['vr']=(v+w*.184/2)/.234
            vl,vr=state['vl'],state['vr']
            state['l']+=vl*dt;state['r']+=vr*dt
            ds=0.234*(vl+vr)/2*dt;da=0.234*(vr-vl)/0.184*dt
            scale=1 if abs(da)<1e-9 else math.sin(da/2)/(da/2)
            state['x']+=ds*scale*math.cos(state['yaw']+da/2);state['y']+=ds*scale*math.sin(state['yaw']+da/2);state['yaw']+=da
            state['distance']+=abs(ds)
            stamp=n.get_clock().now().to_msg()
            msg=JointState();msg.header.stamp=stamp;msg.name=['left_wheel_joint','right_wheel_joint']
            msg.position=[math.remainder(state['l'],8*math.pi),math.remainder(state['r'],8*math.pi)];msg.velocity=[vl,vr]
            feedback=DynamicJointState();feedback.header.stamp=stamp;feedback.joint_names=msg.name
            feedback.interface_values=[InterfaceValue(interface_names=['feedback_age','position','velocity'],
                values=[.001,position,velocity]) for position,velocity in zip(msg.position,msg.velocity)]
            dynamic.publish(feedback);joint.publish(msg)
            im=Imu();im.header.stamp=stamp;im.header.frame_id='imu_link'
            im.linear_acceleration.z=-9.81
            im.angular_velocity.x=0.0007306980937549932
            im.angular_velocity.y=-0.003114453466490671
            im.angular_velocity.z=-da/dt-0.0007333547067765802
            imu.publish(im)
        def laser():
            msg=LaserScan();msg.header.stamp=n.get_clock().now().to_msg();msg.header.frame_id='laser'
            msg.angle_min=-math.pi;msg.angle_increment=2*math.pi/360;msg.angle_max=msg.angle_min+359*msg.angle_increment
            msg.range_min=0.1;msg.range_max=16.0;msg.scan_time=0.1
            ranges=[]
            for i in range(360):
                a=state['yaw']+math.pi+msg.angle_min+i*msg.angle_increment;cx,sy=math.cos(a),math.sin(a)
                dx=((4.9 if cx>=0 else -4.9)-state['x'])/cx if abs(cx)>1e-8 else 1e9
                dy=((4.9 if sy>=0 else -4.9)-state['y'])/sy if abs(sy)>1e-8 else 1e9
                ranges.append(max(0.1,min(dx,dy,16.0)))
            if state['block_rear']:ranges[180]=.40
            if state['block_goal']:
                for i in [0,1,359]:ranges[i]=goal_x
            msg.ranges=ranges;scan.publish(msg)
        n.create_timer(0.02,plant);n.create_timer(0.1,laser)
        thread=threading.Thread(target=executor.spin,daemon=True);thread.start()
        def start(label,cmd):
            f=(ROOT/'log'/('software_lidar_web_'+label+'.log')).open('w');handles.append(f)
            p=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,start_new_session=True);processes.append(p)
        def wait(predicate,label,timeout):
            end=time.monotonic()+timeout
            while time.monotonic()<end:
                if any(p.poll() is not None for p in processes):raise RuntimeError('Test node exited; inspect software_lidar_web_*.log')
                if predicate():return
                time.sleep(0.1)
            raise AssertionError(label+' '+str({k:v for k,v in state.items() if k!='odom'}))
        try:
            start('supervisor',['ros2','run','dori_supervisor','mode_manager_node'])
            start('drive',['ros2','run','dori_drive','drive_controller_node','--ros-args','--params-file',str(ROOT/'ros2_ws/src/dori_drive/config/drive_params.yaml'),'--params-file',str(ROOT/'ros2_ws/src/dori_drive/config/kinematics.yaml'),'-p','feedforward_enabled:=false'])
            start('odometry',['ros2','launch','dori_mapping','lidar_odometry.launch.py'])
            wait(lambda:state['odom'] is not None,'lidar odometry missing',30)
            start('nav2',['ros2','launch','dori_navigation','real_nav2.launch.py','map:='+str(mp),'named_goals_file:='+str(d/'web_goals.json'),'goal_source:=web','publish_laser_tf:=false']+params)
            start('web',['/usr/bin/python3',str(ROOT/'ros2_ws/src/dori_navigation/scripts/web_viewer.py'),'--mode','navigation','--host','127.0.0.1','--port','18080','--user-port','18070' if args.web_user_test else '0','--goals-file',str(d/'web_goals.json')]+(['--ros-args','-p','auto_alignment.period_s:=5.0'] if args.auto_alignment_test else []))
            if args.hri_test:
                start('voice',['ros2','launch','dori_bringup','voice.launch.py','enable_stt:=false','tts_playback_mode:=publish_only'])
                start('hri',['ros2','launch','dori_bringup','interaction.launch.py'])
            client=n.create_client(GetState,'/amcl/get_state')
            wait(lambda:client.service_is_ready(),'AMCL discovery',20)
            end=time.monotonic()+45
            while time.monotonic()<end:
                f=client.call_async(GetState.Request())
                response_deadline=time.monotonic()+2
                while not f.done() and time.monotonic()<response_deadline:time.sleep(.05)
                if not f.done():
                    client.remove_pending_request(f);f.cancel();continue
                if f.result().current_state.id==3:break
                time.sleep(0.3)
            else:raise AssertionError('AMCL did not activate')
            def wait_future(future,timeout):
                deadline=time.monotonic()+timeout
                while not future.done() and time.monotonic()<deadline:time.sleep(.01)
            base='http://127.0.0.1:18080'
            session={}
            def web_started():
                try:session.update(json.load(urllib.request.urlopen(base+'/api/session',timeout=1)));return True
                except OSError:return False
            wait(web_started,'Web HTTP startup',30)
            public_session={}
            def request(action,public=False,**data):
                body=json.dumps(dict(action=action,client='isolated-test-browser',**data)).encode()
                target='http://127.0.0.1:18070' if public else base
                req=urllib.request.Request(target+'/api/command',data=body,headers={'Content-Type':'application/json','X-Dori-Control':(public_session if public else session)['csrf']})
                deadline=time.monotonic()+5
                while True:
                    try: return json.load(urllib.request.urlopen(req,timeout=3))
                    except HTTPError as exc:
                        message=exc.read().decode()
                        if (action not in ('enable','goal') or time.monotonic()>deadline or
                                not any(reason in message for reason in ('미수신/지연','위치 추정 지연','Nav2 시작 대기'))):
                            raise AssertionError(message) from exc
                        time.sleep(.2)
            def snapshot(): return json.load(urllib.request.urlopen(base+'/api/state',timeout=3))
            wait(lambda:snapshot().get('map_available'),'web map missing',15)
            # Map and sensor discovery are independent DDS streams. A latched
            # map may arrive before the first live LiDAR sample in a new viewer.
            def sensors_ready():
                sensors=snapshot()['sensors']
                return all(sensors[key]['age'] is not None and 0<=sensors[key]['age']<limit
                           and sensors[key]['hz']>0 for key,limit in [('scan',.4),('odom',.25)])
            wait(sensors_ready,'web scan/odometry discovery',15)
            request('initial_pose',x=.65,y=-.5,yaw=.6) if args.reverse_recovery else request('initial_pose',x=0.,y=0.,yaw=0.)
            wait(lambda:not snapshot()['readiness'],'web navigation readiness',30)
            contract=check_drive_contract(n,wait_future)
            assert contract['ok'],contract
            if args.auto_alignment_test:
                corrections_before=snapshot()['auto_alignment']['corrections']
                wrong=PoseWithCovarianceStamped();wrong.header.frame_id='map';wrong.header.stamp=n.get_clock().now().to_msg()
                wrong.pose.pose.position.x=.18;wrong.pose.pose.position.y=.08
                wrong.pose.pose.orientation.z=math.sin(.06/2);wrong.pose.pose.orientation.w=math.cos(.06/2)
                wrong.pose.covariance[0]=wrong.pose.covariance[7]=wrong.pose.covariance[35]=1e-8
                initial.publish(wrong)
                wait(lambda:math.hypot(*snapshot()['robot'][:2])>.15,'injected AMCL drift did not appear',5)
                wait(lambda:snapshot()['auto_alignment']['corrections']>corrections_before,'automatic alignment did not apply',30)
                wait(lambda:not snapshot()['readiness'],'alignment settling',5)
                observed=snapshot();pose=observed['robot'];alignment=observed['auto_alignment']
                assert math.hypot(*pose[:2])<.10 and abs(pose[2])<.04,pose
                assert state['distance']<.01 and not observed['values'].get('active'),'Alignment commanded robot motion'
                od=state['odom'].pose.pose.position
                assert math.hypot(od.x,od.y)<.02,'Alignment changed the local odometry origin'
                report=dict(ok=True,plant='software only, no physical motors',injected_pose=[.18,.08,.06],final_pose=pose,
                    alignment=alignment,distance_traveled_m=state['distance'],local_odom=[od.x,od.y])
                (ROOT/'log/auto_alignment_validation.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));passed=True
                return
            if args.heading_test:
                from rclpy.action import ActionClient
                from nav2_msgs.action import ComputePathToPose
                client=ActionClient(n,ComputePathToPose,'/compute_path_to_pose')
                assert client.wait_for_server(timeout_sec=5)
                for planner_id in ('ExactHeading','GridBased'):
                    g=ComputePathToPose.Goal();g.use_start=True;g.planner_id=planner_id
                    g.start.header.frame_id=g.goal.header.frame_id='map'
                    g.start.header.stamp=g.goal.header.stamp=n.get_clock().now().to_msg()
                    g.start.pose.orientation.w=1.;g.goal.pose.position.x=goal_x
                    g.goal.pose.orientation.z=math.sin(math.radians(150)/2);g.goal.pose.orientation.w=math.cos(math.radians(150)/2)
                    f=client.send_goal_async(g);wait(f.done,'plan acceptance',5)
                    assert f.result().accepted
                    result=f.result().get_result_async();wait(result.done,'plan comparison',8)
                    path=result.result().result.path;assert path.poses
                    heading_comparison[planner_id]=sum(math.hypot(b.pose.position.x-a.pose.position.x,b.pose.position.y-a.pose.position.y) for a,b in zip(path.poses,path.poses[1:]))
                assert heading_comparison['GridBased']<goal_x+.2,heading_comparison
                assert heading_comparison['GridBased']<=heading_comparison['ExactHeading']+.001,heading_comparison
                print('Heading path comparison:',heading_comparison,flush=True)
            named_goal=None
            if args.web_user_test:
                public_session.update(json.load(urllib.request.urlopen('http://127.0.0.1:18070/api/session')))
                if not args.relative_test:
                    named_goal=request('save_destination',name='Lobby',x=goal_x,y=0.,yaw=0.)['destination']
                    wait(lambda:len(snapshot().get('destinations',[]))==1,'named destination publication',3)
                phrase=f'Move forward {goal_x:g} meters.' if args.relative_test else 'Please take me to the lobby.'
                req=urllib.request.Request('http://127.0.0.1:18070/api/chat',data=json.dumps({'text':phrase}).encode(),headers={'Content-Type':'application/json','X-Dori-Control':public_session['csrf']})
                if args.offline_intent:
                    intent=dict(action='move_relative',distance_m=goal_x) if args.relative_test else dict(action='navigate',destination_id=named_goal['id'])
                else:
                    intent=json.load(urllib.request.urlopen(req,timeout=20))
                if args.relative_test:assert intent['action']=='move_relative' and intent['distance_m']==goal_x,intent
                else:assert intent['action']=='navigate' and intent['destination_id']==named_goal['id'],intent
                print('Intent selection ('+('fixture' if args.offline_intent else 'Gemini')+'):',intent,flush=True)
            if args.hri_test:
                request('save_destination',name='Lobby',x=goal_x,y=0.,yaw=0.)
                wait(lambda:len(state['locations'])==1 and stt.get_subscription_count()>0,'HRI registry/startup',10)
                stt.publish(String(data=json.dumps(dict(text='hello',confidence=1.,event='stt_result'))))
                wait(lambda:'RESPONDING' in state['hri_states'] and state['hri_states'][-1]=='IDLE','HRI question answer',10)
                assert state['distance']<.01,'Q&A caused movement'
                stt.publish(String(data=json.dumps(dict(text='Please take me to Lobby',confidence=1.,event='stt_result'))))
            else:
                request('enable',public=args.web_user_test)
            wait(lambda:snapshot()['values'].get('enabled'),'mode acknowledgement',5)
            state['block_rear']=args.blocked_rear or args.retry_test
            state['block_goal']=args.retry_test
            if args.retry_test:time.sleep(1.5)  # Allow the real obstacle costmap to mark the occupied goal.
            if args.hri_test:pass
            elif args.relative_test:request('relative_goal',public=True,distance_m=intent['distance_m'])
            elif args.web_user_test:request('named_goal',public=True,id=named_goal['id'])
            else:request('goal',x=goal_x,y=0.,yaw=math.radians(150) if args.heading_test else 0.)
            retry_started=None;retry_distance=None;retry_resumed=None
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                if not args.hri_test:request('heartbeat')
                observed=snapshot();od=state['odom'];q=od.pose.pose.orientation
                retry=json.loads(observed['values'].get('retry','{}'))
                if retry.get('state')=='waiting':
                    if retry_started is None:retry_started=time.monotonic();retry_distance=state['distance']
                    assert not observed['values'].get('active'),'Retry wait enabled motor output'
                    assert state['distance']-retry_distance<.03,'Robot moved during retry wait'
                    if args.retry_test and time.monotonic()-retry_started>2:state['block_goal']=state['block_rear']=False
                elif retry_started and retry_resumed is None and observed['values'].get('active'):
                    retry_resumed=time.monotonic()
                trace.append({'t':time.monotonic(), 'truth':[state['x'],state['y'],state['yaw']],
                              'odom':[od.pose.pose.position.x,od.pose.pose.position.y,math.atan2(2*q.w*q.z,1-2*q.z*q.z)],
                              'web_pose':observed.get('robot'), 'values':observed['values'],
                              'velocities':observed['velocities'], 'wheels':[state['vl'],state['vr']],
                              'wheel_targets':[state['target_l'],state['target_r']]})
                if len(trace)%4==0:
                    (ROOT/'log/lidar_web_navigation_trace.json').write_text(json.dumps(trace,indent=2)+'\n')
                terminal='finished:'+('relative_goal' if args.relative_test else 'rviz_goal')+':status='+('6' if args.blocked_rear else '4')
                if (args.hri_test and 'ARRIVED' in state['hri_states']) or (not args.hri_test and terminal in state['status']):break
                if any(p.poll() is not None for p in processes):raise AssertionError('Test process exited')
                time.sleep(.5)
            else:raise AssertionError('Web goal did not succeed: '+str(state['status']))
            time.sleep(0.4)
            distance_to_goal=math.hypot(state['x']-goal_x,state['y'])
            if args.blocked_rear:
                assert not state['backup_seen'] and state['reverse_distance']==0.,'Rear obstacle did not inhibit reverse'
                assert state['distance']<.03,'Blocked robot moved'
            else:assert state['distance']>0.3 and distance_to_goal<0.3,state
            if args.relative_test:assert distance_to_goal<.15,'Relative move stopped too early'
            assert abs(state['vl'])<.01 and abs(state['vr'])<.01,'wheels did not stop at goal'
            od=state['odom'].pose.pose.position
            assert math.hypot(od.x-state['x'],od.y-state['y']) < .08, 'LiDAR metric accuracy failed'
            if args.heading_test:
                assert state['distance']<goal_x+.4 and abs(state['yaw'])<.2,'Unnecessary heading alignment loop'
            if args.retry_test:
                assert retry_started is not None and retry_resumed is not None,'No automatic retry occurred'
                assert retry_resumed-retry_started>=4.3,'Retry did not wait for the configured delay'
            if args.reverse_recovery and not args.blocked_rear:
                assert state['backup_seen'] and state['reverse_distance']>=.25,'No reverse recovery occurred'
                assert state['reverse_distance']<.60,'Reverse recovery was not bounded'
            request('stop')
            wait(lambda:not snapshot()['values'].get('enabled'),'stop acknowledgement',3)
            request('enable')
            wait(lambda:snapshot()['values'].get('enabled'),'reenable',3)
            # No heartbeat: browser loss must cancel its own navigation session.
            wait(lambda:not snapshot()['values'].get('enabled'),'browser lease expiry',13)
            report={'ok':True,'web_goal':True,'web_stop':True,'lease_expiry':True,'plant':'software only, no physical motors','nav2_result':'ABORTED_REAR_BLOCKED' if args.blocked_rear else 'SUCCEEDED','web_user_test':args.web_user_test,'heading_test':args.heading_test,'heading_path_lengths_m':heading_comparison,'distance_traveled_m':state['distance'],'motor_dynamics':args.motor_dynamics,'reverse_recovery':args.reverse_recovery,'blocked_rear':args.blocked_rear,'reverse_distance_m':state['reverse_distance'],'goal_x':goal_x,
                    'final_xy':[state['x'],state['y']],'distance_to_goal_m':distance_to_goal,
                    'lidar_odom_position_error_m':math.hypot(od.x-state['x'],od.y-state['y'])}
            if args.hri_test:
                assert state['hri_states'][-1]=='IDLE' and 'GUIDING' in state['hri_states'],state['hri_states']
                assert any('목적지에 도착' in json.dumps(m,ensure_ascii=False) for m in state['speech'])
            report.update(hri_test=args.hri_test,hri_states=state['hri_states'],speech_events=state['speech'],relative_test=args.relative_test,retry_test=args.retry_test,intent_provider='fixture' if args.offline_intent else 'Gemini' if args.web_user_test else None,
                retry_wait_seconds=retry_resumed-retry_started if retry_resumed else None,nav2_status=state['status'],
                drive_contract=contract,calibrated_response=args.calibrated_response or args.reverse_recovery or args.heading_test or args.web_user_test or args.retry_test)
            (ROOT/'log/lidar_web_navigation_results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));passed=True
        except Exception as error:
            report={'ok':False,'plant':'software only, no physical motors','error':str(error),'final_xy':[state['x'],state['y']],'distance_to_goal_m':math.hypot(state['x']-goal_x,state['y']),'nav2_status':state['status']}
            (ROOT/'log/lidar_web_navigation_results.json').write_text(json.dumps(report,indent=2)+'\n')
            print('TEST FAILURE:',repr(error),flush=True)
            raise
        finally:
            (ROOT/'log/lidar_web_navigation_trace.json').write_text(json.dumps(trace,indent=2)+'\n')
            if rclpy.ok():
                mode.publish(Int32(data=0));time.sleep(0.2)
            for p in reversed(processes):
                if p.poll() is None:p.send_signal(signal.SIGINT)
            for p in processes:
                try:p.wait(timeout=8)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=3)
            for f in handles:f.close()
            for timer in n.timers:timer.cancel()
            executor.shutdown(timeout_sec=3);thread.join(timeout=3);n.destroy_node()
            if rclpy.ok():rclpy.shutdown()
            if not passed:print('Inspect log/software_lidar_web_*.log for details')

if __name__=='__main__':main()

#!/usr/bin/env python3
"""Real Nav2 + real control/odometry nodes driving a software plant, domain 93 only."""
import json,math,os,signal,subprocess,threading,time,tempfile
from pathlib import Path
if os.getenv('ROS_DOMAIN_ID')!='93' or os.getenv('ROS_LOCALHOST_ONLY')!='1':raise RuntimeError('Use isolated domain 93')
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from sensor_msgs.msg import JointState,LaserScan
from control_msgs.msg import DynamicJointState,InterfaceValue
from geometry_msgs.msg import PoseWithCovarianceStamped
from std_msgs.msg import Int32,String
from robot_msgs.msg import MitCommand
from nav_msgs.msg import Odometry
from lifecycle_msgs.srv import GetState
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1]


def main():
    processes=[];handles=[];passed=False
    with tempfile.TemporaryDirectory() as td:
        d=Path(td);img=Image.new('L',(200,200),254);draw=ImageDraw.Draw(img);draw.rectangle((0,0,199,199),outline=0,width=2);img.save(d/'map.pgm')
        mp=d/'map.yaml';mp.write_text('image: map.pgm\nresolution: 0.05\norigin: [-5, -5, 0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n')
        points=d/'points.csv';points.write_text('name,x,y,yaw_deg,frame_id\nalpha,0.8,0,0,map\n')
        rclpy.init();n=Node('software_robot_test');executor=MultiThreadedExecutor(num_threads=4);executor.add_node(n)
        joint=n.create_publisher(JointState,'/joint_states',20);scan=n.create_publisher(LaserScan,'/scan',10)
        dynamic=n.create_publisher(DynamicJointState,'/dynamic_joint_states',20)
        initial=n.create_publisher(PoseWithCovarianceStamped,'/initialpose',10)
        mode=n.create_publisher(Int32,'/NAVIGATION_MODE',10);text=n.create_publisher(String,'/NAVIGATION_TEXT',10)
        state={'x':0.0,'y':0.0,'yaw':0.0,'l':0.0,'r':0.0,'vl':0.0,'vr':0.0,'last':time.monotonic(),'command':0.0,'status':[],'odom':None,'distance':0.0}
        def on_motor(m):
            state['vl' if m.motor_id==1 else 'vr']=m.v_des;state['command']=time.monotonic()
        n.create_subscription(MitCommand,'/bldc_mit_speed_cmd',on_motor,100)
        n.create_subscription(String,'/named_goal_status',lambda m:state['status'].append(m.data),10)
        n.create_subscription(Odometry,'/odom',lambda m:state.update(odom=m),20)
        def plant():
            now=time.monotonic();dt=min(now-state['last'],0.05);state['last']=now
            vl,vr=(state['vl'],state['vr']) if now-state['command']<0.3 else (0.0,0.0)
            state['l']+=vl*dt;state['r']+=vr*dt
            ds=0.234*(vl+vr)/2*dt;da=0.234*(vr-vl)/0.184*dt
            scale=1 if abs(da)<1e-9 else math.sin(da/2)/(da/2)
            state['x']+=ds*scale*math.cos(state['yaw']+da/2);state['y']+=ds*scale*math.sin(state['yaw']+da/2);state['yaw']+=da
            state['distance']+=abs(ds)
            stamp=n.get_clock().now().to_msg()
            msg=JointState();msg.header.stamp=stamp;msg.name=['left_wheel_joint','right_wheel_joint']
            msg.position=[math.remainder(state['l'],8*math.pi),math.remainder(state['r'],8*math.pi)];msg.velocity=[vl,vr]
            feedback=DynamicJointState();feedback.header.stamp=stamp;feedback.joint_names=msg.name
            feedback.interface_values=[InterfaceValue(interface_names=['feedback_age'],values=[0.001]) for _ in range(2)]
            dynamic.publish(feedback);joint.publish(msg)
        def laser():
            msg=LaserScan();msg.header.stamp=n.get_clock().now().to_msg();msg.header.frame_id='laser'
            msg.angle_min=-math.pi;msg.angle_increment=2*math.pi/360;msg.angle_max=msg.angle_min+359*msg.angle_increment
            msg.range_min=0.1;msg.range_max=16.0;msg.scan_time=0.1
            ranges=[]
            for i in range(360):
                a=state['yaw']+msg.angle_min+i*msg.angle_increment;cx,sy=math.cos(a),math.sin(a)
                dx=((4.9 if cx>=0 else -4.9)-state['x'])/cx if abs(cx)>1e-8 else 1e9
                dy=((4.9 if sy>=0 else -4.9)-state['y'])/sy if abs(sy)>1e-8 else 1e9
                ranges.append(max(0.1,min(dx,dy,16.0)))
            msg.ranges=ranges;scan.publish(msg)
        n.create_timer(0.02,plant);n.create_timer(0.1,laser)
        thread=threading.Thread(target=executor.spin,daemon=True);thread.start()
        def start(label,cmd):
            f=(ROOT/'log'/('software_'+label+'.log')).open('w');handles.append(f)
            p=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,start_new_session=True);processes.append(p)
        def wait(predicate,label,timeout):
            end=time.monotonic()+timeout
            while time.monotonic()<end:
                if any(p.poll() is not None for p in processes):raise RuntimeError('Test node exited; inspect software_*.log')
                if predicate():return
                time.sleep(0.1)
            raise AssertionError(label+' '+str(state['status'][-5:]))
        try:
            start('supervisor',['ros2','run','robot_supervisor','mode_manager_node'])
            start('drive',['ros2','run','robot_drive','drive_controller_node','--ros-args','--params-file',str(ROOT/'src/robot_drive/config/drive_params.yaml'),'--params-file',str(ROOT/'src/robot_drive/config/kinematics.yaml'),'-p','feedforward_enabled:=false'])
            start('odometry',['ros2','launch','robot_drive','odometry.launch.py'])
            wait(lambda:state['odom'] is not None,'wheel odometry missing',10)
            start('nav2',['ros2','launch','robot_navigation','real_nav2.launch.py','map:='+str(mp),'named_points_file:='+str(points)])
            client=n.create_client(GetState,'/amcl/get_state')
            wait(lambda:client.service_is_ready(),'AMCL discovery',20)
            end=time.monotonic()+20
            while time.monotonic()<end:
                f=client.call_async(GetState.Request())
                wait(f.done,'AMCL state response',3)
                if f.result().current_state.id==3:break
                time.sleep(0.3)
            else:raise AssertionError('AMCL did not activate')
            msg=PoseWithCovarianceStamped();msg.header.frame_id='map';msg.header.stamp=n.get_clock().now().to_msg()
            msg.pose.pose.orientation.w=1.0;msg.pose.covariance[0]=0.0025;msg.pose.covariance[7]=0.0025;msg.pose.covariance[35]=0.005
            initial.publish(msg)
            wait(lambda:mode.get_subscription_count()>=3,'navigation subscribers',10)
            # Allow localization and costmaps to observe the initial pose.
            time.sleep(5)
            pre=subprocess.run(['python3',str(ROOT/'scripts/preflight.py'),'--stage','navigation','--duration','2'],capture_output=True,text=True)
            (ROOT/'docs/software_nav2_preflight.json').write_text(pre.stdout+pre.stderr)
            if pre.returncode:raise AssertionError('Real Nav2 preflight failed: '+pre.stdout+pre.stderr)
            text.publish(String(data='alpha'));time.sleep(0.2);mode.publish(Int32(data=1))
            wait(lambda:any(s=='finished:alpha:status=4' for s in state['status']),'Nav2 goal did not succeed',45)
            time.sleep(0.4)
            distance_to_goal=math.hypot(state['x']-0.8,state['y'])
            assert state['distance']>0.3 and distance_to_goal<0.3,state
            assert abs(state['vl'])<1e-6 and abs(state['vr'])<1e-6,'wheels did not stop at goal'
            od=state['odom'].pose.pose.position
            report={'ok':True,'plant':'software only, no physical motors','nav2_result':'SUCCEEDED',
                    'final_xy':[state['x'],state['y']],'distance_to_goal_m':distance_to_goal,
                    'wheel_odom_position_error_m':math.hypot(od.x-state['x'],od.y-state['y'])}
            (ROOT/'docs/real_nav2_software_results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));passed=True
        finally:
            mode.publish(Int32(data=0));time.sleep(0.2)
            for p in reversed(processes):
                if p.poll() is None:p.send_signal(signal.SIGINT)
            for p in processes:
                try:p.wait(timeout=8)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=3)
            for f in handles:f.close()
            executor.shutdown(timeout_sec=3);thread.join(timeout=3);n.destroy_node();rclpy.shutdown()
            if not passed:print('Inspect log/software_*.log for details')

if __name__=='__main__':main()

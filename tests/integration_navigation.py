#!/usr/bin/env python3
"""Isolated real supervisor/drive + Python bridges + fake Nav2 action server. No hardware."""
import os,sys,time,math,signal,subprocess,tempfile,threading,json
from pathlib import Path
if os.getenv('ROS_DOMAIN_ID')!='92' or os.getenv('ROS_LOCALHOST_ONLY')!='1':
    raise RuntimeError('Requires isolated ROS_DOMAIN_ID=92 ROS_LOCALHOST_ONLY=1')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/robot_navigation/scripts'))
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.action import ActionServer,GoalResponse,CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.qos import QoSProfile,DurabilityPolicy
from std_msgs.msg import String,Int32,Bool
from geometry_msgs.msg import Twist,TransformStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import LaserScan,JointState
from control_msgs.msg import DynamicJointState,InterfaceValue
from nav2_msgs.action import NavigateToPose
from robot_msgs.msg import MitCommand
from tf2_ros import TransformBroadcaster,StaticTransformBroadcaster
from text_llm_named_goal import TextLLMNamedGoal
from named_goal_bridge import NamedGoalBridge
from nav_drive_bridge import NavDriveBridge


def main():
    results=[];processes=[];logs=[]
    with tempfile.TemporaryDirectory() as td:
        points=Path(td)/'points.csv';points.write_text('name,x,y,yaw_deg,frame_id\nalpha,1,0,0,map\nbeta,0,1,90,map\n')
        rclpy.init(args=['--ros-args','-p','points_file:='+str(points)])
        n=Node('contract_test');llm=TextLLMNamedGoal();goals=NamedGoalBridge();bridge=NavDriveBridge()
        executor=MultiThreadedExecutor(num_threads=6)
        for node in [n,llm,goals,bridge]:executor.add_node(node)
        group=ReentrantCallbackGroup();server_state={'running':0,'max_running':0,'goals':0,'cancelled':0,'delay':False}
        def accept(request):
            if server_state['delay']:time.sleep(0.3)
            return GoalResponse.ACCEPT
        def execute(handle):
            server_state['running']+=1;server_state['goals']+=1
            server_state['max_running']=max(server_state['running'],server_state['max_running'])
            while rclpy.ok() and not handle.is_cancel_requested:time.sleep(0.01)
            if rclpy.ok():handle.canceled();server_state['cancelled']+=1
            server_state['running']-=1
            return NavigateToPose.Result()
        server=ActionServer(n,NavigateToPose,'/navigate_to_pose',execute_callback=execute,
                            goal_callback=accept,cancel_callback=lambda h:CancelResponse.ACCEPT,callback_group=group)
        latch=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        mode=n.create_publisher(Int32,'/NAVIGATION_MODE',10);text=n.create_publisher(String,'/NAVIGATION_TEXT',10)
        manual=n.create_publisher(Twist,'/manual/cmd_vel',10);nav=n.create_publisher(Twist,'/nav/cmd_vel',10)
        odom=n.create_publisher(Odometry,'/odom',10);scan=n.create_publisher(LaserScan,'/scan',10)
        estop=n.create_publisher(Bool,'/emergency_stop',10);ego=n.create_publisher(Bool,'/emergency_go',10)
        system_mode=n.create_publisher(Int32,'/control_mode_cmd',10)
        tf=TransformBroadcaster(n);static=StaticTransformBroadcaster(n)
        frames=TransformStamped();frames.header.frame_id='base_link';frames.child_frame_id='laser';frames.transform.rotation.w=1.0
        static.sendTransform(frames)
        values={'auto':None,'drive':None,'motors':{},'status':'','named':[],'mode':None}
        n.create_subscription(Twist,'/auto/cmd_vel',lambda m:values.update(auto=m),10)
        n.create_subscription(Twist,'/drive/cmd_vel',lambda m:values.update(drive=m),10)
        n.create_subscription(MitCommand,'/bldc_mit_speed_cmd',lambda m:values['motors'].update({m.motor_id:m.v_des}),100)
        n.create_subscription(String,'/navigation/drive_status',lambda m:values.update(status=m.data),latch)
        n.create_subscription(String,'/named_goal',lambda m:values['named'].append(m.data),10)
        n.create_subscription(Int32,'/system/control_mode',lambda m:values.update(mode=m.data),latch)
        feedback_pub=n.create_publisher(DynamicJointState,'/dynamic_joint_states',10)
        feed={'sensors':True,'command':True,'manual':True,'feedback':True}
        def pump():
            stamp=n.get_clock().now().to_msg()
            f=DynamicJointState();f.header.stamp=stamp;f.joint_names=['left_wheel_joint','right_wheel_joint']
            f.interface_values=[InterfaceValue(interface_names=['feedback_age'],values=[0.001 if feed['feedback'] else 0.5]) for _ in range(2)]
            feedback_pub.publish(f)
            if feed['sensors']:
                o=Odometry();o.header.stamp=stamp;o.header.frame_id='odom';o.child_frame_id='base_link';o.pose.pose.orientation.w=1.0;odom.publish(o)
                s=LaserScan();s.header.stamp=stamp;s.header.frame_id='laser';s.range_min=0.1;s.range_max=16.0;s.ranges=[3.0]*360;scan.publish(s)
                t=TransformStamped();t.header.stamp=stamp;t.header.frame_id='odom';t.child_frame_id='base_link';t.transform.rotation.w=1.0
                loc=TransformStamped();loc.header.stamp=stamp;loc.header.stamp.sec+=1;loc.header.frame_id='map';loc.child_frame_id='odom';loc.transform.rotation.w=1.0
                tf.sendTransform([t,loc])
            if feed['command']:
                c=Twist();c.linear.x=0.172;c.angular.z=0.7;nav.publish(c)
            if feed['manual']:manual.publish(Twist())
        n.create_timer(0.05,pump)
        thread=threading.Thread(target=executor.spin,daemon=True);thread.start()
        def wait(predicate,label,timeout=5):
            end=time.monotonic()+timeout
            while time.monotonic()<end:
                if predicate():return
                time.sleep(0.02)
            raise AssertionError(label+' '+str(values['status'])+' motors='+str(values['motors']))
        def start(pkg,exe,extra=[]):
            log=(Path(td)/(exe+'.log')).open('w');logs.append(log)
            p=subprocess.Popen(['ros2','run',pkg,exe]+extra,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);processes.append(p)
        try:
            start('robot_supervisor','mode_manager_node')
            start('robot_drive','drive_controller_node',['--ros-args','--params-file',str(ROOT/'src/robot_drive/config/kinematics.yaml'),'-p','feedforward_enabled:=false','-p','require_hardware_feedback:=true'])
            wait(lambda:values['mode']==0,'supervisor startup')
            text.publish(String(data='alpha'));time.sleep(0.1);mode.publish(Int32(data=1))
            wait(lambda:values['status']=='driving','navigation gates')
            wait(lambda:values['auto'] and abs(values['auto'].linear.x-0.1)<1e-6,'normalized units')
            wait(lambda:len(values['motors'])==2,'motor command output')
            time.sleep(1.2)
            assert abs(values['drive'].linear.x-0.1)<1e-6,'manual idle interrupted auto'
            expected={1:(0.172-0.7*0.184/2)/0.234,2:(0.172+0.7*0.184/2)/0.234}
            for i,v in expected.items():assert abs(values['motors'][i]-v)<0.02,(values['motors'],expected)
            results.append('SI→normalized→supervisor→wheel rad/s; joystick idle does not interrupt AUTO')
            feed['sensors']=False
            wait(lambda:values['status'] in ('stale_odom','stale_scan'),'sensor timeout')
            wait(lambda:all(abs(v)<1e-8 for v in values['motors'].values()),'sensor stop')
            feed['sensors']=True;wait(lambda:values['status']=='driving','sensor recovery')
            results.append('sensor freshness gate and immediate motor halt')
            feed['feedback']=False
            wait(lambda:all(abs(v)<1e-8 for v in values['motors'].values()),'CAN feedback loss stop')
            feed['feedback']=True
            wait(lambda:abs(values['motors'].get(1,0))>0.05,'CAN recovery')
            results.append('fresh ROS messages cannot mask stale per-wheel CAN feedback')
            text.publish(String(data='beta'));wait(lambda:server_state['goals']>=2,'replacement')
            assert server_state['max_running']==1,'overlapping goals'
            mode.publish(Int32(data=0));wait(lambda:server_state['running']==0,'mode-off cancellation')
            wait(lambda:all(abs(v)<1e-8 for v in values['motors'].values()),'mode-off halt')
            results.append('replacement serialized after cancellation; MODE=0 cancels action and stops wheels')
            # A mode-off event while action acceptance is delayed must cancel the late handle.
            server_state['delay']=True
            mode.publish(Int32(data=1));time.sleep(0.08);mode.publish(Int32(data=0))
            time.sleep(0.7);assert server_state['running']==0 and not bridge.goal_active
            server_state['delay']=False
            results.append('late action acceptance after cancellation cannot enable movement')
            # Slow old inference must not publish after newer request/mode-off.
            os.environ['OPENAI_API_KEY']='offline-test-only'
            entered=threading.Event();release=threading.Event()
            def slow_model(request):entered.set();release.wait(timeout=3);return 'alpha'
            llm.call_model=slow_model
            mode.publish(Int32(data=1));time.sleep(0.1)
            text.publish(String(data='slow inference'));wait(entered.is_set,'worker start')
            mode.publish(Int32(data=0));time.sleep(0.1);count=len(values['named']);release.set();time.sleep(0.3)
            assert len(values['named'])==count,'stale LLM result published'
            results.append('LLM in-flight result discarded atomically on mode-off')
            text.publish(String(data='alpha'));time.sleep(0.1);mode.publish(Int32(data=1))
            wait(lambda:values['status']=='driving','resume test')
            estop.publish(Bool(data=True));wait(lambda:server_state['running']==0,'estop action cancel')
            wait(lambda:all(abs(v)<1e-8 for v in values['motors'].values()),'estop motor stop')
            results.append('emergency stop cancels navigation and stops motor output')
            ego.publish(Bool(data=True));wait(lambda:values['mode']==0,'manual recovery')
            # Ignore auto packets while manual input is active.
            feed['manual']=False;auto_noise=n.create_publisher(Twist,'/auto/cmd_vel',10)
            c=Twist();c.linear.x=0.2
            for _ in range(10):manual.publish(c);auto_noise.publish(Twist());time.sleep(0.05)
            assert abs(values['drive'].linear.x-0.2)<1e-6,'unselected auto input interrupted manual'
            time.sleep(0.45)
            assert all(abs(v)<1e-8 for v in values['motors'].values()),'drive watchdog did not stop stale manual command'
            results.append('manual mode ignores auto input; final drive watchdog stops command loss')
            print(json.dumps({'ok':True,'checks':results},indent=2))
            (ROOT/'docs/navigation_integration_results.json').write_text(json.dumps({'ok':True,'checks':results},indent=2)+'\n')
        finally:
            release.set() if 'release' in locals() else None
            llm.stop_topic_worker()
            for p in processes:
                if p.poll() is None:os.killpg(p.pid,signal.SIGINT)
            for p in processes:
                try:p.wait(timeout=4)
                except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=3)
            for log in logs:log.close()
            for path in Path(td).glob('*.log'):
                (ROOT/'log'/('test_'+path.name)).write_text(path.read_text())
                print(path.name, path.read_text()[-1200:])
            rclpy.shutdown();executor.shutdown(timeout_sec=3);thread.join(timeout=3)
            for node in [n,llm,goals,bridge]:node.destroy_node()

if __name__=='__main__':main()

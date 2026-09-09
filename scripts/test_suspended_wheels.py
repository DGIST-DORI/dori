#!/usr/bin/env python3
"""Physical motor test. Run only with wheels raised and robot isolated."""
import argparse,json,math,time,statistics,signal
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile,DurabilityPolicy,qos_profile_sensor_data
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import JointState
from std_msgs.msg import Int32,Bool
from rcl_interfaces.srv import GetParameters
from robot_msgs.msg import MitCommand

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--execute-raised-wheel-test',action='store_true');ap.add_argument('--stronger',action='store_true');args=ap.parse_args()
    if not args.execute_raised_wheel_test:ap.error('Explicit raised-wheel execution flag required')
    rclpy.init();n=Node('suspended_wheel_direction_test');latched=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
    state={};history=[];report={'physical_condition':'User authorized commands with wheels raised and robot isolated','steps':[]}
    def receive(key,msg):
        state[key]=(time.monotonic(),msg)
        if key in ('odom','joint','motor'):history.append((time.monotonic(),key,msg))
    for typ,topic,key,q in [(Int32,'/system/control_mode','mode',latched),(Int32,'/system/action_state','action',latched),(Twist,'/manual/cmd_vel','manual',10),(Odometry,'/odom','odom',qos_profile_sensor_data),(JointState,'/joint_states','joint',qos_profile_sensor_data),(MitCommand,'/bldc_mit_speed_cmd','motor',100)]:
        n.create_subscription(typ,topic,lambda msg,key=key:receive(key,msg),q)
    def spin(duration):
        end=time.monotonic()+duration
        while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.01)
    spin(3)
    assert state.get('mode',(0,None))[1] is not None,'No supervisor mode'
    original=state['mode'][1].data
    assert original==0 and state['action'][1].data in (0,1),'Robot must be MANUAL and uninhibited'
    assert not n.get_publishers_info_by_topic('/auto/cmd_vel'),'Another AUTO command publisher exists'
    assert not n.get_publishers_info_by_topic('/navigation/halt'),'Navigation must be stopped first'
    for key in ['odom','joint','manual']:assert key in state and time.monotonic()-state[key][0]<.3,'Missing fresh '+key
    m=state['manual'][1];assert abs(m.linear.x)<1e-6 and abs(m.angular.z)<1e-6,'Release joystick'
    client=n.create_client(GetParameters,'/drive_controller_node/get_parameters');assert client.wait_for_service(timeout_sec=2)
    req=GetParameters.Request();req.names=['max_linear_velocity','max_angular_velocity','wheel_radius','wheel_separation']
    f=client.call_async(req);rclpy.spin_until_future_complete(n,f,timeout_sec=2);assert f.done() and f.result()
    scales={k:v.double_value for k,v in zip(req.names,f.result().values)}
    assert all(v>0 and math.isfinite(v) for v in scales.values());report['runtime_parameters']=scales
    pub=n.create_publisher(Twist,'/auto/cmd_vel',10);mode=n.create_publisher(Int32,'/control_mode_cmd',10)
    estop=n.create_publisher(Bool,'/emergency_stop',10)
    def checked():
        assert state['mode'][1].data==1 and state['action'][1].data in (0,1),'Control mode changed or hardware inhibited'
        for key in ['odom','joint']:assert time.monotonic()-state[key][0]<.3,'Feedback stale: '+key
        manual=state['manual'][1];assert abs(manual.linear.x)<1e-6 and abs(manual.angular.z)<1e-6,'Joystick input detected'
        o=state['odom'][1];assert abs(o.twist.twist.linear.x)<.3 and abs(o.twist.twist.angular.z)<1.5,'Unexpected wheel speed'
    def command(v,w,duration,check=True):
        msg=Twist();msg.linear.x=v/scales['max_linear_velocity'];msg.angular.z=w/scales['max_angular_velocity']
        end=time.monotonic()+duration
        while time.monotonic()<end:
            if check:checked()
            pub.publish(msg);spin(.04)
    def yaw(o):
        q=o.pose.pose.orientation;return math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
    try:
        spin(.5);mode.publish(Int32(data=1));spin(.5);checked();command(0,0,.8)
        speed,rate,duration=(.15,.8,3.0) if args.stronger else (.06,.35,2.0)
        for label,v,w in [('forward',speed,0.),('reverse',-speed,0.),('left_turn',0.,rate),('right_turn',0.,-rate)]:
            print('Testing',label,'v=',v,'w=',w,flush=True)
            begin=state['odom'][1];initial_joint=state['joint'][1];start=time.monotonic()
            command(v,w,duration);command(0,0,1.5)
            endodom=state['odom'][1];endjoint=state['joint'][1]
            a=yaw(begin);dx=endodom.pose.pose.position.x-begin.pose.pose.position.x;dy=endodom.pose.pose.position.y-begin.pose.pose.position.y
            forward=math.cos(a)*dx+math.sin(a)*dy;turn=math.remainder(yaw(endodom)-a,2*math.pi)
            d=[]
            for name in ['left_wheel_joint','right_wheel_joint']:
                d.append(math.remainder(endjoint.position[endjoint.name.index(name)]-initial_joint.position[initial_joint.name.index(name)],8*math.pi))
            radius=scales['wheel_radius'];sep=scales['wheel_separation'];distance=radius*sum(d)/2;rotation=radius*(d[1]-d[0])/sep
            samples=[m for t,k,m in history if start+.7<t<start+duration-.2 and k=='odom']
            row={'command':label,'command_v_m_s':v,'command_w_rad_s':w,'wheel_delta_rad':d,'odom_forward_m':forward,'odom_yaw_rad':turn,'encoder_distance_m':distance,'encoder_yaw_rad':rotation,'mean_v_m_s':statistics.mean(m.twist.twist.linear.x for m in samples) if samples else None,'mean_w_rad_s':statistics.mean(m.twist.twist.angular.z for m in samples) if samples else None}
            row['motor_commands']={}
            for mid in [1,2]:
                motors=[m for t,k,m in history if start+.7<t<start+duration-.2 and k=='motor' and m.motor_id==mid]
                if motors:row['motor_commands'][mid]={field:statistics.mean(getattr(m,field) for m in motors) for field in ['v_des','tau_ff','kd']}
            row['response_detected']=abs(forward)>.01 if v else abs(turn)>.05
            row['direction_ok']=(forward*v>0 and d[0]*v>0 and d[1]*v>0) if v else (turn*w>0 and d[0]*w<0 and d[1]*w>0)
            row['odom_encoder_consistent']=abs(turn-rotation)<.03 and (not v or abs(forward-distance)<.005)
            report['steps'].append(row);print(json.dumps(row),flush=True)
            assert row['response_detected'] and row['direction_ok'] and row['odom_encoder_consistent'],'Direction or encoder/odom consistency failed'
        report['ok']=True
    except BaseException as exc:
        report['ok']=False;report['error']=str(exc);print('TEST STOPPED:',repr(exc),flush=True)
    finally:
        command(0,0,1.5,check=False)
        o=state.get('odom',(0,None))[1]
        stopped=o is not None and time.monotonic()-state['odom'][0]<.3 and abs(o.twist.twist.linear.x)<.02 and abs(o.twist.twist.angular.z)<.15
        report['stopped_before_mode_restore']=stopped
        if not stopped:
            estop.publish(Bool(data=True));spin(.3);report['emergency_stop_requested']=True
        mode.publish(Int32(data=original));spin(.5)
        report['final_control_mode']=state['mode'][1].data
        path=Path(__file__).resolve().parents[1]/('docs/suspended_wheel_test_stronger_20260909.json' if args.stronger else 'docs/suspended_wheel_test_20260909.json');path.write_text(json.dumps(report,indent=2)+'\n');print('Report:',path,flush=True)
        n.destroy_node();rclpy.shutdown()
    return 0 if report.get('ok') and stopped else 1
if __name__=='__main__':raise SystemExit(main())

#!/usr/bin/env python3
"""Bounded physical motion trial, explicitly authorized. Captures raw IMU and laser scans.
Never derives mounting verification from command sign alone.
"""
import argparse,json,math,time
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile,DurabilityPolicy,qos_profile_sensor_data
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import JointState,Imu,LaserScan
from std_msgs.msg import Int32,Bool
from rcl_interfaces.srv import GetParameters

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execute-authorized-turn',action='store_true')
    ap.add_argument('--output',required=True)
    ap.add_argument('--duration',type=float,default=1.5)
    ap.add_argument('--rate',type=float,default=.4)
    ap.add_argument('--direction',choices=['positive','negative','both'],default='both')
    ap.add_argument('--forward-speed',type=float,default=0.,help='Forward trial speed in m/s; zero selects turn trial')
    a=ap.parse_args()
    if not math.isfinite(a.forward_speed) or not 0<=a.forward_speed<=.15:ap.error('forward speed must be 0..0.15 m/s')
    maximum=30 if a.forward_speed else 15
    if not math.isfinite(a.duration) or not 0<a.duration<=maximum:ap.error('duration exceeds trial limit')
    if not math.isfinite(a.rate) or not 0<a.rate<=1.0:ap.error('rate must be >0 and <=1.0 rad/s')
    if not a.execute_authorized_turn:ap.error('Explicit execution flag required')
    rclpy.init();n=Node('imu_turn_audit');state={};samples=[];phase='baseline';subs=[]
    latched=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
    def cb(key,m):
        state[key]=(time.monotonic(),m)
        if key not in ('imu','scan','joint','odom'):return
        row={'t':time.monotonic(),'phase':phase,'topic':key,
             'stamp':m.header.stamp.sec+m.header.stamp.nanosec/1e9}
        if key=='imu':
            row.update(accel=[getattr(m.linear_acceleration,c) for c in 'xyz'],gyro=[getattr(m.angular_velocity,c) for c in 'xyz'])
        elif key=='scan':
            row.update(angle_min=m.angle_min,angle_increment=m.angle_increment,time_increment=m.time_increment,
                       ranges=[float(v) if math.isfinite(v) else None for v in m.ranges])
        elif key=='joint':
            row.update(names=list(m.name),positions=list(m.position),velocities=list(m.velocity))
        else:
            q=m.pose.pose.orientation;pos=m.pose.pose.position
            row.update(x=pos.x,y=pos.y,yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z)))
        samples.append(row)
    for typ,topic,key,q in [(Int32,'/system/control_mode','mode',latched),(Int32,'/system/action_state','action',latched),
            (Twist,'/manual/cmd_vel','manual',10),(Odometry,'/odom','odom',qos_profile_sensor_data),
            (JointState,'/joint_states','joint',qos_profile_sensor_data),(Imu,'/imu/data_raw','imu',qos_profile_sensor_data),
            (LaserScan,'/scan','scan',qos_profile_sensor_data)]:
        subs.append(n.create_subscription(typ,topic,lambda m,k=key:cb(k,m),q))
    def spin(seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.01)
    def fresh(key):
        if key not in state or time.monotonic()-state[key][0]>.25:raise RuntimeError('Missing/stale '+key)
    def wheels():
        fresh('joint');m=state['joint'][1];out=[]
        for name in ['left_wheel_joint','right_wheel_joint']:
            i=m.name.index(name)
            if i>=len(m.velocity) or not math.isfinite(m.velocity[i]):raise RuntimeError('Invalid wheel feedback')
            out.append(m.velocity[i])
        return out
    def wheels_stopped():
        fresh('joint')
        rr=[r for r in samples if r['topic']=='joint' and r['t']>time.monotonic()-.6]
        if len(rr)<10 or rr[-1]['t']-rr[0]['t']<.4:return False
        for name in ['left_wheel_joint','right_wheel_joint']:
            pos=[r['positions'][r['names'].index(name)] for r in rr]
            delta=[math.remainder(x-pos[0],8*math.pi) for x in pos]
            if max(delta)-min(delta)>.01:return False
        return True
    def idle_joystick():
        fresh('manual');m=state['manual'][1]
        if abs(m.linear.x)>1e-6 or abs(m.angular.z)>1e-6:raise RuntimeError('Joystick input detected')
    report={'ok':False,'mounting_verified':False,'rate_rad_s':a.rate if not a.forward_speed else 0.,'forward_speed_m_s':a.forward_speed,'max_duration_s':a.duration,'steps':[]};pub=mode=estop=None;changed=False
    try:
        spin(4)
        for k in ['odom','imu','scan','joint','manual']:fresh(k)
        if state.get('mode',(0,None))[1] is None or state['mode'][1].data!=0:raise RuntimeError('MANUAL mode required')
        if state.get('action',(0,None))[1] is None or state['action'][1].data not in (0,1):raise RuntimeError('Hardware inhibited')
        idle_joystick()
        if not wheels_stopped():raise RuntimeError('Wheels must be stopped')
        if n.get_publishers_info_by_topic('/auto/cmd_vel') or n.get_publishers_info_by_topic('/navigation/halt'):raise RuntimeError('Competing navigation publisher')
        client=n.create_client(GetParameters,'/drive_controller_node/get_parameters')
        req=GetParameters.Request();req.names=['max_angular_velocity','max_linear_velocity']
        f=client.call_async(req);rclpy.spin_until_future_complete(n,f,timeout_sec=2)
        if not f.done() or not f.result() or len(f.result().values)!=2:raise RuntimeError('Missing drive parameters')
        max_w=f.result().values[0].double_value;max_v=f.result().values[1].double_value
        if not all(math.isfinite(v) and v>0 for v in [max_w,max_v]):raise RuntimeError('Invalid drive scale')
        pub=n.create_publisher(Twist,'/auto/cmd_vel',10)
        mode=n.create_publisher(Int32,'/control_mode_cmd',10)
        estop=n.create_publisher(Bool,'/emergency_stop',10);spin(.5)
        changed=True;mode.publish(Int32(data=1));spin(.5)
        def command(w,seconds,check=True,v=0.):
            msg=Twist();msg.angular.z=w/max_w;msg.linear.x=v/max_v;end=time.monotonic()+seconds
            while time.monotonic()<end:
                if check:
                    for k in ['imu','scan','odom']:fresh(k)
                    idle_joystick()
                    if v>0:
                        scan=state['scan'][1]
                        front=[r for i,r in enumerate(scan.ranges) if abs(math.remainder(scan.angle_min+i*scan.angle_increment,2*math.pi))<math.radians(30) and math.isfinite(r) and scan.range_min<=r<=scan.range_max]
                        if len(front)<10:raise RuntimeError('Insufficient valid forward lidar returns')
                        if min(front)<.5:raise RuntimeError('Obstacle within 0.5 m forward lidar sector')
                    if state['mode'][1].data!=1 or state['action'][1].data not in (0,1):raise RuntimeError('Mode changed/inhibited')
                    if max(abs(v) for v in wheels())>1.0:raise RuntimeError('Wheel velocity limit exceeded')
                    if max(abs(getattr(state['imu'][1].angular_velocity,c)) for c in 'xyz')>1.5:raise RuntimeError('IMU rate limit exceeded')
                pub.publish(msg);spin(.04)
        command(0,1)
        base=[r['gyro'] for r in samples if r['topic']=='imu' and r['phase']=='baseline']
        bias=[sum(v[i] for v in base)/len(base) for i in range(3)]
        report['baseline_bias_rad_s']=bias
        steps=[('positive_yaw',a.rate),('negative_yaw',-a.rate)]
        if a.direction!='both':steps=[s for s in steps if s[0].startswith(a.direction)]
        if a.forward_speed:steps=[('forward',0.)]
        for name,w in steps:
            phase=name;print('Trial:',name,'v=',a.forward_speed,'m/s w=',w,'rad/s,',a.duration,'s maximum',flush=True)
            begin=time.monotonic();deadline=begin+a.duration;last=None;angle=[0.,0.,0.];reason='duration_limit'
            while time.monotonic()<deadline:
                command(w,.04,v=a.forward_speed)
                m=state['imu'][1];stamp=m.header.stamp.sec+m.header.stamp.nanosec/1e9
                if last is not None and 0<stamp-last<.2:
                    for i,c in enumerate('xyz'):angle[i]+=(getattr(m.angular_velocity,c)-bias[i])*(stamp-last)
                last=stamp
                if math.sqrt(sum(x*x for x in angle))>.175:
                    reason='imu_angle_limit';print('IMU angle limit reached; stopping',flush=True);break
            elapsed=time.monotonic()-begin
            phase=name+'_settle';command(0,3)
            stopped=wheels_stopped()
            report['steps'].append({'name':name,'stopped':stopped,'command_duration_s':elapsed,'stop_reason':reason,'gyro_integral_xyz_rad':angle})
            if not stopped:raise RuntimeError('Wheels did not stop')
        report['ok']=True
    except BaseException as e:
        report['error']=repr(e);print('Trial stopped:',repr(e),flush=True)
    finally:
        phase='final_stop'
        if pub is not None:
            until=time.monotonic()+1.5
            while time.monotonic()<until:pub.publish(Twist());spin(.04)
        if changed:
            try:stopped=wheels_stopped()
            except Exception:stopped=False
            report['stopped']=stopped
            if not stopped:
                estop.publish(Bool(data=True));spin(.3);report['emergency_stop_requested']=True
            mode.publish(Int32(data=0));spin(.4)
            report['final_mode']=state['mode'][1].data
        target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(json.dumps({'report':report,'samples':samples},allow_nan=False)+'\n')
        print(json.dumps(report,indent=2),flush=True);print('Saved:',target,flush=True)
        n.destroy_node();rclpy.shutdown()
    return 0 if report['ok'] else 1
if __name__=='__main__':raise SystemExit(main())

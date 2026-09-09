#!/usr/bin/env python3
"""Continuous read-only observation. Publishes no commands."""
import json,math,time,statistics,argparse
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data,QoSProfile,DurabilityPolicy
from sensor_msgs.msg import Imu,JointState,LaserScan,Joy
from nav_msgs.msg import Odometry
from geometry_msgs.msg import Twist
from std_msgs.msg import Int32
from robot_msgs.msg import MitCommand
p=argparse.ArgumentParser();p.add_argument('--output-dir',required=True);a=p.parse_args()
out=Path(a.output_dir);out.mkdir(parents=True,exist_ok=True)
rclpy.init();n=Node('joystick_observer');state={};window={};subs=[]
raw=(out/'samples.jsonl').open('a');live=(out/'live.log').open('a');started=time.monotonic()
def emit(row):
    s=json.dumps(row,ensure_ascii=False,allow_nan=False);print(s,flush=True);live.write(s+'\n');live.flush();raw.flush()
def finite(v):return float(v) if math.isfinite(v) else None
def receive(key,m):
    now=time.monotonic();r={'topic':key,'t':now,'elapsed':now-started}
    if hasattr(m,'header'):
        r['stamp']=m.header.stamp.sec+m.header.stamp.nanosec/1e9
        r['age_ms']=(n.get_clock().now().nanoseconds/1e9-r['stamp'])*1000
    if key=='imu':
        r.update(accel=[finite(getattr(m.linear_acceleration,c)) for c in 'xyz'],gyro=[finite(getattr(m.angular_velocity,c)) for c in 'xyz'])
    elif key=='scan':r.update(angle_min=m.angle_min,angle_increment=m.angle_increment,time_increment=m.time_increment,ranges=[finite(v) for v in m.ranges])
    elif key=='joint':r.update(names=list(m.name),positions=[finite(v) for v in m.position],velocities=[finite(v) for v in m.velocity])
    elif key=='odom':
        q=m.pose.pose.orientation;r.update(x=m.pose.pose.position.x,y=m.pose.pose.position.y,yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z)),v=m.twist.twist.linear.x,w=m.twist.twist.angular.z)
    elif key=='joy':r.update(axes=list(m.axes),buttons=list(m.buttons))
    elif key=='motor':r.update(id=m.motor_id,v_des=m.v_des,tau_ff=m.tau_ff,kd=m.kd)
    elif key in ['mode','action']:r['value']=m.data
    else:r.update(v=m.linear.x,w=m.angular.z)
    state[key]=r;window.setdefault(key,[]).append(r);raw.write(json.dumps(r,allow_nan=False)+'\n')
latched=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
for typ,topic,key,q in [(Joy,'/joy','joy',qos_profile_sensor_data),(Twist,'/manual/cmd_vel','manual',10),(Twist,'/drive/cmd_vel','drive',10),(MitCommand,'/bldc_mit_speed_cmd','motor',100),(Imu,'/imu/data_raw','imu',qos_profile_sensor_data),(JointState,'/joint_states','joint',qos_profile_sensor_data),(LaserScan,'/scan','scan',qos_profile_sensor_data),(Odometry,'/odom','odom',qos_profile_sensor_data),(Int32,'/system/control_mode','mode',latched),(Int32,'/system/action_state','action',latched)]:
    subs.append(n.create_subscription(typ,topic,lambda m,k=key:receive(k,m),q))
last=time.monotonic();emit({'status':'observer_started','output_dir':str(out)})
try:
    while rclpy.ok():
        rclpy.spin_once(n,timeout_sec=.02)
        if time.monotonic()-last<5:continue
        now=time.monotonic();row={'elapsed_s':round(now-started,1),'counts':{k:len(v) for k,v in window.items()},'mode':state.get('mode',{}).get('value'),'action':state.get('action',{}).get('value'),'age_since_receive_s':{k:round(now-v['t'],2) for k,v in state.items()}}
        for key in ['manual','drive']:
            rr=window.get(key,[])
            if rr:row[key+'_peak']={c:round(max(rr,key=lambda r:abs(r[c]))[c],4) for c in ['v','w']}
        rr=window.get('motor',[])
        if rr:row['motor_v_des_mean']={str(mid):round(statistics.mean(r['v_des'] for r in rr if r['id']==mid),4) for mid in set(r['id'] for r in rr)}
        rr=window.get('odom',[])
        if len(rr)>1:row['odom_window']={'dx_m':round(rr[-1]['x']-rr[0]['x'],4),'dy_m':round(rr[-1]['y']-rr[0]['y'],4),'yaw_deg':round(math.degrees(math.remainder(rr[-1]['yaw']-rr[0]['yaw'],2*math.pi)),2)}
        rr=window.get('imu',[])
        if rr:row['gyro_mean_rad_s']=[round(statistics.mean(r['gyro'][i] for r in rr if r['gyro'][i] is not None),4) for i in range(3)]
        emit(row);window.clear();last=now
except KeyboardInterrupt:pass
finally:
    emit({'status':'observer_stopped'});raw.close();live.close();n.destroy_node();rclpy.shutdown()

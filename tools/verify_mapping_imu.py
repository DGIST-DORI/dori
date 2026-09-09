#!/usr/bin/env python3
"""Read-only live IMU mapping contract check."""
import json,time,math,sys,argparse
from pathlib import Path
import rclpy,yaml
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import Imu
from nav_msgs.msg import OccupancyGrid
from tf2_ros import Buffer,TransformListener
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/robot_mapping/scripts'))
from imu_rotation import rotation,vector
p=argparse.ArgumentParser();p.add_argument('--output',required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1];c=yaml.safe_load((root/'src/robot_mapping/config/imu_calibrated.yaml').read_text());R=rotation(c['rpy_rad'])
rclpy.init();n=Node('verify_mapping_imu');buf=Buffer();listener=TransformListener(buf,n);data={'raw':{},'mapped':{}};maps=[];subs=[]
def receive(key,m):data[key][m.header.stamp.sec*1000000000+m.header.stamp.nanosec]=m
for key,topic in [('raw','/imu/data_raw'),('mapped','/imu/mapping')]:subs.append(n.create_subscription(Imu,topic,lambda m,k=key:receive(k,m),qos_profile_sensor_data))
subs.append(n.create_subscription(OccupancyGrid,'/map',lambda m:maps.append(m),qos_profile_sensor_data))
end=time.monotonic()+12
while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.02)
errors=[];pairs=set(data['raw'])&set(data['mapped']);maxerr=0.;acc=[];gyro=[]
for stamp in pairs:
    raw=data['raw'][stamp];m=data['mapped'][stamp]
    if m.header.frame_id!='imu_mapping':errors.append('Wrong corrected frame')
    expected_g=vector(R,[getattr(raw.angular_velocity,x)-b for x,b in zip('xyz',c['gyro_bias_rad_s'])]);expected_a=vector(R,[getattr(raw.linear_acceleration,x) for x in 'xyz'])
    values_g=[getattr(m.angular_velocity,x) for x in 'xyz'];values_a=[getattr(m.linear_acceleration,x) for x in 'xyz']
    maxerr=max(maxerr,*[abs(x-y) for x,y in zip(expected_g+expected_a,values_g+values_a)])
    acc.append(values_a);gyro.append(values_g)
    if m.orientation_covariance[0]!=-1:errors.append('Invalid orientation validity flag')
if len(pairs)<100:errors.append('Too few matched raw/corrected messages')
if maxerr>1e-8:errors.append('Rotation/bias mismatch')
if not maps:errors.append('No live map received')
subscribers=[x.node_name for x in n.get_subscriptions_info_by_topic('/imu/mapping')]
if 'cartographer_node' not in subscribers:errors.append('Cartographer not subscribed to corrected IMU')
tfs={}
for target,source in [('base_link','imu_mapping'),('base_link','imu_link'),('map','base_link')]:
    try:
        t=buf.lookup_transform(target,source,Time());tfs[target+'<-'+source]={'xyz':[getattr(t.transform.translation,x) for x in 'xyz'],'xyzw':[getattr(t.transform.rotation,x) for x in 'xyzw']}
    except Exception as e:errors.append(str(e))
result={'ok':not errors,'errors':sorted(set(errors)),'matched_imu_messages':len(pairs),'max_numeric_error':maxerr,'imu_subscribers':subscribers,'map_messages':len(maps),'tf':tfs,'mean_accel':[sum(v[i] for v in acc)/len(acc) for i in range(3)] if acc else [],'mean_gyro':[sum(v[i] for v in gyro)/len(gyro) for i in range(3)] if gyro else []}
Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));n.destroy_node();rclpy.shutdown()
raise SystemExit(0 if result['ok'] else 1)

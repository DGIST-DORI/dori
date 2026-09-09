#!/usr/bin/env python3
"""Read-only sensor/TF audit. No motor publishers; statistics do not prove mounting."""
import argparse
import json
import math
from pathlib import Path
import statistics
import subprocess
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import Imu, JointState, LaserScan
from nav_msgs.msg import Odometry
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer, TransformListener
from rcl_interfaces.srv import GetParameters


def stamp(s):
    return s.sec * 1000000000 + s.nanosec


def stats(values):
    values = sorted(v for v in values if math.isfinite(v))
    if not values:
        return None
    return dict(count=len(values), mean=statistics.mean(values),
                std=statistics.pstdev(values), min=values[0],
                median=statistics.median(values), p95=values[int(.95*(len(values)-1))], max=values[-1])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--duration', type=float, default=20)
    p.add_argument('--label', default='unconfirmed_motion')
    p.add_argument('--output', required=True)
    a=p.parse_args()
    if not math.isfinite(a.duration) or not 5 <= a.duration <= 120:
        p.error('duration must be 5..120 seconds')
    rclpy.init(); n=Node('mapping_sensor_audit')
    buffer=Buffer(); listener=TransformListener(buffer,n)
    rows={}; subs=[]; transforms={}; pending=[]; tf_checks={}; futures={}
    types={'/scan':LaserScan,'/joint_states':JointState,'/odom':Odometry,
           '/imu/data_raw':Imu,'/imu/mapping':Imu}
    def receive(topic,m):
        ns=stamp(m.header.stamp); now=n.get_clock().now().nanoseconds
        row={'stamp_ns':ns,'age_ms':(now-ns)/1e6,'frame':m.header.frame_id}
        if isinstance(m,Imu):
            row['accel']=[getattr(m.linear_acceleration,c) for c in 'xyz']
            row['gyro']=[getattr(m.angular_velocity,c) for c in 'xyz']
            row['orientation_covariance_0']=m.orientation_covariance[0]
        elif isinstance(m,LaserScan):
            span=m.time_increment*max(0,len(m.ranges)-1)
            row.update(span_ms=span*1000,end_age_ms=(now-ns)/1e6-span*1000,
                       angle_increment=m.angle_increment,time_increment=m.time_increment)
            pending.append((time.monotonic()+.5,ns,ns+round(span*1e9),m.header.frame_id))
        elif isinstance(m,Odometry):
            pos=m.pose.pose.position; q=m.pose.pose.orientation
            row['position']=[pos.x,pos.y,pos.z]
            row['quaternion']=[q.x,q.y,q.z,q.w]
            row['twist']=[m.twist.twist.linear.x,m.twist.twist.angular.z]
        rows.setdefault(topic,[]).append(row)
    def tf_cb(m):
        gid='unresolved'
        for t in m.transforms:
            key=t.header.frame_id+'->'+t.child_frame_id
            transforms.setdefault(key,set()).add(gid)
    for topic,typ in types.items():
        subs.append(n.create_subscription(typ,topic,lambda m,t=topic:receive(t,m),qos_profile_sensor_data))
    subs.append(n.create_subscription(TFMessage,'/tf',tf_cb,qos_profile_sensor_data))
    subs.append(n.create_subscription(TFMessage,'/tf_static',tf_cb,QoSProfile(depth=100,durability=DurabilityPolicy.TRANSIENT_LOCAL)))
    # Allow discovery and the TF buffer to warm up before measuring.
    warmup=time.monotonic()+4
    while time.monotonic()<warmup:rclpy.spin_once(n,timeout_sec=.02)
    rows.clear();pending.clear()
    authority=subprocess.Popen(['ros2','run','robot_drive','tf_authority_check','--ros-args','-p','duration:='+str(a.duration)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    started=time.monotonic(); queried=False
    while time.monotonic()-started<a.duration+.6:
        rclpy.spin_once(n,timeout_sec=.02)
        if not queried and time.monotonic()-started>2:
            queried=True
            for name,ns in n.get_node_names_and_namespaces():
                if any(s in name for s in ['cartographer','lidar','odometry','controller_manager','imu_node']):
                    full=ns.rstrip('/')+'/'+name
                    for param in ['use_sim_time']+(['odom_scale'] if name=='wheel_odometry_node' else []):
                        client=n.create_client(GetParameters,full+'/get_parameters')
                        req=GetParameters.Request();req.names=[param]
                        futures[full+':'+param]=(client,client.call_async(req))
        while pending and pending[0][0]<=time.monotonic():
            _,begin,end,frame=pending.pop(0)
            for target,source in [('odom','base_link'),('map','base_link'),('base_link',frame)]:
                key=target+'<-'+source
                out=tf_checks.setdefault(key,{'ok':0,'failed':0,'last_error':None})
                for ts in [begin,end]:
                    try:
                        buffer.lookup_transform(target,source,Time(nanoseconds=ts))
                        out['ok']+=1
                    except Exception as e:
                        out['failed']+=1;out['last_error']=str(e)
    result={'label':a.label,'duration_s':time.monotonic()-started,'topics':{},'parameters':{},
            'scan_time_tf_checks_after_500ms':tf_checks,'tf_owners':{},'imu_mounting_verified':False,
            'limitations':['Host-stamp age is not physical acquisition latency.',
                           'Stationarity and physical motion direction require human confirmation.',
                           'Four-second discovery/TF warmup precedes measurements; subscriber delays can still affect this audit.']}
    gid_names={}
    for topic in ['/tf','/tf_static']:
        for endpoint in n.get_publishers_info_by_topic(topic):
            gid_names[bytes(endpoint.endpoint_gid).hex()]=endpoint.node_namespace.rstrip('/')+'/'+endpoint.node_name
    try:
        authority_out,authority_err=authority.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        authority.kill();authority_out,authority_err=authority.communicate()
    result['tf_authority_exit_code']=authority.returncode
    for line in authority_out.splitlines():
        parts=line.split('\t')
        if len(parts)==4 and parts[0]=='EDGE':
            result['tf_owners'].setdefault(parts[1]+'->'+parts[2],[]).append(parts[3])
    for topic,typ in types.items():
        rr=rows.get(topic,[])
        out={'count':len(rr),'publishers':[e.node_name for e in n.get_publishers_info_by_topic(topic)],
             'subscribers':[e.node_name for e in n.get_subscriptions_info_by_topic(topic)]}
        if rr:
            gaps=[(b['stamp_ns']-x['stamp_ns'])/1e6 for x,b in zip(rr,rr[1:])]
            out.update(age_ms=stats([r['age_ms'] for r in rr]),gap_ms=stats(gaps),
                       nonincreasing=sum(g<=0 for g in gaps),frames=sorted({r['frame'] for r in rr}))
            if typ is Imu:
                for field in ['accel','gyro']:
                    out[field]=[stats([r[field][i] for r in rr]) for i in range(3)]
                out['accel_norm']=stats([math.sqrt(sum(v*v for v in r['accel'])) for r in rr])
                out['orientation_covariance_0']=sorted({r['orientation_covariance_0'] for r in rr})
            elif typ is LaserScan:
                for field in ['span_ms','end_age_ms','angle_increment','time_increment']:
                    out[field]=stats([r[field] for r in rr])
            elif typ is Odometry:
                out['net_position_delta_m']=[rr[-1]['position'][i]-rr[0]['position'][i] for i in range(3)]
                out['twist']=[stats([r['twist'][i] for r in rr]) for i in range(2)]
        result['topics'][topic]=out
    for key,(_,f) in futures.items():
        if f.done() and f.result() and f.result().values:
            v=f.result().values[0]
            result['parameters'][key]=v.bool_value if v.type==1 else v.double_value if v.type==3 else None
        else:result['parameters'][key]='no response'
    try:
        t=buffer.lookup_transform('base_link','imu_link',Time())
        result['base_from_imu']={'xyz':[getattr(t.transform.translation,c) for c in 'xyz'],
                                'xyzw':[getattr(t.transform.rotation,c) for c in 'xyzw']}
    except Exception as e:result['base_from_imu']={'error':str(e)}
    target=Path(a.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps({'summary':result,'samples':rows},indent=2,allow_nan=False)+'\n')
    print(json.dumps(result,indent=2,allow_nan=False),flush=True)
    n.destroy_node();rclpy.shutdown()

if __name__=='__main__':main()

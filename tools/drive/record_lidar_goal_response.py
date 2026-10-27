#!/usr/bin/env python3
"""Record the whole velocity path. --retry-last explicitly retries the web goal."""
import argparse,json,math,time,urllib.request
from pathlib import Path
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data,QoSProfile,DurabilityPolicy
from geometry_msgs.msg import Twist,PoseStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import JointState
from control_msgs.msg import DynamicJointState
from std_msgs.msg import Int32,String,Bool
from dori_msgs.msg import MitCommand


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--retry-last',action='store_true');ap.add_argument('--duration',type=float,default=8);ap.add_argument('--output',default='log/lidar_drive_response.json');args=ap.parse_args()
    rclpy.init();n=Node('lidar_drive_response_recorder');latest={};samples=[]
    for key,topic in [('nav','/nav/cmd_vel'),('auto','/auto/cmd_vel'),('drive','/drive/cmd_vel')]:
        n.create_subscription(Twist,topic,lambda m,k=key:latest.update({k:[m.linear.x,m.angular.z]}),10)
    def motor(m):latest['motor_'+str(m.motor_id)]=[m.v_des,m.tau_ff]
    n.create_subscription(MitCommand,'/bldc_mit_speed_cmd',motor,100)
    def joints(m):latest['wheels']={name:[m.position[i],m.velocity[i],m.effort[i] if i<len(m.effort) else None] for i,name in enumerate(m.name) if i<len(m.position) and i<len(m.velocity)}
    n.create_subscription(JointState,'/joint_states',joints,qos_profile_sensor_data)
    def dynamic(m,key):
        latest[key]={name:dict(zip(values.interface_names,values.values)) for name,values in zip(m.joint_names,m.interface_values)}
    n.create_subscription(DynamicJointState,'/dynamic_joint_states',lambda m:dynamic(m,'hardware'),qos_profile_sensor_data)
    n.create_subscription(DynamicJointState,'/drive/wheel_control',lambda m:dynamic(m,'wheel_control'),qos_profile_sensor_data)
    def odom(m):
        p=m.pose.pose.position;q=m.pose.pose.orientation
        latest['odom']=[p.x,p.y,math.atan2(2*q.w*q.z,1-2*q.z*q.z)]
    n.create_subscription(Odometry,'/odom',odom,qos_profile_sensor_data)
    n.create_subscription(String,'/navigation/drive_status',lambda m:latest.update(gate=m.data),QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL))
    n.create_subscription(String,'/named_goal_status',lambda m:latest.update(goal=m.data),10)
    goal=n.create_publisher(PoseStamped,'/goal_pose',10);mode=n.create_publisher(Int32,'/NAVIGATION_MODE',10)
    end=time.monotonic()+2
    while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.02)
    retried=False
    try:
        if args.retry_last:
            s=json.load(urllib.request.urlopen('http://127.0.0.1:8080/api/state'))
            if s['values'].get('active'):raise RuntimeError('Another goal is active; recording only is required')
            if not s['values'].get('enabled') or not s.get('goal'):raise RuntimeError('Web navigation must be enabled with a previous goal')
            x,y,a=s['goal'];m=PoseStamped();m.header.frame_id='map';m.header.stamp=n.get_clock().now().to_msg();m.pose.position.x=x;m.pose.position.y=y;m.pose.orientation.z=math.sin(a/2);m.pose.orientation.w=math.cos(a/2);goal.publish(m);retried=True
        start=time.monotonic();next_sample=start
        while time.monotonic()-start<args.duration:
            rclpy.spin_once(n,timeout_sec=.01)
            if time.monotonic()>=next_sample:
                samples.append(dict(t=time.monotonic()-start,**latest));next_sample+=.1
    finally:
        if retried:
            mode.publish(Int32(data=0));end=time.monotonic()+.4
            while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.02)
        Path(args.output).write_text(json.dumps(samples,indent=2))
        n.destroy_node();rclpy.shutdown()
    moving=[s for s in samples if s.get('gate')=='driving']
    print(json.dumps({'samples':len(samples),'driving_samples':len(moving),'first':moving[0] if moving else None,'middle':moving[len(moving)//2] if moving else None,'last':moving[-1] if moving else None},indent=2))
if __name__=='__main__':main()

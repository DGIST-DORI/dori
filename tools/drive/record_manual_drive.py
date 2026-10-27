#!/usr/bin/env python3
"""Passive, streaming capture of joystick -> protected motor command -> motion.

No command publishers. JSONL is flushed each second and survives interruption.
Timestamps and per-topic receipt ages distinguish missing data from zero motion.
"""
import argparse
import json
import math
import time
from pathlib import Path

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Joy, JointState, Imu
from control_msgs.msg import DynamicJointState
from std_msgs.msg import Int32, String, Float64
from dori_msgs.msg import MitCommand, CommandFeedback


def finite(value):
    if isinstance(value, float): return value if math.isfinite(value) else None
    if isinstance(value, dict): return {k:finite(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [finite(v) for v in value]
    return value


class Recorder(Node):
    def __init__(self, output):
        super().__init__('manual_drive_recorder')
        self.latest={};self.received={};self.start=time.monotonic();self.count=0
        self.file=output.open('w',buffering=1)
        latch=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
        def subscribe(kind,topic,key,convert,qos=qos_profile_sensor_data):
            self.create_subscription(kind,topic,lambda m:self.put(key,convert(m)),qos)
        for key,topic in [('manual','/manual/cmd_vel'),('auto','/auto/cmd_vel'),
                          ('drive','/drive/cmd_vel'),('nav','/nav/cmd_vel')]:
            subscribe(Twist,topic,key,lambda m:[m.linear.x,m.angular.z])
        subscribe(Joy,'/joy','joy',lambda m:dict(axes=list(m.axes),buttons=list(m.buttons)))
        self.create_subscription(MitCommand,'/bldc_mit_speed_cmd',self.motor,qos_profile_sensor_data)
        subscribe(JointState,'/joint_states','joints',lambda m:{name:{field:list(getattr(m,field))[i]
            for field in ('position','velocity','effort') if i<len(getattr(m,field))} for i,name in enumerate(m.name)})
        for key,topic in [('hardware','/dynamic_joint_states'),('wheel_control','/drive/wheel_control')]:
            subscribe(DynamicJointState,topic,key,lambda m:{name:dict(zip(v.interface_names,v.values))
                for name,v in zip(m.joint_names,m.interface_values) if 'wheel' in name})
        subscribe(Odometry,'/odom','odom',self.odometry)
        subscribe(Imu,'/imu/data_raw','imu',lambda m:dict(
            stamp=m.header.stamp.sec+m.header.stamp.nanosec/1e9,
            gyro=[m.angular_velocity.x,m.angular_velocity.y,m.angular_velocity.z],
            acceleration=[m.linear_acceleration.x,m.linear_acceleration.y,m.linear_acceleration.z]))
        for key,topic in [('control_mode','/system/control_mode'),('action','/system/action_state')]:
            subscribe(Int32,topic,key,lambda m:m.data,latch)
        for key,topic in [('gate','/navigation/drive_status'),('lidar_quality','/lidar_odometry/status')]:
            subscribe(String,topic,key,lambda m:m.data,latch)
        subscribe(CommandFeedback,'/drive/command_feedback','drive_feedback',
                  lambda m:str(m))
        subscribe(Float64,'/body/pitch_deg','pitch_deg',lambda m:m.data)
        self.create_timer(.05,self.sample)

    def put(self,key,value):
        self.latest[key]=value;self.received[key]=time.monotonic()

    def motor(self,m):
        self.put('motor_'+str(m.motor_id),dict(velocity=m.v_des,effort=m.tau_ff,kd=m.kd))

    @staticmethod
    def odometry(m):
        p=m.pose.pose.position;q=m.pose.pose.orientation;v=m.twist.twist
        return dict(stamp=m.header.stamp.sec+m.header.stamp.nanosec/1e9,
                    pose=[p.x,p.y,math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))],
                    velocity=[v.linear.x,v.angular.z])

    def sample(self):
        now=time.monotonic()
        data=dict(t=now-self.start,ros_time=self.get_clock().now().nanoseconds/1e9,
                  ages={k:now-v for k,v in self.received.items()},**self.latest)
        self.file.write(json.dumps(finite(data),allow_nan=False,separators=(',',':'))+'\n')
        self.count+=1


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',required=True)
    parser.add_argument('--duration',type=float,default=600.)
    args=parser.parse_args();output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    rclpy.init();node=Recorder(output)
    print('Recording manual commands, protected motor targets, encoders and LiDAR: '+str(output),flush=True)
    try:
        while rclpy.ok() and time.monotonic()-node.start<args.duration:rclpy.spin_once(node,timeout_sec=.05)
    except KeyboardInterrupt:
        pass
    finally:
        node.file.close();print('Saved '+str(node.count)+' samples',flush=True)
        node.destroy_node()
        if rclpy.ok():rclpy.shutdown()


if __name__=='__main__':main()

#!/usr/bin/env python3
import argparse
import math
import time
import rclpy
from rclpy.node import Node
from std_msgs.msg import Int32,String
from geometry_msgs.msg import PoseWithCovarianceStamped


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    t=sub.add_parser('text');t.add_argument('text')
    sub.add_parser('stop')
    p=sub.add_parser('pose');p.add_argument('x',type=float);p.add_argument('y',type=float);p.add_argument('yaw_deg',type=float)
    args=parser.parse_args();rclpy.init();n=Node('navigation_command')
    if args.command=='pose':
        if not all(math.isfinite(v) for v in [args.x,args.y,args.yaw_deg]):raise ValueError('Finite pose required')
        pub=n.create_publisher(PoseWithCovarianceStamped,'/initialpose',10)
        end=time.monotonic()+8
        while pub.get_subscription_count()<1 and time.monotonic()<end:rclpy.spin_once(n,timeout_sec=0.1)
        if pub.get_subscription_count()<1:raise RuntimeError('AMCL /initialpose subscriber not available')
        msg=PoseWithCovarianceStamped();msg.header.frame_id='map';msg.header.stamp=n.get_clock().now().to_msg()
        msg.pose.pose.position.x=args.x;msg.pose.pose.position.y=args.y
        yaw=math.radians(args.yaw_deg);msg.pose.pose.orientation.z=math.sin(yaw/2);msg.pose.pose.orientation.w=math.cos(yaw/2)
        msg.pose.covariance[0]=0.25;msg.pose.covariance[7]=0.25;msg.pose.covariance[35]=0.0685
        pub.publish(msg)
    else:
        mode=n.create_publisher(Int32,'/NAVIGATION_MODE',10);text=n.create_publisher(String,'/NAVIGATION_TEXT',10)
        end=time.monotonic()+8
        while time.monotonic()<end:
            rclpy.spin_once(n,timeout_sec=0.1)
            if mode.get_subscription_count()>=(1 if args.command=='stop' else 3) and (args.command=='stop' or text.get_subscription_count()>=1):break
        else:raise RuntimeError('Navigation stack subscribers not ready')
        if args.command=='stop':
            mode.publish(Int32(data=0))
        else:
            text.publish(String(data=args.text))
            # Allow text caching before enabling processing, including a previously disabled session.
            end=time.monotonic()+0.2
            while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=0.02)
            mode.publish(Int32(data=1))
    end=time.monotonic()+0.5
    while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=0.05)
    print('Published',args.command)
    n.destroy_node();rclpy.shutdown()


if __name__=='__main__':main()

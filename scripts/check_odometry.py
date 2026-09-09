#!/usr/bin/env python3
"""ROS integration test. Run in an isolated domain; starts only wheel_odometry_node."""
import math
import argparse
import os
import signal
import subprocess
import time

import rclpy
from sensor_msgs.msg import JointState
from nav_msgs.msg import Odometry
from tf2_msgs.msg import TFMessage


def main():
    parser=argparse.ArgumentParser();parser.add_argument("--odom-scale",type=float,default=1.0);scale=parser.parse_args().odom_scale
    if os.environ.get('ROS_DOMAIN_ID') != '91' or os.environ.get('ROS_LOCALHOST_ONLY') != '1':
        raise RuntimeError('Use ROS_DOMAIN_ID=91 ROS_LOCALHOST_ONLY=1 for this test')
    rclpy.init()
    node = rclpy.create_node('odometry_integration_check')
    messages, transforms = [], []
    node.create_subscription(Odometry, '/test/odom', messages.append, 100)
    node.create_subscription(TFMessage, '/test/tf', transforms.append, 100)
    pub = node.create_publisher(JointState, '/test/joint_states', 20)
    process = subprocess.Popen([
        'ros2', 'run', 'robot_drive', 'wheel_odometry_node', '--ros-args',
        '-r', 'joint_states:=/test/joint_states', '-r', 'odom:=/test/odom',
        '-r', '/tf:=/test/tf', '-p', 'odom_scale:='+str(scale)], start_new_session=True)

    def spin(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=0.01)

    def send(left, right, names=None, stale=False):
        msg = JointState()
        msg.header.stamp = node.get_clock().now().to_msg()
        if stale:
            msg.header.stamp.sec -= 2
        # Reversed order tests lookup by joint name, not array index.
        msg.name = names if names is not None else ['right_wheel_joint', 'left_wheel_joint']
        msg.position = [right, left]
        pub.publish(msg)
        spin(0.06)

    try:
        deadline = time.monotonic() + 10
        while pub.get_subscription_count() == 0 and time.monotonic() < deadline:
            spin(0.1)
        assert pub.get_subscription_count() == 1, 'odometry subscriber missing'
        send(5.0, -3.0)
        for i in range(1, 11):
            send(5.0 + i * 0.1, -3.0 + i * 0.1)
        assert messages, 'no Odometry received'
        last = messages[-1]
        assert abs(last.pose.pose.position.x - 0.234 * scale) < 1e-6, last.pose.pose.position
        assert abs(last.pose.pose.position.y) < 1e-6
        assert last.header.frame_id == 'odom' and last.child_frame_id == 'base_link'
        assert last.twist.twist.linear.x > 0
        assert abs(last.twist.twist.angular.z) < 1e-6
        assert last.pose.covariance[0] > 0 and last.twist.covariance[35] > 0
        assert transforms, 'missing odom TF'
        tf = transforms[-1].transforms[0]
        assert tf.header.frame_id == 'odom' and tf.child_frame_id == 'base_link'
        assert abs(tf.transform.translation.x - last.pose.pose.position.x) < 1e-6
        assert tf.header.stamp == last.header.stamp
        count = len(messages)
        send(7.0, -1.0, stale=True)
        send(7.0, -1.0, names=['other_joint'])
        send(float('nan'), -1.0)
        assert len(messages) == count, 'invalid JointState produced odometry'
        spin(0.3)
        assert len(messages) == count, 'odometry extrapolated without measurements'
        send(10.0, 2.0)
        assert abs(messages[-1].pose.pose.position.x - 0.234 * scale) < 1e-6, 'integrated over gap'
        assert messages[-1].twist.twist.linear.x == 0
        send(10.1, 2.1)
        assert abs(messages[-1].pose.pose.position.x - 0.2574 * scale) < 1e-6
        for i in range(1,11):
            send(10.1-i*.01,2.1+i*.01)
        last=messages[-1];q=last.pose.pose.orientation
        angle=math.atan2(2*q.w*q.z,1-2*q.z*q.z)
        assert abs(angle-.234*.2/.184*scale)<1e-6, 'yaw scale mismatch'
        assert abs(last.pose.pose.position.x-.2574*scale)<1e-6
        assert abs(transforms[-1].transforms[0].transform.rotation.z-q.z)<1e-6
        print('Scale',scale,'validated for translation, yaw and TF')
        print('PASS: ROS joint ordering, pose, speed, TF, covariance, invalid/stale input and gap recovery')
    finally:
        os.killpg(process.pid, signal.SIGINT)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

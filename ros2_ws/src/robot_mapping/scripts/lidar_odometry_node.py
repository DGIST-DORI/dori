#!/usr/bin/env python3
"""C1 scan registration -> /odom, matching TF and observable quality status."""
import os
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['OMP_NUM_THREADS'] = '1'
import json
import math
import time
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy
from nav_msgs.msg import Odometry as OdometryMessage
from sensor_msgs.msg import LaserScan
from geometry_msgs.msg import TransformStamped
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformListener, TransformBroadcaster, TransformException
from lidar_odometry.core import Odometry, Settings, scan_points, transform, RegistrationError


class LidarOdometry(Node):
    def __init__(self):
        super().__init__('lidar_odometry')
        settings = Settings(**{key: self.declare_parameter(key, value).value
                               for key, value in vars(Settings()).items()})
        self.estimator = Odometry(settings)
        seed = np.array([self.declare_parameter('initial_'+key, 0.).value for key in ('x','y','yaw')])
        if not np.isfinite(seed).all(): raise ValueError('Initial odometry pose must be finite')
        self.estimator.pose = seed.copy(); self.estimator.reference_pose = seed.copy()
        self.scan_timeout = self.declare_parameter('scan_timeout', 0.8).value
        self.base_frame = self.declare_parameter('base_frame', 'base_link').value
        self.odom_frame = self.declare_parameter('odom_frame', 'odom').value
        self.laser_frame = self.declare_parameter('laser_frame', 'laser').value
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.broadcaster = TransformBroadcaster(self)
        self.pub = self.create_publisher(OdometryMessage, '/odom', 10)
        self.status = self.create_publisher(String, '/lidar_odometry/status',
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(LaserScan, '/scan', self.receive,
            QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT))
        self.last_receive = time.monotonic()
        self.last_reason = ''
        self.accepted = self.rejected = 0
        self.create_timer(0.5, self.watchdog)
        self.create_service(Trigger,'/lidar_odometry/reset_reference',self.reset_reference)

    def reset_reference(self, request, response):
        # Explicit relocalization only. The map search supplies the new absolute
        # pose; retaining this odom origin avoids an arbitrary TF translation.
        e=self.estimator
        e.reference=None;e.reference_pose=e.pose.copy();e.reference_stamp=None
        e.last_stamp=e.last_seen=None;e.velocity=np.zeros(3);e.lost=False
        self.report('relocalizing')
        response.success=True;response.message='새 스캔을 기다립니다. 지도 재정합이 필요합니다.'
        return response

    def report(self, state, **details):
        data = dict(state=state, accepted=self.accepted, rejected=self.rejected, **details)
        self.status.publish(String(data=json.dumps(data, allow_nan=False)))
        if state != self.last_reason:
            self.get_logger().info('LiDAR odometry: ' + state)
            self.last_reason = state

    def watchdog(self):
        if time.monotonic() - self.last_receive > self.scan_timeout:
            self.report('scan_timeout')

    def receive(self, msg):
        started = time.monotonic()
        self.last_receive = started
        stamp = Time.from_msg(msg.header.stamp)
        age = (self.get_clock().now() - stamp).nanoseconds / 1e9
        try:
            if msg.header.frame_id != self.laser_frame:
                raise RegistrationError('invalid_scan_frame')
            if not -0.05 <= age <= self.scan_timeout:
                raise RegistrationError('stale_scan')
            tf = self.buffer.lookup_transform(self.base_frame, msg.header.frame_id, stamp)
            p, q = tf.transform.translation, tf.transform.rotation
            roll = math.atan2(2*(q.w*q.x+q.y*q.z), 1-2*(q.x*q.x+q.y*q.y))
            pitch = math.asin(max(-1., min(1., 2*(q.w*q.y-q.z*q.x))))
            if abs(roll) > 0.15 or abs(pitch) > 0.15:
                raise RegistrationError('nonplanar_laser_mount')
            yaw = math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))
            points = scan_points(msg.ranges, msg.angle_min, msg.angle_increment,
                                 max(0.10, msg.range_min), min(16.0, msg.range_max))
            # Transform before matching: correctly accounts for yaw=pi and for
            # the lever-arm translation when the robot turns in place.
            points = transform(points, np.array([p.x, p.y, yaw]))
            match = self.estimator.update(points, stamp.nanoseconds / 1e9)
        except (RegistrationError, ValueError, np.linalg.LinAlgError) as exc:
            self.rejected += 1
            self.report(str(exc))
            return
        except TransformException:
            self.report('waiting_for_laser_tf')
            return
        pose, velocity = self.estimator.pose, self.estimator.velocity
        odom = OdometryMessage()
        odom.header.stamp = msg.header.stamp
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame
        odom.pose.pose.position.x, odom.pose.pose.position.y = map(float, pose[:2])
        odom.pose.pose.orientation.z = math.sin(pose[2] / 2)
        odom.pose.pose.orientation.w = math.cos(pose[2] / 2)
        odom.twist.twist.linear.x, odom.twist.twist.linear.y = map(float, velocity[:2])
        odom.twist.twist.angular.z = float(velocity[2])
        # Fit covariance has a conservative floor; accumulated drift is not
        # statistically calibrated. Do not claim this is fused absolute accuracy.
        for axis, variance in enumerate((.01, .01, 1e6, 1e6, 1e6, .01)):
            odom.pose.covariance[axis*7] = variance
            odom.twist.covariance[axis*7] = variance * 2
        tf = TransformStamped()
        tf.header, tf.child_frame_id = odom.header, odom.child_frame_id
        tf.transform.translation.x = odom.pose.pose.position.x
        tf.transform.translation.y = odom.pose.pose.position.y
        tf.transform.rotation = odom.pose.pose.orientation
        self.broadcaster.sendTransform(tf)
        self.pub.publish(odom)
        self.accepted += 1
        self.report('tracking', rmse_m=match.rmse, overlap=match.overlap,
                    condition=match.condition, points=len(points),
                    processing_ms=(time.monotonic()-started)*1000)


def main():
    rclpy.init()
    node = LidarOdometry()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()

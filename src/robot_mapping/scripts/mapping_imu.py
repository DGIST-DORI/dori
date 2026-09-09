#!/usr/bin/env python3
"""Dedicated mapping IMU stream; preserve raw IMU used by existing body control."""
import math
import copy
from imu_rotation import rotation, vector, covariance
from imu_calibration import load_calibration
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from sensor_msgs.msg import Imu

class MappingImu(Node):
    def __init__(self):
        super().__init__('mapping_imu')
        c=load_calibration(self.declare_parameter('calibration_file','').value)
        self.bias=c['gyro_bias_rad_s'];self.frame=c['frame_id']
        self.output_frame=c.get('mapping_frame_id',self.frame)
        self.rotation=rotation(c['rpy_rad']) if self.output_frame!=self.frame else rotation([0.,0.,0.])
        self.last_stamp=0
        self.pub=self.create_publisher(Imu,'/imu/mapping',qos_profile_sensor_data)
        self.sub=self.create_subscription(Imu,'/imu/data_raw',self.receive,qos_profile_sensor_data)
    def receive(self,m):
        stamp=Time.from_msg(m.header.stamp)
        age=(self.get_clock().now()-stamp).nanoseconds/1e9
        values=[getattr(v,a) for v in [m.angular_velocity,m.linear_acceleration] for a in 'xyz']
        if m.header.frame_id!=self.frame or not -.05<=age<=.2 or stamp.nanoseconds<=self.last_stamp or not all(math.isfinite(v) for v in values):return
        if not 1<math.sqrt(sum(getattr(m.linear_acceleration,a)**2 for a in 'xyz'))<30:return
        self.last_stamp=stamp.nanoseconds
        out=copy.deepcopy(m)
        out.header.frame_id=self.output_frame
        gyro=vector(self.rotation,[getattr(m.angular_velocity,a)-b for a,b in zip('xyz',self.bias)])
        accel=vector(self.rotation,[getattr(m.linear_acceleration,a) for a in 'xyz'])
        for a,g,v in zip('xyz',gyro,accel):
            setattr(out.angular_velocity,a,g);setattr(out.linear_acceleration,a,v)
        out.angular_velocity_covariance=covariance(self.rotation,m.angular_velocity_covariance)
        out.linear_acceleration_covariance=covariance(self.rotation,m.linear_acceleration_covariance)
        # This stream supplies angular velocity and specific force, not an attitude estimate.
        out.orientation.x=out.orientation.y=out.orientation.z=0.;out.orientation.w=1.
        out.orientation_covariance=[-1.,0.,0.,0.,0.,0.,0.,0.,0.]
        self.pub.publish(out)

def main():
    rclpy.init();n=MappingImu()
    try:rclpy.spin(n)
    except KeyboardInterrupt:pass
    finally:
        n.destroy_node()
        if rclpy.ok():rclpy.shutdown()
if __name__=='__main__':main()

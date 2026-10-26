#!/usr/bin/env python3

import math

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Imu
from std_msgs.msg import Float64


class BodyPitchNode(Node):

    def __init__(self):
        super().__init__('body_pitch_node')

        # ============================================================
        # Parameters
        # ============================================================

        self.declare_parameter(
            'alpha',
            0.98
        )

        self.declare_parameter(
            'gyro_deadband',
            0.002
        )

        self.alpha = (
            self.get_parameter('alpha')
            .get_parameter_value()
            .double_value
        )

        self.gyro_deadband = (
            self.get_parameter('gyro_deadband')
            .get_parameter_value()
            .double_value
        )

        # ============================================================
        # Subscriber
        # ============================================================

        self.imu_sub = self.create_subscription(
            Imu,
            '/imu/data_raw',
            self.imu_callback,
            10
        )

        # ============================================================
        # Publishers
        # ============================================================

        self.pitch_rad_pub = self.create_publisher(
            Float64,
            '/body/pitch',
            10
        )

        self.pitch_deg_pub = self.create_publisher(
            Float64,
            '/body/pitch_deg',
            10
        )

        self.pitch_rate_pub = self.create_publisher(
            Float64,
            '/body/pitch_rate',
            10
        )

        self.acc_pitch_deg_pub = self.create_publisher(
            Float64,
            '/body/acc_pitch_deg',
            10
        )

        # ============================================================
        # NEW:
        # Gyro-only integrated pitch
        #
        # complementary filter가 얼마나 늦는지 확인하기 위한 디버그
        # ============================================================

        self.gyro_pitch_deg_pub = self.create_publisher(
            Float64,
            '/body/gyro_pitch_deg',
            10
        )

        # ============================================================
        # Filter states
        # ============================================================

        self.pitch = 0.0

        # gyro-only 적분값
        self.gyro_only_pitch = 0.0

        self.initialized = False

        self.last_time = None

        self.get_logger().info(
            'Body pitch estimator started'
        )

        self.get_logger().info(
            f'Complementary filter alpha = {self.alpha}'
        )

    # ================================================================
    # IMU callback
    # ================================================================

    def imu_callback(self, msg):

        # ============================================================
        # Timestamp
        # ============================================================

        current_time = (
            msg.header.stamp.sec
            +
            msg.header.stamp.nanosec * 1e-9
        )

        # ============================================================
        # IMU data
        # ============================================================

        ay = msg.linear_acceleration.y
        az = msg.linear_acceleration.z

        gx = msg.angular_velocity.x

        # ============================================================
        # Accelerometer pitch
        # ============================================================

        acc_pitch = math.atan2(
            ay,
            -az
        )

        # ============================================================
        # Initialization
        # ============================================================

        if not self.initialized:

            self.pitch = acc_pitch

            self.gyro_only_pitch = acc_pitch

            self.last_time = current_time

            self.initialized = True

            return

        # ============================================================
        # dt
        # ============================================================

        dt = (
            current_time
            -
            self.last_time
        )

        self.last_time = current_time

        if dt <= 0.0 or dt > 0.1:
            return

        # ============================================================
        # Gyro deadband
        # ============================================================

        gyro_rate = -gx

        if abs(gyro_rate) < self.gyro_deadband:
            gyro_rate = 0.0

        # ============================================================
        # Gyro-only integration
        #
        # 디버깅용
        # ============================================================

        self.gyro_only_pitch += (
            gyro_rate
            *
            dt
        )

        # ============================================================
        # Gyro prediction for complementary filter
        # ============================================================

        gyro_pitch = (
            self.pitch
            +
            gyro_rate * dt
        )

        # ============================================================
        # Complementary filter
        # ============================================================

        self.pitch = (
            self.alpha
            *
            gyro_pitch
            +
            (1.0 - self.alpha)
            *
            acc_pitch
        )

        # ============================================================
        # Publish filtered pitch [rad]
        # ============================================================

        pitch_msg = Float64()

        pitch_msg.data = (
            self.pitch
        )

        self.pitch_rad_pub.publish(
            pitch_msg
        )

        # ============================================================
        # Publish filtered pitch [deg]
        # ============================================================

        pitch_deg_msg = Float64()

        pitch_deg_msg.data = (
            math.degrees(
                self.pitch
            )
        )

        self.pitch_deg_pub.publish(
            pitch_deg_msg
        )

        # ============================================================
        # Publish gyro rate [rad/s]
        # ============================================================

        rate_msg = Float64()

        rate_msg.data = gyro_rate

        self.pitch_rate_pub.publish(
            rate_msg
        )

        # ============================================================
        # Publish accelerometer pitch [deg]
        # ============================================================

        acc_msg = Float64()

        acc_msg.data = (
            math.degrees(
                acc_pitch
            )
        )

        self.acc_pitch_deg_pub.publish(
            acc_msg
        )

        # ============================================================
        # Publish gyro-only pitch [deg]
        # ============================================================

        gyro_pitch_msg = Float64()

        gyro_pitch_msg.data = (
            math.degrees(
                self.gyro_only_pitch
            )
        )

        self.gyro_pitch_deg_pub.publish(
            gyro_pitch_msg
        )


def main(args=None):

    rclpy.init(args=args)

    node = BodyPitchNode()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

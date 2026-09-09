#!/usr/bin/env python3

import math

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Imu
from std_msgs.msg import Float64


class YawAngleNode(Node):

    def __init__(self):
        super().__init__('yaw_angle_node')

        # ============================================================
        # Parameters
        # ============================================================

        self.declare_parameter(
            'deadband',
            0.003
        )

        self.deadband = (
            self.get_parameter('deadband')
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

        # degree 단위
        self.yaw_deg_pub = self.create_publisher(
            Float64,
            '/body_yaw/angle_deg',
            10
        )

        # radian 단위
        self.yaw_rad_pub = self.create_publisher(
            Float64,
            '/body_yaw/angle_rad',
            10
        )

        # ============================================================
        # Integration variables
        # ============================================================

        self.yaw_rad = 0.0

        self.last_time = None

        self.get_logger().info(
            'Yaw angle integration node started'
        )

        self.get_logger().info(
            'Initial yaw = 0 deg'
        )

        self.get_logger().info(
            f'Deadband = {self.deadband:.6f} rad/s'
        )

    # ================================================================
    # IMU callback
    # ================================================================

    def imu_callback(self, msg):

        # ------------------------------------------------------------
        # 현재 timestamp
        # ------------------------------------------------------------

        current_time = (
            msg.header.stamp.sec
            + msg.header.stamp.nanosec * 1e-9
        )

        # 첫 샘플에서는 dt를 계산할 수 없으므로
        # 시간만 저장하고 종료
        if self.last_time is None:

            self.last_time = current_time
            return

        # ------------------------------------------------------------
        # dt 계산
        # ------------------------------------------------------------

        dt = current_time - self.last_time

        self.last_time = current_time

        # 비정상적인 시간 간격 제거
        if dt <= 0.0 or dt > 0.1:
            return

        # ------------------------------------------------------------
        # Z축 각속도
        #
        # sensor_msgs/Imu:
        # rad/s
        # ------------------------------------------------------------

        yaw_rate = msg.angular_velocity.z

        # ------------------------------------------------------------
        # Deadband
        #
        # 아주 작은 gyro noise를 0으로 처리
        # ------------------------------------------------------------

        if abs(yaw_rate) < self.deadband:
            yaw_rate = 0.0

        # ------------------------------------------------------------
        # Integration
        #
        # theta(k) =
        # theta(k-1) + omega * dt
        # ------------------------------------------------------------

        self.yaw_rad += yaw_rate * dt

        # ------------------------------------------------------------
        # degree 변환
        # ------------------------------------------------------------

        yaw_deg = math.degrees(
            self.yaw_rad
        )

        # ------------------------------------------------------------
        # Publish radian
        # ------------------------------------------------------------

        msg_rad = Float64()

        msg_rad.data = self.yaw_rad

        self.yaw_rad_pub.publish(
            msg_rad
        )

        # ------------------------------------------------------------
        # Publish degree
        # ------------------------------------------------------------

        msg_deg = Float64()

        msg_deg.data = yaw_deg

        self.yaw_deg_pub.publish(
            msg_deg
        )


def main(args=None):

    rclpy.init(args=args)

    node = YawAngleNode()

    try:

        rclpy.spin(node)

    except KeyboardInterrupt:

        pass

    finally:

        node.destroy_node()

        rclpy.shutdown()


if __name__ == '__main__':

    main()

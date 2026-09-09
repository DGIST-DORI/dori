#!/usr/bin/env python3

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Imu
from std_msgs.msg import Float64


class YawDampingNode(Node):

    def __init__(self):
        super().__init__('yaw_damping_node')

        # ============================================================
        # Parameters
        # ============================================================

        self.declare_parameter('kd', 1.0)

        self.declare_parameter(
            'deadband',
            0.01
        )

        self.declare_parameter(
            'max_correction',
            1.0
        )

        self.kd = (
            self.get_parameter('kd')
            .get_parameter_value()
            .double_value
        )

        self.deadband = (
            self.get_parameter('deadband')
            .get_parameter_value()
            .double_value
        )

        self.max_correction = (
            self.get_parameter('max_correction')
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
        # Correction publisher
        #
        # 아직 실제 모터 명령과 연결하지 않고
        # 보정량만 별도 토픽으로 출력
        # ============================================================

        self.correction_pub = self.create_publisher(
            Float64,
            '/body_yaw/correction',
            10
        )

        self.get_logger().info(
            'Yaw damping node started'
        )

        self.get_logger().info(
            f'Kd = {self.kd}'
        )

    # ================================================================
    # IMU callback
    # ================================================================

    def imu_callback(self, msg):

        # ROS sensor_msgs/Imu에서
        # angular_velocity 단위는 rad/s
        yaw_rate = msg.angular_velocity.z

        # ------------------------------------------------------------
        # Deadband
        #
        # 아주 작은 센서 노이즈에는 반응하지 않도록 함
        # ------------------------------------------------------------

        if abs(yaw_rate) < self.deadband:
            yaw_rate = 0.0

        # ------------------------------------------------------------
        # 목표 yaw rate = 0
        #
        # error = desired - measured
        # ------------------------------------------------------------

        error = -yaw_rate

        # ------------------------------------------------------------
        # Damping correction
        # ------------------------------------------------------------

        correction = (
            self.kd * error
        )

        # ------------------------------------------------------------
        # Saturation
        # ------------------------------------------------------------

        if correction > self.max_correction:
            correction = self.max_correction

        elif correction < -self.max_correction:
            correction = -self.max_correction

        # ------------------------------------------------------------
        # Publish
        # ------------------------------------------------------------

        out = Float64()

        out.data = correction

        self.correction_pub.publish(out)


def main(args=None):

    rclpy.init(args=args)

    node = YawDampingNode()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

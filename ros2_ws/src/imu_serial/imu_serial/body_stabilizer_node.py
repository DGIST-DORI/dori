#!/usr/bin/env python3

import math

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float64


class BodyStabilizerNode(Node):

    def __init__(self):
        super().__init__('body_stabilizer_node')

        # ======================================================
        # Parameters
        # ======================================================

        self.declare_parameter(
            'target_pitch_deg',
            0.0
        )

        self.declare_parameter(
            'kp',
            5.0
        )

        self.declare_parameter(
            'kd',
            1.0
        )

        self.declare_parameter(
            'max_torque',
            13.0
        )

        # 기존 5~10 deg는 너무 큼
        self.declare_parameter(
            'angle_deadband_deg',
            1.0
        )

        # PD 계산 주기
        self.declare_parameter(
            'control_frequency_hz',
            100.0
        )

        # 센서 timeout
        self.declare_parameter(
            'sensor_timeout_sec',
            0.10
        )

        # ======================================================
        # Read parameters
        # ======================================================

        self.target_pitch_deg = float(
            self.get_parameter('target_pitch_deg').value
        )

        self.kp = float(
            self.get_parameter('kp').value
        )

        self.kd = float(
            self.get_parameter('kd').value
        )

        self.max_torque = abs(float(
            self.get_parameter('max_torque').value
        ))

        self.angle_deadband_deg = abs(float(
            self.get_parameter('angle_deadband_deg').value
        ))

        self.control_frequency_hz = float(
            self.get_parameter('control_frequency_hz').value
        )

        self.sensor_timeout_sec = float(
            self.get_parameter('sensor_timeout_sec').value
        )

        if self.control_frequency_hz <= 0.0:
            self.control_frequency_hz = 100.0

        self.target_pitch = math.radians(
            self.target_pitch_deg
        )

        self.angle_deadband = math.radians(
            self.angle_deadband_deg
        )

        # ======================================================
        # State
        # ======================================================

        self.pitch = 0.0
        self.pitch_rate = 0.0

        self.pitch_received = False
        self.pitch_rate_received = False

        self.last_pitch_time = None
        self.last_pitch_rate_time = None

        # Debug state
        self.angle_error = 0.0
        self.p_torque = 0.0
        self.d_torque = 0.0
        self.pd_torque = 0.0

        # ======================================================
        # Subscribers
        # ======================================================

        self.pitch_sub = self.create_subscription(
            Float64,
            '/body/pitch',
            self.pitch_callback,
            20
        )

        self.pitch_rate_sub = self.create_subscription(
            Float64,
            '/body/pitch_rate',
            self.pitch_rate_callback,
            20
        )

        # ======================================================
        # Main torque publisher
        # ======================================================

        self.torque_pub = self.create_publisher(
            Float64,
            '/body/stabilization_torque',
            20
        )

        # ======================================================
        # Debug publishers
        # ======================================================

        self.angle_error_pub = self.create_publisher(
            Float64,
            '/body/debug/angle_error',
            20
        )

        self.p_torque_pub = self.create_publisher(
            Float64,
            '/body/debug/p_torque',
            20
        )

        self.d_torque_pub = self.create_publisher(
            Float64,
            '/body/debug/d_torque',
            20
        )

        self.pd_torque_pub = self.create_publisher(
            Float64,
            '/body/debug/pd_torque',
            20
        )

        # ======================================================
        # 100 Hz control timer
        # ======================================================

        self.control_timer = self.create_timer(
            1.0 / self.control_frequency_hz,
            self.control_callback
        )

        self.get_logger().info(
            'Body attitude PD stabilizer started: '
            f'target={self.target_pitch_deg:.2f} deg, '
            f'Kp={self.kp:.3f}, '
            f'Kd={self.kd:.3f}, '
            f'max_torque={self.max_torque:.3f}, '
            f'deadband={self.angle_deadband_deg:.2f} deg, '
            f'frequency={self.control_frequency_hz:.1f} Hz'
        )

    # ==========================================================
    # Helper
    # ==========================================================

    def clamp(self, value, minimum, maximum):
        return max(
            minimum,
            min(value, maximum)
        )

    # ==========================================================
    # Callbacks
    #
    # callback에서는 값만 저장
    # ==========================================================

    def pitch_callback(self, msg):
        self.pitch = msg.data
        self.pitch_received = True
        self.last_pitch_time = self.get_clock().now()

    def pitch_rate_callback(self, msg):
        self.pitch_rate = msg.data
        self.pitch_rate_received = True
        self.last_pitch_rate_time = self.get_clock().now()

    # ==========================================================
    # 100 Hz PD controller
    #
    # error = target - current
    #
    # tau = Kp * error - Kd * pitch_rate
    # ==========================================================

    def control_callback(self):

        if not (
            self.pitch_received
            and self.pitch_rate_received
        ):
            return

        now = self.get_clock().now()

        pitch_age = (
            now - self.last_pitch_time
        ).nanoseconds * 1e-9

        rate_age = (
            now - self.last_pitch_rate_time
        ).nanoseconds * 1e-9

        # ======================================================
        # Sensor timeout
        #
        # IMU 데이터가 오래되면 stabilization torque를 0으로
        # ======================================================

        if (
            pitch_age > self.sensor_timeout_sec
            or
            rate_age > self.sensor_timeout_sec
        ):
            self.publish_zero_torque()
            return

        # ======================================================
        # Pitch error
        # ======================================================

        angle_error = (
            self.target_pitch
            -
            self.pitch
        )

        self.angle_error = angle_error

        # ======================================================
        # P deadband
        #
        # D는 deadband 안에서도 계속 동작
        # ======================================================

        if abs(angle_error) < self.angle_deadband:
            proportional_error = 0.0
        else:
            proportional_error = angle_error

        # ======================================================
        # P term
        # ======================================================

        p_torque = (
            self.kp
            *
            proportional_error
        )

        # ======================================================
        # D term
        #
        # 수정된 IMU에서
        # pitch와 pitch_rate가 같은 +방향이므로
        # -Kd * pitch_rate가 damping 방향
        # ======================================================

        d_torque = (
            -self.kd
            *
            self.pitch_rate
        )

        # ======================================================
        # PD
        # ======================================================

        raw_torque = (
            p_torque
            +
            d_torque
        )

        torque = self.clamp(
            raw_torque,
            -self.max_torque,
            self.max_torque
        )

        self.p_torque = p_torque
        self.d_torque = d_torque
        self.pd_torque = torque

        # ======================================================
        # Publish
        # ======================================================

        torque_msg = Float64()
        torque_msg.data = torque
        self.torque_pub.publish(torque_msg)

        error_msg = Float64()
        error_msg.data = angle_error
        self.angle_error_pub.publish(error_msg)

        p_msg = Float64()
        p_msg.data = p_torque
        self.p_torque_pub.publish(p_msg)

        d_msg = Float64()
        d_msg.data = d_torque
        self.d_torque_pub.publish(d_msg)

        pd_msg = Float64()
        pd_msg.data = torque
        self.pd_torque_pub.publish(pd_msg)

    # ==========================================================
    # Zero output
    # ==========================================================

    def publish_zero_torque(self):

        msg = Float64()
        msg.data = 0.0

        self.torque_pub.publish(msg)


def main(args=None):

    rclpy.init(args=args)

    node = BodyStabilizerNode()

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

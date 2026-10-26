#!/usr/bin/env python3

import math

import rclpy

from rclpy.node import Node
from std_msgs.msg import Float64
from std_msgs.msg import Float64MultiArray


class Servo3PitchFollowerNode(Node):

    def __init__(self):

        super().__init__('servo3_pitch_follower_node')

        # ============================================================
        # Parameters
        # ============================================================

        # logical motor 5 -> physical DXL ID 3
        self.declare_parameter(
            'logical_motor_id',
            5
        )

        # 몸체가 수평일 때 서보 중심 위치
        self.declare_parameter(
            'center_deg',
            180.0
        )

        # Servo safety range
        self.declare_parameter(
            'min_deg',
            135.0
        )

        self.declare_parameter(
            'max_deg',
            225.0
        )

        # +1:
        # body pitch +10 deg -> servo +10 deg
        #
        # -1:
        # body pitch +10 deg -> servo -10 deg
        self.declare_parameter(
            'direction',
            1.0
        )

        # 작은 pitch noise 무시
        self.declare_parameter(
            'pitch_deadband_deg',
            0.5
        )

        # 마지막으로 실제 DXL에 보낸 명령과
        # 이 값보다 적게 차이나면 새 명령 생략
        self.declare_parameter(
            'command_threshold_deg',
            0.2
        )

        # 실제 Dynamixel 명령 전송 주기
        self.declare_parameter(
            'command_rate_hz',
            30.0
        )

        # ============================================================
        # Pitch-rate feedforward gain
        #
        # 단위: second
        #
        # FF [deg]
        # = gain [s] * pitch_rate [deg/s]
        # ============================================================

        self.declare_parameter(
            'pitch_rate_ff_gain',
            0.05
        )

        # ============================================================
        # Pitch-rate limit
        #
        # gyro spike 등으로 FF가 너무 커지는 것 방지
        # ============================================================

        self.declare_parameter(
            'pitch_rate_limit_deg_s',
            180.0
        )

        # ============================================================
        # Get parameters
        # ============================================================

        self.logical_motor_id = (
            self.get_parameter('logical_motor_id')
            .get_parameter_value()
            .integer_value
        )

        self.center_deg = (
            self.get_parameter('center_deg')
            .get_parameter_value()
            .double_value
        )

        self.min_deg = (
            self.get_parameter('min_deg')
            .get_parameter_value()
            .double_value
        )

        self.max_deg = (
            self.get_parameter('max_deg')
            .get_parameter_value()
            .double_value
        )

        self.direction = (
            self.get_parameter('direction')
            .get_parameter_value()
            .double_value
        )

        self.pitch_deadband_deg = (
            self.get_parameter('pitch_deadband_deg')
            .get_parameter_value()
            .double_value
        )

        self.command_threshold_deg = (
            self.get_parameter('command_threshold_deg')
            .get_parameter_value()
            .double_value
        )

        self.command_rate_hz = (
            self.get_parameter('command_rate_hz')
            .get_parameter_value()
            .double_value
        )

        self.pitch_rate_ff_gain = (
            self.get_parameter('pitch_rate_ff_gain')
            .get_parameter_value()
            .double_value
        )

        self.pitch_rate_limit_deg_s = (
            self.get_parameter('pitch_rate_limit_deg_s')
            .get_parameter_value()
            .double_value
        )

        if self.command_rate_hz <= 0.0:

            self.get_logger().warn(
                'command_rate_hz must be > 0. '
                'Using 30.0 Hz instead.'
            )

            self.command_rate_hz = 30.0

        # ============================================================
        # State
        # ============================================================

        self.latest_pitch_deg = 0.0

        self.latest_pitch_rate_deg_s = 0.0

        # FF를 넣기 전 기준 target
        self.latest_base_target_deg = self.center_deg

        # FF를 포함한 최종 target
        self.latest_target_deg = self.center_deg

        self.has_pitch = False

        self.has_pitch_rate = False

        # 마지막으로 실제 DXL에 전송한 target
        self.last_sent_target_deg = None

        # ============================================================
        # Subscriber: body pitch
        #
        # /body/pitch_deg
        # unit = deg
        # ============================================================

        self.pitch_sub = self.create_subscription(
            Float64,
            '/body/pitch_deg',
            self.pitch_callback,
            20
        )

        # ============================================================
        # Subscriber: body pitch rate
        #
        # /body/pitch_rate
        # unit = rad/s
        # ============================================================

        self.pitch_rate_sub = self.create_subscription(
            Float64,
            '/body/pitch_rate',
            self.pitch_rate_callback,
            20
        )

        # ============================================================
        # Dynamixel command publisher
        #
        # data[0] = logical motor ID
        # data[1] = target degree
        # ============================================================

        self.dxl_cmd_pub = self.create_publisher(
            Float64MultiArray,
            '/dxl_position_cmd',
            20
        )

        # ============================================================
        # Debug publishers
        # ============================================================

        # ------------------------------------------------------------
        # 기준 target
        #
        # center + pitch
        #
        # "서보가 원래 있어야 하는 위치"
        # ------------------------------------------------------------

        self.base_target_deg_pub = self.create_publisher(
            Float64,
            '/servo3/base_target_deg',
            20
        )

        # ------------------------------------------------------------
        # 최종 target
        #
        # base_target + pitch-rate FF
        # ------------------------------------------------------------

        self.target_deg_pub = self.create_publisher(
            Float64,
            '/servo3/target_deg',
            20
        )

        # ------------------------------------------------------------
        # FF가 몇 도 추가되었는지
        # ------------------------------------------------------------

        self.ff_deg_pub = self.create_publisher(
            Float64,
            '/servo3/pitch_rate_ff_deg',
            20
        )

        # ------------------------------------------------------------
        # pitch rate를 deg/s로 변환한 값
        # ------------------------------------------------------------

        self.pitch_rate_deg_s_pub = self.create_publisher(
            Float64,
            '/servo3/pitch_rate_deg_s',
            20
        )

        # ============================================================
        # Command timer
        #
        # DXL 명령은 callback마다 바로 보내지 않고
        # 여기서 고정 주기로 최신 target만 전송
        # ============================================================

        self.command_timer = self.create_timer(
            1.0 / self.command_rate_hz,
            self.command_timer_callback
        )

        # ============================================================
        # Startup logs
        # ============================================================

        self.get_logger().info(
            'Servo 3 pitch follower started'
        )

        self.get_logger().info(
            f'Logical motor ID = {self.logical_motor_id}'
        )

        self.get_logger().info(
            f'Center = {self.center_deg:.1f} deg'
        )

        self.get_logger().info(
            f'Safety range = '
            f'{self.min_deg:.1f} ~ {self.max_deg:.1f} deg'
        )

        self.get_logger().info(
            f'Direction = {self.direction:+.1f}'
        )

        self.get_logger().info(
            f'Pitch deadband = '
            f'{self.pitch_deadband_deg:.2f} deg'
        )

        self.get_logger().info(
            f'Command threshold = '
            f'{self.command_threshold_deg:.2f} deg'
        )

        self.get_logger().info(
            f'Command rate = '
            f'{self.command_rate_hz:.1f} Hz'
        )

        self.get_logger().info(
            f'Pitch-rate FF gain = '
            f'{self.pitch_rate_ff_gain:.3f} s'
        )

        self.get_logger().info(
            f'Pitch-rate limit = '
            f'{self.pitch_rate_limit_deg_s:.1f} deg/s'
        )

    # ================================================================
    # Pitch callback
    # ================================================================

    def pitch_callback(self, msg):

        pitch_deg = msg.data

        # ============================================================
        # Pitch deadband
        # ============================================================

        if abs(pitch_deg) < self.pitch_deadband_deg:

            pitch_deg = 0.0

        self.latest_pitch_deg = pitch_deg

        self.has_pitch = True

        self.update_target()

    # ================================================================
    # Pitch-rate callback
    #
    # input: rad/s
    # ================================================================

    def pitch_rate_callback(self, msg):

        # rad/s -> deg/s
        pitch_rate_deg_s = math.degrees(
            msg.data
        )

        # ============================================================
        # Clamp
        # ============================================================

        pitch_rate_deg_s = max(
            -self.pitch_rate_limit_deg_s,
            min(
                self.pitch_rate_limit_deg_s,
                pitch_rate_deg_s
            )
        )

        self.latest_pitch_rate_deg_s = pitch_rate_deg_s

        self.has_pitch_rate = True

        # ============================================================
        # Debug: pitch rate
        # ============================================================

        rate_msg = Float64()

        rate_msg.data = pitch_rate_deg_s

        self.pitch_rate_deg_s_pub.publish(
            rate_msg
        )

        self.update_target()

    # ================================================================
    # Calculate target
    # ================================================================

    def update_target(self):

        if not self.has_pitch:

            return

        # ============================================================
        # 1. Base target
        #
        # FF가 없을 때 원래 따라가고 싶은 위치
        #
        # base =
        # center + direction * pitch
        # ============================================================

        base_target_deg = (
            self.center_deg
            +
            self.direction
            *
            self.latest_pitch_deg
        )

        # ============================================================
        # Base target safety clamp
        # ============================================================

        base_target_deg = max(
            self.min_deg,
            min(
                self.max_deg,
                base_target_deg
            )
        )

        self.latest_base_target_deg = (
            base_target_deg
        )

        # ============================================================
        # Publish base target
        # ============================================================

        base_msg = Float64()

        base_msg.data = base_target_deg

        self.base_target_deg_pub.publish(
            base_msg
        )

        # ============================================================
        # 2. Pitch rate
        # ============================================================

        if self.has_pitch_rate:

            pitch_rate_deg_s = (
                self.latest_pitch_rate_deg_s
            )

        else:

            pitch_rate_deg_s = 0.0

        # ============================================================
        # 3. Feedforward
        #
        # [s] * [deg/s]
        # = [deg]
        # ============================================================

        ff_deg = (
            self.pitch_rate_ff_gain
            *
            pitch_rate_deg_s
        )

        # direction까지 포함한
        # 실제 servo 방향 기준 FF
        servo_ff_deg = (
            self.direction
            *
            ff_deg
        )

        # ============================================================
        # 4. Final command
        #
        # 주의:
        #
        # 여기서는 base_target에 FF를 더한다.
        #
        # base_target 자체에 이미 direction이 적용되어 있음.
        # ============================================================

        target_deg = (
            base_target_deg
            +
            servo_ff_deg
        )

        # ============================================================
        # Final safety clamp
        # ============================================================

        target_deg = max(
            self.min_deg,
            min(
                self.max_deg,
                target_deg
            )
        )

        self.latest_target_deg = target_deg

        # ============================================================
        # Debug: final target
        # ============================================================

        target_msg = Float64()

        target_msg.data = target_deg

        self.target_deg_pub.publish(
            target_msg
        )

        # ============================================================
        # Debug: FF contribution
        # ============================================================

        ff_msg = Float64()

        ff_msg.data = servo_ff_deg

        self.ff_deg_pub.publish(
            ff_msg
        )

    # ================================================================
    # Dynamixel command timer
    # ================================================================

    def command_timer_callback(self):

        if not self.has_pitch:

            return

        target_deg = self.latest_target_deg

        # ============================================================
        # Command threshold
        # ============================================================

        if self.last_sent_target_deg is not None:

            delta_deg = abs(
                target_deg
                -
                self.last_sent_target_deg
            )

            if delta_deg < self.command_threshold_deg:

                return

        # ============================================================
        # DXL command
        #
        # logical motor 5
        # -> physical DXL ID 3
        # ============================================================

        cmd = Float64MultiArray()

        cmd.data = [
            float(self.logical_motor_id),
            float(target_deg)
        ]

        self.dxl_cmd_pub.publish(
            cmd
        )

        self.last_sent_target_deg = target_deg


def main(args=None):

    rclpy.init(args=args)

    node = Servo3PitchFollowerNode()

    try:

        rclpy.spin(node)

    except KeyboardInterrupt:

        pass

    finally:

        node.destroy_node()

        rclpy.shutdown()


if __name__ == '__main__':

    main()

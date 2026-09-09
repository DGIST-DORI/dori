import rclpy
from rclpy.node import Node

from sensor_msgs.msg import JointState
from robot_msgs.msg import MitCommand


class SingleWheelTorqueTestNode(Node):

    def __init__(self):
        super().__init__('single_wheel_torque_test_node')

        # ======================================================
        # Parameters
        # ======================================================

        # 'left' 또는 'right'
        self.declare_parameter('wheel', 'left')

        # +1 forward / -1 reverse
        self.declare_parameter('direction', 1)

        # 테스트 torque 단계
        self.declare_parameter(
            'torque_steps',
            [2.0, 4.0, 6.0]
        )

        # 각 torque를 몇 초 유지할지
        self.declare_parameter(
            'hold_duration',
            2.0
        )

        # 각 torque 사이에 0 Nm 유지
        self.declare_parameter(
            'zero_duration',
            2.0
        )

        # 제어 주파수
        self.declare_parameter(
            'control_frequency',
            100.0
        )

        # 반대 방향 속도가 이 값보다 커지면 즉시 정지
        self.declare_parameter(
            'reverse_fault_velocity',
            2.0
        )

        # 절대 overspeed
        self.declare_parameter(
            'overspeed_limit',
            5.0
        )

        # ======================================================
        # Read parameters
        # ======================================================

        self.wheel = str(
            self.get_parameter('wheel').value
        ).lower()

        if self.wheel not in ['left', 'right']:
            raise ValueError(
                "wheel parameter must be 'left' or 'right'"
            )

        self.direction = int(
            self.get_parameter('direction').value
        )

        self.direction = 1 if self.direction >= 0 else -1

        self.torque_steps = [
            abs(float(x))
            for x in
            self.get_parameter('torque_steps').value
        ]

        self.hold_duration = float(
            self.get_parameter('hold_duration').value
        )

        self.zero_duration = float(
            self.get_parameter('zero_duration').value
        )

        self.control_frequency = float(
            self.get_parameter('control_frequency').value
        )

        self.reverse_fault_velocity = abs(
            float(
                self.get_parameter(
                    'reverse_fault_velocity'
                ).value
            )
        )

        self.overspeed_limit = abs(
            float(
                self.get_parameter(
                    'overspeed_limit'
                ).value
            )
        )

        self.dt = 1.0 / self.control_frequency

        # ======================================================
        # Wheel state
        # ======================================================

        self.left_position = 0.0
        self.right_position = 0.0

        self.left_velocity = 0.0
        self.right_velocity = 0.0

        self.left_effort = 0.0
        self.right_effort = 0.0

        self.joint_received = False

        # ======================================================
        # Test state
        # ======================================================

        self.step_index = 0

        self.phase = 'WAIT'

        self.phase_start_time = self.get_clock().now()

        self.test_finished = False

        # ======================================================
        # ROS interfaces
        # ======================================================

        self.sub = self.create_subscription(
            JointState,
            '/joint_states',
            self.joint_state_callback,
            100
        )

        self.pub = self.create_publisher(
            MitCommand,
            '/bldc_mit_speed_cmd',
            20
        )

        self.timer = self.create_timer(
            self.dt,
            self.control_loop
        )

        # ======================================================
        # Log
        # ======================================================

        direction_text = (
            'FORWARD'
            if self.direction > 0
            else 'REVERSE'
        )

        self.get_logger().info(
            '========================================'
        )
        self.get_logger().info(
            'Single wheel torque validation'
        )
        self.get_logger().info(
            f'Wheel = {self.wheel.upper()}'
        )
        self.get_logger().info(
            f'Direction = {direction_text}'
        )
        self.get_logger().info(
            f'Torque steps = {self.torque_steps}'
        )
        self.get_logger().info(
            'Other wheel will receive 0 Nm.'
        )
        self.get_logger().info(
            '========================================'
        )


    # ==========================================================
    # Joint state
    # ==========================================================

    def joint_state_callback(self, msg):

        for i, name in enumerate(msg.name):

            if name == 'left_wheel_joint':

                if i < len(msg.position):
                    self.left_position = float(
                        msg.position[i]
                    )

                if i < len(msg.velocity):
                    self.left_velocity = float(
                        msg.velocity[i]
                    )

                if i < len(msg.effort):
                    self.left_effort = float(
                        msg.effort[i]
                    )

            elif name == 'right_wheel_joint':

                if i < len(msg.position):
                    self.right_position = float(
                        msg.position[i]
                    )

                if i < len(msg.velocity):
                    self.right_velocity = float(
                        msg.velocity[i]
                    )

                if i < len(msg.effort):
                    self.right_effort = float(
                        msg.effort[i]
                    )

        self.joint_received = True


    # ==========================================================
    # MIT torque command
    # ==========================================================

    def publish_motor(self, motor_id, torque):

        msg = MitCommand()

        msg.motor_id = motor_id

        msg.p_des = 0.0
        msg.v_des = 0.0

        msg.kp = 0.0
        msg.kd = 0.0

        msg.tau_ff = float(torque)

        self.pub.publish(msg)


    def publish_torques(
        self,
        left_torque,
        right_torque
    ):

        self.publish_motor(
            1,
            left_torque
        )

        self.publish_motor(
            2,
            right_torque
        )


    def send_zero(self):

        for _ in range(10):

            self.publish_torques(
                0.0,
                0.0
            )


    # ==========================================================
    # Time
    # ==========================================================

    def phase_elapsed(self):

        return (
            self.get_clock().now()
            -
            self.phase_start_time
        ).nanoseconds * 1e-9


    def set_phase(self, phase):

        self.phase = phase

        self.phase_start_time = (
            self.get_clock().now()
        )


    # ==========================================================
    # Safety
    # ==========================================================

    def check_fault(self):

        if self.wheel == 'left':

            velocity = self.left_velocity

        else:

            velocity = self.right_velocity

        directional_velocity = (
            self.direction
            *
            velocity
        )

        # ------------------------------------------
        # Absolute overspeed
        # ------------------------------------------

        if abs(velocity) >= self.overspeed_limit:

            self.get_logger().error(
                f'OVERSPEED: '
                f'{velocity:+.3f} rad/s'
            )

            self.send_zero()

            self.test_finished = True

            return True

        # ------------------------------------------
        # High-speed reverse motion
        # ------------------------------------------

        if (
            directional_velocity
            <=
            -self.reverse_fault_velocity
        ):

            self.get_logger().error(
                'REVERSE DIRECTION FAULT: '
                f'{velocity:+.3f} rad/s'
            )

            self.send_zero()

            self.test_finished = True

            return True

        return False


    # ==========================================================
    # Control loop
    # ==========================================================

    def control_loop(self):

        if self.test_finished:
            return

        if not self.joint_received:

            self.publish_torques(
                0.0,
                0.0
            )

            self.get_logger().warn(
                'Waiting for /joint_states...',
                throttle_duration_sec=1.0
            )

            return

        # ======================================================
        # WAIT
        # ======================================================

        if self.phase == 'WAIT':

            self.send_zero()

            self.set_phase(
                'ZERO'
            )

            return

        # ======================================================
        # ZERO
        # ======================================================

        if self.phase == 'ZERO':

            self.publish_torques(
                0.0,
                0.0
            )

            if (
                self.phase_elapsed()
                >=
                self.zero_duration
            ):

                if (
                    self.step_index
                    >=
                    len(self.torque_steps)
                ):

                    self.get_logger().info(
                        'All torque steps complete.'
                    )

                    self.send_zero()

                    self.test_finished = True

                    return

                torque = (
                    self.direction
                    *
                    self.torque_steps[
                        self.step_index
                    ]
                )

                self.get_logger().info(
                    ''
                )

                self.get_logger().info(
                    '----------------------------------------'
                )

                self.get_logger().info(
                    f'Step {self.step_index + 1}'
                )

                self.get_logger().info(
                    f'Command torque = '
                    f'{torque:+.2f} Nm'
                )

                self.get_logger().info(
                    '----------------------------------------'
                )

                self.set_phase(
                    'TORQUE'
                )

            return

        # ======================================================
        # TORQUE
        # ======================================================

        if self.phase == 'TORQUE':

            torque = (
                self.direction
                *
                self.torque_steps[
                    self.step_index
                ]
            )

            if self.wheel == 'left':

                self.publish_torques(
                    torque,
                    0.0
                )

            else:

                self.publish_torques(
                    0.0,
                    torque
                )

            if self.check_fault():
                return

            self.get_logger().info(
                f'{self.wheel.upper()} | '
                f'tau={torque:+.2f} Nm | '
                f'L pos={self.left_position:+.3f} '
                f'vel={self.left_velocity:+.3f} '
                f'eff={self.left_effort:+.2f} | '
                f'R pos={self.right_position:+.3f} '
                f'vel={self.right_velocity:+.3f} '
                f'eff={self.right_effort:+.2f}',
                throttle_duration_sec=0.2
            )

            if (
                self.phase_elapsed()
                >=
                self.hold_duration
            ):

                self.send_zero()

                self.step_index += 1

                self.set_phase(
                    'ZERO'
                )

            return


    def destroy_node(self):

        super().destroy_node()


def main(args=None):

    rclpy.init(args=args)

    node = SingleWheelTorqueTestNode()

    try:

        rclpy.spin(node)

    except KeyboardInterrupt:

        if rclpy.ok():

            node.get_logger().warn(
                'Interrupted. Sending 0 Nm.'
            )

            node.send_zero()

    finally:

        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()

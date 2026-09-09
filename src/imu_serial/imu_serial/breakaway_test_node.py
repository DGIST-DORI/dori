import rclpy
from rclpy.node import Node

from sensor_msgs.msg import JointState
from robot_msgs.msg import MitCommand


class BreakawayTestNode(Node):

    def __init__(self):
        super().__init__('breakaway_test_node')

        # ======================================================
        # Parameters
        # ======================================================

        # +1 : forward
        # -1 : reverse
        self.declare_parameter(
            'direction',
            1
        )

        # 시작 torque [Nm]
        self.declare_parameter(
            'start_torque',
            0.0
        )

        # torque 증가 속도 [Nm/s]
        self.declare_parameter(
            'torque_ramp_rate',
            0.5
        )

        # 안전 최대 torque [Nm]
        self.declare_parameter(
            'max_torque',
            15.0
        )

        # 움직였다고 판단할 wheel velocity [rad/s]
        self.declare_parameter(
            'velocity_threshold',
            0.15
        )

        # threshold를 연속 몇 샘플 넘어야
        # 실제 breakaway로 인정할지
        self.declare_parameter(
            'required_samples',
            5
        )

        # control frequency [Hz]
        self.declare_parameter(
            'control_frequency',
            50.0
        )

        # ======================================================
        # Read parameters
        # ======================================================

        self.direction = int(
            self.get_parameter('direction').value
        )

        self.direction = (
            1
            if self.direction >= 0
            else -1
        )

        self.start_torque = abs(
            float(
                self.get_parameter('start_torque').value
            )
        )

        self.torque_ramp_rate = abs(
            float(
                self.get_parameter('torque_ramp_rate').value
            )
        )

        self.max_torque = abs(
            float(
                self.get_parameter('max_torque').value
            )
        )

        self.velocity_threshold = abs(
            float(
                self.get_parameter('velocity_threshold').value
            )
        )

        self.required_samples = int(
            self.get_parameter('required_samples').value
        )

        self.control_frequency = float(
            self.get_parameter('control_frequency').value
        )

        # ======================================================
        # Joint state
        # ======================================================

        self.left_velocity = 0.0
        self.right_velocity = 0.0

        self.left_received = False
        self.right_received = False

        # ======================================================
        # Breakaway detection state
        # ======================================================

        self.left_motion_count = 0
        self.right_motion_count = 0

        self.left_breakaway_detected = False
        self.right_breakaway_detected = False

        self.left_breakaway_torque = None
        self.right_breakaway_torque = None

        self.left_breakaway_velocity = None
        self.right_breakaway_velocity = None

        # ======================================================
        # Test state
        # ======================================================

        self.current_torque = self.start_torque

        self.test_finished = False

        self.dt = (
            1.0 /
            self.control_frequency
        )

        # ======================================================
        # Subscriber
        # ======================================================

        self.joint_state_sub = self.create_subscription(
            JointState,
            '/joint_states',
            self.joint_state_callback,
            50
        )

        # ======================================================
        # Publisher
        # ======================================================

        self.command_pub = self.create_publisher(
            MitCommand,
            '/bldc_mit_speed_cmd',
            20
        )

        # ======================================================
        # Timer
        # ======================================================

        self.timer = self.create_timer(
            self.dt,
            self.control_loop
        )

        # ======================================================
        # Startup log
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
            'Individual wheel breakaway test started'
        )

        self.get_logger().info(
            f'Direction = {direction_text}'
        )

        self.get_logger().info(
            f'Ramp rate = '
            f'{self.torque_ramp_rate:.2f} Nm/s'
        )

        self.get_logger().info(
            f'Max torque = '
            f'{self.max_torque:.2f} Nm'
        )

        self.get_logger().info(
            f'Velocity threshold = '
            f'{self.velocity_threshold:.3f} rad/s'
        )

        self.get_logger().info(
            f'Required consecutive samples = '
            f'{self.required_samples}'
        )

        self.get_logger().info(
            'Both wheels receive the same torque.'
        )

        self.get_logger().info(
            'Left/right breakaway is detected independently.'
        )

        self.get_logger().info(
            'Keep emergency stop ready.'
        )

        self.get_logger().info(
            '========================================'
        )


    # ==========================================================
    # Joint state callback
    # ==========================================================

    def joint_state_callback(
        self,
        msg
    ):

        count = min(
            len(msg.name),
            len(msg.velocity)
        )

        for i in range(count):

            if msg.name[i] == 'left_wheel_joint':

                self.left_velocity = (
                    msg.velocity[i]
                )

                self.left_received = True

            elif msg.name[i] == 'right_wheel_joint':

                self.right_velocity = (
                    msg.velocity[i]
                )

                self.right_received = True


    # ==========================================================
    # MIT torque command
    #
    # velocity/position feedback terms are disabled:
    #
    # kp = 0
    # kd = 0
    # v_des = 0
    #
    # Therefore tau_ff is the commanded torque term.
    # ==========================================================

    def publish_torque(
        self,
        torque
    ):

        for motor_id in [1, 2]:

            msg = MitCommand()

            msg.motor_id = motor_id

            msg.p_des = 0.0
            msg.v_des = 0.0

            msg.kp = 0.0
            msg.kd = 0.0

            msg.tau_ff = torque

            self.command_pub.publish(
                msg
            )


    # ==========================================================
    # Stop motors
    # ==========================================================

    def stop_motors(
        self
    ):

        if not rclpy.ok():
            return

        for _ in range(10):

            self.publish_torque(
                0.0
            )


    # ==========================================================
    # Print final result
    # ==========================================================

    def print_result(
        self
    ):

        self.get_logger().info(
            ''
        )

        self.get_logger().info(
            '========================================'
        )

        self.get_logger().info(
            'FINAL BREAKAWAY RESULT'
        )

        if self.left_breakaway_detected:

            self.get_logger().info(
                f'LEFT  : '
                f'{self.left_breakaway_torque:+.3f} Nm '
                f'@ {self.left_breakaway_velocity:+.3f} rad/s'
            )

        else:

            self.get_logger().warn(
                'LEFT  : NOT DETECTED'
            )

        if self.right_breakaway_detected:

            self.get_logger().info(
                f'RIGHT : '
                f'{self.right_breakaway_torque:+.3f} Nm '
                f'@ {self.right_breakaway_velocity:+.3f} rad/s'
            )

        else:

            self.get_logger().warn(
                'RIGHT : NOT DETECTED'
            )

        self.get_logger().info(
            '========================================'
        )


    # ==========================================================
    # Main test loop
    # ==========================================================

    def control_loop(
        self
    ):

        if self.test_finished:
            return

        # ------------------------------------------------------
        # Wait for joint states
        # ------------------------------------------------------

        if not (
            self.left_received
            and
            self.right_received
        ):

            self.get_logger().warn(
                'Waiting for left/right wheel velocity '
                'from /joint_states...',
                throttle_duration_sec=1.0
            )

            return

        # ------------------------------------------------------
        # Current signed torque
        # ------------------------------------------------------

        signed_torque = (
            self.direction
            *
            self.current_torque
        )

        self.publish_torque(
            signed_torque
        )

        # ------------------------------------------------------
        # Direction-aware wheel velocity
        #
        # Forward test:
        #   positive velocity = intended direction
        #
        # Reverse test:
        #   negative raw velocity becomes positive
        #   after multiplication by direction
        # ------------------------------------------------------

        left_directional_velocity = (
            self.direction
            *
            self.left_velocity
        )

        right_directional_velocity = (
            self.direction
            *
            self.right_velocity
        )

        # ======================================================
        # LEFT breakaway detection
        # ======================================================

        if not self.left_breakaway_detected:

            if (
                left_directional_velocity
                >
                self.velocity_threshold
            ):

                self.left_motion_count += 1

            else:

                self.left_motion_count = 0


            if (
                self.left_motion_count
                >=
                self.required_samples
            ):

                self.left_breakaway_detected = True

                self.left_breakaway_torque = (
                    signed_torque
                )

                self.left_breakaway_velocity = (
                    self.left_velocity
                )

                self.get_logger().info(
                    ''
                )

                self.get_logger().info(
                    '----------------------------------------'
                )

                self.get_logger().info(
                    'LEFT BREAKAWAY DETECTED'
                )

                self.get_logger().info(
                    f'Torque = '
                    f'{self.left_breakaway_torque:+.3f} Nm'
                )

                self.get_logger().info(
                    f'Velocity = '
                    f'{self.left_breakaway_velocity:+.3f} rad/s'
                )

                self.get_logger().info(
                    '----------------------------------------'
                )

        # ======================================================
        # RIGHT breakaway detection
        # ======================================================

        if not self.right_breakaway_detected:

            if (
                right_directional_velocity
                >
                self.velocity_threshold
            ):

                self.right_motion_count += 1

            else:

                self.right_motion_count = 0


            if (
                self.right_motion_count
                >=
                self.required_samples
            ):

                self.right_breakaway_detected = True

                self.right_breakaway_torque = (
                    signed_torque
                )

                self.right_breakaway_velocity = (
                    self.right_velocity
                )

                self.get_logger().info(
                    ''
                )

                self.get_logger().info(
                    '----------------------------------------'
                )

                self.get_logger().info(
                    'RIGHT BREAKAWAY DETECTED'
                )

                self.get_logger().info(
                    f'Torque = '
                    f'{self.right_breakaway_torque:+.3f} Nm'
                )

                self.get_logger().info(
                    f'Velocity = '
                    f'{self.right_breakaway_velocity:+.3f} rad/s'
                )

                self.get_logger().info(
                    '----------------------------------------'
                )

        # ======================================================
        # Both wheels detected
        # ======================================================

        if (
            self.left_breakaway_detected
            and
            self.right_breakaway_detected
        ):

            self.stop_motors()

            self.test_finished = True

            self.print_result()

            self.get_logger().info(
                'Motors commanded to 0 Nm.'
            )

            return

        # ======================================================
        # Increase torque
        # ======================================================

        self.current_torque += (
            self.torque_ramp_rate
            *
            self.dt
        )

        # ======================================================
        # Maximum torque
        # ======================================================

        if (
            self.current_torque
            >
            self.max_torque
        ):

            self.stop_motors()

            self.test_finished = True

            self.get_logger().warn(
                ''
            )

            self.get_logger().warn(
                '========================================'
            )

            self.get_logger().warn(
                'MAX TORQUE REACHED'
            )

            self.get_logger().warn(
                f'Maximum test torque = '
                f'{self.max_torque:.2f} Nm'
            )

            self.print_result()

            self.get_logger().warn(
                'Motors commanded to 0 Nm.'
            )

            return

        # ======================================================
        # Running debug
        # ======================================================

        left_state = (
            'DONE'
            if self.left_breakaway_detected
            else f'{self.left_motion_count}/{self.required_samples}'
        )

        right_state = (
            'DONE'
            if self.right_breakaway_detected
            else f'{self.right_motion_count}/{self.required_samples}'
        )

        self.get_logger().info(
            f'tau={signed_torque:+6.2f} Nm | '
            f'L={self.left_velocity:+6.3f} rad/s '
            f'[{left_state}] | '
            f'R={self.right_velocity:+6.3f} rad/s '
            f'[{right_state}]',
            throttle_duration_sec=0.2
        )


    # ==========================================================
    # Node destruction
    # ==========================================================

    def destroy_node(
        self
    ):

        super().destroy_node()


def main(
    args=None
):

    rclpy.init(
        args=args
    )

    node = BreakawayTestNode()

    try:

        rclpy.spin(
            node
        )

    except KeyboardInterrupt:

        if rclpy.ok():

            node.get_logger().warn(
                'Test interrupted. Sending 0 Nm.'
            )

            node.stop_motors()

    finally:

        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()

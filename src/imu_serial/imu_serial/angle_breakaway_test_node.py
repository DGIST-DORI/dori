import csv
import json
import math
import os

from datetime import datetime
from pathlib import Path

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray


class AngleBreakawayTestNode(Node):

    def __init__(self):

        super().__init__(
            'angle_breakaway_test_node'
        )

        # ======================================================
        # Experiment parameters
        # ======================================================

        # +1 forward
        # -1 reverse
        self.declare_parameter(
            'direction',
            1
        )

        # 최대 허용 torque
        self.declare_parameter(
            'max_torque',
            15.0
        )

        # torque 증가율 [Nm/s]
        self.declare_parameter(
            'ramp_rate',
            0.2
        )

        self.declare_parameter(
            'control_frequency',
            100.0
        )

        # 시작 전에 zero torque 유지
        self.declare_parameter(
            'zero_hold_before_sec',
            3.0
        )

        # 종료 후 zero torque 유지
        self.declare_parameter(
            'zero_hold_after_sec',
            3.0
        )

        # ======================================================
        # Breakaway detection
        # ======================================================

        # 움직였다고 판단할 최소 속도
        self.declare_parameter(
            'breakaway_velocity_threshold',
            0.30
        )

        # 100 Hz에서 30 samples = 0.3 sec
        self.declare_parameter(
            'breakaway_required_samples',
            30
        )

        # 후보 구간 동안 최소 실제 위치 변화
        self.declare_parameter(
            'breakaway_position_change_threshold',
            0.05
        )

        # ======================================================
        # Safety
        # ======================================================

        # 같은 방향으로 너무 빨라질 경우
        self.declare_parameter(
            'overspeed_threshold',
            4.0
        )

        # 명령 torque 반대 방향으로 급회전 시
        self.declare_parameter(
            'wrong_direction_velocity_threshold',
            2.0
        )

        self.declare_parameter(
            'joint_state_timeout_sec',
            0.20
        )

        # ======================================================
        # Output
        # ======================================================

        self.declare_parameter(
            'output_directory',
            os.path.expanduser(
                '~/robot_ws/data/friction'
            )
        )

        # ======================================================
        # Read parameters
        # ======================================================

        self.direction = int(
            self.get_parameter(
                'direction'
            ).value
        )

        self.direction = (
            1 if self.direction >= 0 else -1
        )

        self.max_torque = abs(
            float(
                self.get_parameter(
                    'max_torque'
                ).value
            )
        )

        self.ramp_rate = abs(
            float(
                self.get_parameter(
                    'ramp_rate'
                ).value
            )
        )

        self.control_frequency = float(
            self.get_parameter(
                'control_frequency'
            ).value
        )

        self.zero_hold_before_sec = float(
            self.get_parameter(
                'zero_hold_before_sec'
            ).value
        )

        self.zero_hold_after_sec = float(
            self.get_parameter(
                'zero_hold_after_sec'
            ).value
        )

        self.breakaway_velocity_threshold = abs(
            float(
                self.get_parameter(
                    'breakaway_velocity_threshold'
                ).value
            )
        )

        self.breakaway_required_samples = int(
            self.get_parameter(
                'breakaway_required_samples'
            ).value
        )

        self.breakaway_position_change_threshold = abs(
            float(
                self.get_parameter(
                    'breakaway_position_change_threshold'
                ).value
            )
        )

        self.overspeed_threshold = abs(
            float(
                self.get_parameter(
                    'overspeed_threshold'
                ).value
            )
        )

        self.wrong_direction_velocity_threshold = abs(
            float(
                self.get_parameter(
                    'wrong_direction_velocity_threshold'
                ).value
            )
        )

        self.joint_state_timeout_sec = float(
            self.get_parameter(
                'joint_state_timeout_sec'
            ).value
        )

        self.output_directory = os.path.expanduser(
            str(
                self.get_parameter(
                    'output_directory'
                ).value
            )
        )

        self.dt = (
            1.0
            /
            self.control_frequency
        )

        # ======================================================
        # Experiment state
        # ======================================================

        self.phase = 'WAIT_JOINT'

        self.current_torque = 0.0

        self.test_finished = False

        self.safety_triggered = False

        self.fault_type = 'NONE'

        self.safety_reason = ''

        # ======================================================
        # Timing
        # ======================================================

        self.test_start_time = (
            self.get_clock().now()
        )

        self.phase_start_time = (
            self.get_clock().now()
        )

        self.last_joint_state_time = None

        # ======================================================
        # Joint feedback
        # ======================================================

        self.left_position = 0.0
        self.right_position = 0.0

        self.left_velocity = 0.0
        self.right_velocity = 0.0

        self.left_effort = 0.0
        self.right_effort = 0.0

        self.left_temperature = float('nan')
        self.right_temperature = float('nan')

        self.left_received = False
        self.right_received = False

        # ======================================================
        # Initial condition
        # ======================================================

        self.initial_left_position = None
        self.initial_right_position = None

        self.initial_left_temperature = None
        self.initial_right_temperature = None

        # ======================================================
        # Breakaway detection
        # ======================================================

        self.left_count = 0
        self.right_count = 0

        self.left_candidate_start_position = None
        self.right_candidate_start_position = None

        self.left_breakaway = False
        self.right_breakaway = False

        self.left_breakaway_torque = None
        self.right_breakaway_torque = None

        self.left_breakaway_feedback_effort = None
        self.right_breakaway_feedback_effort = None

        self.left_breakaway_velocity = None
        self.right_breakaway_velocity = None

        self.left_breakaway_position = None
        self.right_breakaway_position = None

        self.left_breakaway_delta_position = None
        self.right_breakaway_delta_position = None

        # ======================================================
        # Output files
        # ======================================================

        Path(
            self.output_directory
        ).mkdir(
            parents=True,
            exist_ok=True
        )

        timestamp = datetime.now().strftime(
            '%Y%m%d_%H%M%S'
        )

        direction_name = (
            'forward'
            if self.direction > 0
            else 'reverse'
        )

        self.run_name = (
            f'angle_breakaway_'
            f'{direction_name}_'
            f'{timestamp}'
        )

        self.raw_path = os.path.join(
            self.output_directory,
            self.run_name + '_raw.csv'
        )

        self.summary_path = os.path.join(
            self.output_directory,
            self.run_name + '_summary.json'
        )

        self.raw_file = open(
            self.raw_path,
            'w',
            newline=''
        )

        self.raw_writer = csv.writer(
            self.raw_file
        )

        self.raw_writer.writerow([

            'ros_time_sec',
            'elapsed_sec',
            'phase',

            'direction',

            'command_torque_nm',

            'left_position_rad',
            'right_position_rad',

            'left_velocity_rad_s',
            'right_velocity_rad_s',

            'left_effort_feedback_nm',
            'right_effort_feedback_nm',

            'initial_left_position_rad',
            'initial_right_position_rad',

            'left_breakaway',
            'right_breakaway',

            'safety_triggered',
            'fault_type',
        ])

        # ======================================================
        # Publishers / subscribers
        # ======================================================

        self.left_pub = self.create_publisher(
            Float64MultiArray,
            '/left_bldc_effort_controller/commands',
            10
        )

        self.right_pub = self.create_publisher(
            Float64MultiArray,
            '/right_bldc_effort_controller/commands',
            10
        )

        self.joint_sub = self.create_subscription(
            JointState,
            '/joint_states',
            self.joint_callback,
            100
        )

        self.timer = self.create_timer(
            self.dt,
            self.control_loop
        )

        # ======================================================
        # Logs
        # ======================================================

        self.get_logger().info(
            '========================================'
        )

        self.get_logger().info(
            'ANGLE-DEPENDENT BREAKAWAY TEST'
        )

        self.get_logger().info(
            f'Direction = {direction_name.upper()}'
        )

        self.get_logger().info(
            f'Max torque = '
            f'{self.max_torque:.2f} Nm'
        )

        self.get_logger().info(
            f'Ramp rate = '
            f'{self.ramp_rate:.3f} Nm/s'
        )

        self.get_logger().info(
            'Hardware mode must be CURRENT_LOOP'
        )

        self.get_logger().info(
            'kp=0, kd=0, v_des=0'
        )

        self.get_logger().info(
            f'Raw = {self.raw_path}'
        )

        self.get_logger().info(
            '========================================'
        )


    # ==========================================================
    # Time
    # ==========================================================

    def elapsed(self):

        return (
            self.get_clock().now()
            -
            self.test_start_time
        ).nanoseconds * 1e-9


    def phase_elapsed(self):

        return (
            self.get_clock().now()
            -
            self.phase_start_time
        ).nanoseconds * 1e-9


    def set_phase(
        self,
        phase
    ):

        self.phase = phase

        self.phase_start_time = (
            self.get_clock().now()
        )


    def joint_state_age(self):

        if self.last_joint_state_time is None:

            return float('inf')

        return (
            self.get_clock().now()
            -
            self.last_joint_state_time
        ).nanoseconds * 1e-9


    # ==========================================================
    # Joint state
    # ==========================================================

    def joint_callback(
        self,
        msg
    ):

        self.last_joint_state_time = (
            self.get_clock().now()
        )

        for i, name in enumerate(
            msg.name
        ):

            if name == 'left_wheel_joint':

                if i < len(msg.position):

                    self.left_position = float(
                        msg.position[i]
                    )

                if i < len(msg.velocity):

                    self.left_velocity = float(
                        msg.velocity[i]
                    )

                    self.left_received = True

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

                    self.right_received = True

                if i < len(msg.effort):

                    self.right_effort = float(
                        msg.effort[i]
                    )


    # ==========================================================
    # Command
    # ==========================================================

    def publish_torque(
        self,
        torque
    ):

        left_msg = Float64MultiArray()

        left_msg.data = [
            float(torque)
        ]

        right_msg = Float64MultiArray()

        right_msg.data = [
            float(torque)
        ]

        self.left_pub.publish(
            left_msg
        )

        self.right_pub.publish(
            right_msg
        )


    def send_zero(self):

        for _ in range(10):

            self.publish_torque(
                0.0
            )


    # ==========================================================
    # Raw logging
    # ==========================================================

    def save_row(self):

        self.raw_writer.writerow([

            self.get_clock().now().nanoseconds
            *
            1e-9,

            self.elapsed(),

            self.phase,

            self.direction,

            self.current_torque,

            self.left_position,
            self.right_position,

            self.left_velocity,
            self.right_velocity,

            self.left_effort,
            self.right_effort,

            (
                self.initial_left_position
                if self.initial_left_position
                is not None
                else float('nan')
            ),

            (
                self.initial_right_position
                if self.initial_right_position
                is not None
                else float('nan')
            ),

            int(
                self.left_breakaway
            ),

            int(
                self.right_breakaway
            ),

            int(
                self.safety_triggered
            ),

            self.fault_type,
        ])


    # ==========================================================
    # Initial condition
    # ==========================================================

    def capture_initial_state(self):

        self.initial_left_position = (
            self.left_position
        )

        self.initial_right_position = (
            self.right_position
        )

        self.get_logger().info(
            ''
        )

        self.get_logger().info(
            'INITIAL CONDITION'
        )

        self.get_logger().info(
            f'LEFT  theta0 = '
            f'{self.initial_left_position:+.5f} rad'
        )

        self.get_logger().info(
            f'RIGHT theta0 = '
            f'{self.initial_right_position:+.5f} rad'
        )


    # ==========================================================
    # Breakaway detection
    # ==========================================================

    def update_breakaway(self):

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
        # LEFT
        # ======================================================

        if not self.left_breakaway:

            if (
                left_directional_velocity
                >
                self.breakaway_velocity_threshold
            ):

                if self.left_count == 0:

                    self.left_candidate_start_position = (
                        self.left_position
                    )

                self.left_count += 1

            else:

                self.left_count = 0

                self.left_candidate_start_position = None

            if (
                self.left_count
                >=
                self.breakaway_required_samples
                and
                self.left_candidate_start_position
                is not None
            ):

                delta = (
                    self.direction
                    *
                    (
                        self.left_position
                        -
                        self.left_candidate_start_position
                    )
                )

                if (
                    delta
                    >=
                    self.breakaway_position_change_threshold
                ):

                    self.left_breakaway = True

                    self.left_breakaway_torque = (
                        self.current_torque
                    )

                    self.left_breakaway_feedback_effort = (
                        self.left_effort
                    )

                    self.left_breakaway_velocity = (
                        self.left_velocity
                    )

                    self.left_breakaway_position = (
                        self.left_position
                    )

                    self.left_breakaway_delta_position = (
                        delta
                    )

                    self.get_logger().info(
                        ''
                    )

                    self.get_logger().info(
                        'LEFT BREAKAWAY'
                    )

                    self.get_logger().info(
                        f'Initial position = '
                        f'{self.initial_left_position:+.5f} rad'
                    )

                    self.get_logger().info(
                        f'Breakaway position = '
                        f'{self.left_breakaway_position:+.5f} rad'
                    )

                    self.get_logger().info(
                        f'Command torque = '
                        f'{self.left_breakaway_torque:+.3f} Nm'
                    )

                    self.get_logger().info(
                        f'Feedback effort = '
                        f'{self.left_breakaway_feedback_effort:+.3f} Nm'
                    )

                    self.get_logger().info(
                        f'Velocity = '
                        f'{self.left_breakaway_velocity:+.3f} rad/s'
                    )

                    self.get_logger().info(
                        f'Delta position = '
                        f'{delta:+.5f} rad'
                    )

        # ======================================================
        # RIGHT
        # ======================================================

        if not self.right_breakaway:

            if (
                right_directional_velocity
                >
                self.breakaway_velocity_threshold
            ):

                if self.right_count == 0:

                    self.right_candidate_start_position = (
                        self.right_position
                    )

                self.right_count += 1

            else:

                self.right_count = 0

                self.right_candidate_start_position = None

            if (
                self.right_count
                >=
                self.breakaway_required_samples
                and
                self.right_candidate_start_position
                is not None
            ):

                delta = (
                    self.direction
                    *
                    (
                        self.right_position
                        -
                        self.right_candidate_start_position
                    )
                )

                if (
                    delta
                    >=
                    self.breakaway_position_change_threshold
                ):

                    self.right_breakaway = True

                    self.right_breakaway_torque = (
                        self.current_torque
                    )

                    self.right_breakaway_feedback_effort = (
                        self.right_effort
                    )

                    self.right_breakaway_velocity = (
                        self.right_velocity
                    )

                    self.right_breakaway_position = (
                        self.right_position
                    )

                    self.right_breakaway_delta_position = (
                        delta
                    )

                    self.get_logger().info(
                        ''
                    )

                    self.get_logger().info(
                        'RIGHT BREAKAWAY'
                    )

                    self.get_logger().info(
                        f'Initial position = '
                        f'{self.initial_right_position:+.5f} rad'
                    )

                    self.get_logger().info(
                        f'Breakaway position = '
                        f'{self.right_breakaway_position:+.5f} rad'
                    )

                    self.get_logger().info(
                        f'Command torque = '
                        f'{self.right_breakaway_torque:+.3f} Nm'
                    )

                    self.get_logger().info(
                        f'Feedback effort = '
                        f'{self.right_breakaway_feedback_effort:+.3f} Nm'
                    )

                    self.get_logger().info(
                        f'Velocity = '
                        f'{self.right_breakaway_velocity:+.3f} rad/s'
                    )

                    self.get_logger().info(
                        f'Delta position = '
                        f'{delta:+.5f} rad'
                    )


    # ==========================================================
    # Safety stop
    # ==========================================================

    def trigger_stop(
        self,
        fault_type,
        reason
    ):

        self.safety_triggered = True

        self.fault_type = fault_type

        self.safety_reason = reason

        self.get_logger().error(
            ''
        )

        self.get_logger().error(
            '========================================'
        )

        self.get_logger().error(
            'IMMEDIATE STOP'
        )

        self.get_logger().error(
            reason
        )

        self.get_logger().error(
            '========================================'
        )

        self.save_row()

        self.current_torque = 0.0

        self.send_zero()

        self.set_phase(
            'ZERO_AFTER'
        )


    def check_safety(self):

        if (
            self.joint_state_age()
            >
            self.joint_state_timeout_sec
        ):

            self.trigger_stop(
                'FEEDBACK_TIMEOUT',
                '/joint_states timeout'
            )

            return False

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

        # Wrong direction
        if (
            left_directional_velocity
            <
            -self.wrong_direction_velocity_threshold
            or
            right_directional_velocity
            <
            -self.wrong_direction_velocity_threshold
        ):

            self.trigger_stop(

                'WRONG_DIRECTION',

                f'Wrong-direction motion: '
                f'L={self.left_velocity:+.3f}, '
                f'R={self.right_velocity:+.3f} rad/s'
            )

            return False

        # Overspeed
        if (
            abs(
                self.left_velocity
            )
            >
            self.overspeed_threshold
            or
            abs(
                self.right_velocity
            )
            >
            self.overspeed_threshold
        ):

            self.trigger_stop(

                'OVERSPEED',

                f'Overspeed: '
                f'L={self.left_velocity:+.3f}, '
                f'R={self.right_velocity:+.3f} rad/s'
            )

            return False

        return True


    # ==========================================================
    # Summary
    # ==========================================================

    def write_summary(self):

        summary = {

            'direction':
                self.direction,

            'initial_left_position_rad':
                self.initial_left_position,

            'initial_right_position_rad':
                self.initial_right_position,

            'left_breakaway_detected':
                self.left_breakaway,

            'left_breakaway_command_torque_nm':
                self.left_breakaway_torque,

            'left_breakaway_feedback_effort_nm':
                self.left_breakaway_feedback_effort,

            'left_breakaway_velocity_rad_s':
                self.left_breakaway_velocity,

            'left_breakaway_position_rad':
                self.left_breakaway_position,

            'left_breakaway_delta_position_rad':
                self.left_breakaway_delta_position,

            'right_breakaway_detected':
                self.right_breakaway,

            'right_breakaway_command_torque_nm':
                self.right_breakaway_torque,

            'right_breakaway_feedback_effort_nm':
                self.right_breakaway_feedback_effort,

            'right_breakaway_velocity_rad_s':
                self.right_breakaway_velocity,

            'right_breakaway_position_rad':
                self.right_breakaway_position,

            'right_breakaway_delta_position_rad':
                self.right_breakaway_delta_position,

            'max_torque_nm':
                self.max_torque,

            'ramp_rate_nm_s':
                self.ramp_rate,

            'safety_triggered':
                self.safety_triggered,

            'fault_type':
                self.fault_type,

            'safety_reason':
                self.safety_reason,

            'raw_file':
                self.raw_path,
        }

        with open(
            self.summary_path,
            'w'
        ) as f:

            json.dump(
                summary,
                f,
                indent=4
            )


    # ==========================================================
    # Finish
    # ==========================================================

    def finish(self):

        self.current_torque = 0.0

        self.send_zero()

        self.raw_file.flush()

        self.write_summary()

        self.test_finished = True

        self.get_logger().info(
            ''
        )

        self.get_logger().info(
            '========================================'
        )

        self.get_logger().info(
            'ANGLE BREAKAWAY TEST COMPLETE'
        )

        self.get_logger().info(
            f'Initial L = '
            f'{self.initial_left_position}'
        )

        self.get_logger().info(
            f'Initial R = '
            f'{self.initial_right_position}'
        )

        self.get_logger().info(
            f'LEFT breakaway = '
            f'{self.left_breakaway_torque}'
        )

        self.get_logger().info(
            f'RIGHT breakaway = '
            f'{self.right_breakaway_torque}'
        )

        self.get_logger().info(
            f'Fault = '
            f'{self.fault_type}'
        )

        self.get_logger().info(
            f'Raw = '
            f'{self.raw_path}'
        )

        self.get_logger().info(
            f'Summary = '
            f'{self.summary_path}'
        )

        self.get_logger().info(
            '========================================'
        )


    # ==========================================================
    # Main loop
    # ==========================================================

    def control_loop(self):

        if self.test_finished:

            return

        # ======================================================
        # WAIT
        # ======================================================

        if self.phase == 'WAIT_JOINT':

            self.publish_torque(
                0.0
            )

            if (
                self.left_received
                and
                self.right_received
            ):

                self.set_phase(
                    'ZERO_BEFORE'
                )

                self.get_logger().info(
                    '/joint_states received.'
                )

            return

        # ======================================================
        # ZERO BEFORE
        # ======================================================

        if self.phase == 'ZERO_BEFORE':

            self.current_torque = 0.0

            self.publish_torque(
                0.0
            )

            self.save_row()

            if (
                self.phase_elapsed()
                >=
                self.zero_hold_before_sec
            ):

                self.capture_initial_state()

                self.set_phase(
                    'RAMP_UP'
                )

                self.get_logger().info(
                    ''
                )

                self.get_logger().info(
                    'RAMP_UP started.'
                )

            return

        # ======================================================
        # RAMP UP
        # ======================================================

        if self.phase == 'RAMP_UP':

            if not self.check_safety():

                return

            magnitude = (
                abs(
                    self.current_torque
                )
                +
                self.ramp_rate
                *
                self.dt
            )

            magnitude = min(
                magnitude,
                self.max_torque
            )

            self.current_torque = (
                self.direction
                *
                magnitude
            )

            self.publish_torque(
                self.current_torque
            )

            self.update_breakaway()

            self.save_row()

            # --------------------------------------------------
            # 둘 다 breakaway 검출
            #
            # 바로 torque 0으로 제거
            # --------------------------------------------------

            if (
                self.left_breakaway
                and
                self.right_breakaway
            ):

                self.get_logger().info(
                    ''
                )

                self.get_logger().info(
                    'Both wheels reached breakaway.'
                )

                self.get_logger().info(
                    'Returning immediately to 0 Nm.'
                )

                self.current_torque = 0.0

                self.send_zero()

                self.set_phase(
                    'ZERO_AFTER'
                )

                return

            # --------------------------------------------------
            # 한쪽이라도 breakaway한 뒤
            # overspeed 전에 다음 sample에서 안전하게 종료할 수 있게
            # --------------------------------------------------

            if (
                self.left_breakaway
                or
                self.right_breakaway
            ):

                # 다른 한쪽 검출을 위해 계속 올리되,
                # safety check가 매 loop 수행됨.
                pass

            # --------------------------------------------------
            # Max torque reached
            # --------------------------------------------------

            if (
                magnitude
                >=
                self.max_torque
            ):

                self.get_logger().warn(
                    ''
                )

                self.get_logger().warn(
                    'Maximum torque reached '
                    'before both breakaway events.'
                )

                self.current_torque = 0.0

                self.send_zero()

                self.set_phase(
                    'ZERO_AFTER'
                )

                return

            self.get_logger().info(
                f'RAMP_UP | '
                f'tau={self.current_torque:+6.2f} Nm | '
                f'L pos={self.left_position:+7.3f} '
                f'vel={self.left_velocity:+6.3f} '
                f'eff={self.left_effort:+6.2f} | '
                f'R pos={self.right_position:+7.3f} '
                f'vel={self.right_velocity:+6.3f} '
                f'eff={self.right_effort:+6.2f}',
                throttle_duration_sec=0.5
            )

            return

        # ======================================================
        # ZERO AFTER
        # ======================================================

        if self.phase == 'ZERO_AFTER':

            self.current_torque = 0.0

            self.publish_torque(
                0.0
            )

            self.save_row()

            if (
                self.phase_elapsed()
                >=
                self.zero_hold_after_sec
            ):

                self.finish()

            return


    # ==========================================================
    # Destroy
    # ==========================================================

    def destroy_node(self):

        try:

            if (
                hasattr(
                    self,
                    'raw_file'
                )
                and
                not self.raw_file.closed
            ):

                self.raw_file.flush()

                self.raw_file.close()

        except Exception:

            pass

        super().destroy_node()


def main(args=None):

    rclpy.init(
        args=args
    )

    node = (
        AngleBreakawayTestNode()
    )

    try:

        rclpy.spin(
            node
        )

    except KeyboardInterrupt:

        if rclpy.ok():

            node.get_logger().warn(
                'Interrupted. Sending 0 Nm.'
            )

            node.current_torque = 0.0

            node.send_zero()

    finally:

        node.destroy_node()

        if rclpy.ok():

            rclpy.shutdown()


if __name__ == '__main__':

    main()

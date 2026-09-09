import csv
import json
import math
import os
from collections import deque
from datetime import datetime
from pathlib import Path

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import JointState
from robot_msgs.msg import MitCommand


class DynamicFrictionTestNode(Node):

    def __init__(self):
        super().__init__('dynamic_friction_test_node')

        # ======================================================
        # 1. Experiment parameters
        # ======================================================

        self.declare_parameter(
            'target_speeds',
            [
                0.5,
                1.0,
                2.0,
                3.0,
                -0.5,
                -1.0,
                -2.0,
                -3.0,
            ]
        )

        self.declare_parameter(
            'repeat_count',
            3
        )

        self.declare_parameter(
            'control_frequency',
            100.0
        )

        # ======================================================
        # 2. STARTUP / breakaway parameters
        # ======================================================

        # 0 Nm에서 시작하여 이 속도로 torque를 증가
        self.declare_parameter(
            'startup_torque_ramp_rate',
            0.5
        )

        # breakaway 판정 속도
        self.declare_parameter(
            'breakaway_velocity_threshold',
            0.30
        )

        # 이 시간 이상 threshold를 유지해야 breakaway 인정
        self.declare_parameter(
            'breakaway_required_time',
            0.10
        )

        # 시험 전체의 절대 torque limit
        self.declare_parameter(
            'max_torque',
            15.0
        )

        # STARTUP 최대 허용 시간
        self.declare_parameter(
            'startup_timeout',
            35.0
        )

        # ======================================================
        # 3. Velocity reference ramp
        # ======================================================

        # PI에 목표 속도를 step으로 넣지 않고
        # internal reference를 이 속도로 증가시킨다.
        #
        # unit: rad/s^2
        self.declare_parameter(
            'velocity_reference_ramp_rate',
            0.5
        )

        # ======================================================
        # 4. PI controller
        # ======================================================

        self.declare_parameter(
            'velocity_kp',
            1.0
        )

        self.declare_parameter(
            'velocity_ki',
            2.0
        )

        # ======================================================
        # 5. Steady-state detection
        # ======================================================

        # 최근 N초의 속도를 사용
        self.declare_parameter(
            'steady_window_sec',
            0.50
        )

        # 평균 속도가 목표값에서 벗어날 수 있는 범위
        self.declare_parameter(
            'steady_mean_error_threshold',
            0.15
        )

        # 최근 속도 표준편차 허용치
        self.declare_parameter(
            'steady_velocity_std_threshold',
            0.12
        )

        # 위 조건이 몇 초 연속 유지되어야 하는지
        self.declare_parameter(
            'steady_required_time',
            1.0
        )

        # breakaway 이후 정상상태까지 최대 대기시간
        self.declare_parameter(
            'settling_timeout',
            20.0
        )

        # ======================================================
        # 6. Measurement
        # ======================================================

        self.declare_parameter(
            'measurement_duration',
            3.0
        )

        # 시험 조건 사이에 0 torque 유지 시간
        self.declare_parameter(
            'zero_hold_duration',
            3.0
        )

        # 다음 시험으로 넘어가기 전에
        # 바퀴가 충분히 멈췄다고 판단할 속도
        self.declare_parameter(
            'zero_velocity_threshold',
            0.10
        )

        # ======================================================
        # 7. Output
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

        self.target_speeds = list(
            self.get_parameter(
                'target_speeds'
            ).value
        )

        self.repeat_count = int(
            self.get_parameter(
                'repeat_count'
            ).value
        )

        self.control_frequency = float(
            self.get_parameter(
                'control_frequency'
            ).value
        )

        self.startup_torque_ramp_rate = abs(
            float(
                self.get_parameter(
                    'startup_torque_ramp_rate'
                ).value
            )
        )

        self.breakaway_velocity_threshold = abs(
            float(
                self.get_parameter(
                    'breakaway_velocity_threshold'
                ).value
            )
        )

        self.breakaway_required_time = float(
            self.get_parameter(
                'breakaway_required_time'
            ).value
        )

        self.max_torque = abs(
            float(
                self.get_parameter(
                    'max_torque'
                ).value
            )
        )

        self.startup_timeout = float(
            self.get_parameter(
                'startup_timeout'
            ).value
        )

        self.velocity_reference_ramp_rate = abs(
            float(
                self.get_parameter(
                    'velocity_reference_ramp_rate'
                ).value
            )
        )

        self.velocity_kp = float(
            self.get_parameter(
                'velocity_kp'
            ).value
        )

        self.velocity_ki = float(
            self.get_parameter(
                'velocity_ki'
            ).value
        )

        self.steady_window_sec = float(
            self.get_parameter(
                'steady_window_sec'
            ).value
        )

        self.steady_mean_error_threshold = abs(
            float(
                self.get_parameter(
                    'steady_mean_error_threshold'
                ).value
            )
        )

        self.steady_velocity_std_threshold = abs(
            float(
                self.get_parameter(
                    'steady_velocity_std_threshold'
                ).value
            )
        )

        self.steady_required_time = float(
            self.get_parameter(
                'steady_required_time'
            ).value
        )

        self.settling_timeout = float(
            self.get_parameter(
                'settling_timeout'
            ).value
        )

        self.measurement_duration = float(
            self.get_parameter(
                'measurement_duration'
            ).value
        )

        self.zero_hold_duration = float(
            self.get_parameter(
                'zero_hold_duration'
            ).value
        )

        self.zero_velocity_threshold = abs(
            float(
                self.get_parameter(
                    'zero_velocity_threshold'
                ).value
            )
        )

        self.output_directory = os.path.expanduser(
            str(
                self.get_parameter(
                    'output_directory'
                ).value
            )
        )

        self.dt = (
            1.0 /
            self.control_frequency
        )

        # ======================================================
        # Experiment sequence
        #
        # repeat 1 : normal order
        # repeat 2 : reverse order
        # repeat 3 : normal order
        #
        # 열/순서 효과를 조금 줄이기 위함.
        # ======================================================

        self.test_sequence = []

        for repeat in range(
            1,
            self.repeat_count + 1
        ):

            if repeat % 2 == 1:

                speeds = list(
                    self.target_speeds
                )

            else:

                speeds = list(
                    reversed(
                        self.target_speeds
                    )
                )

            for target_speed in speeds:

                self.test_sequence.append({
                    'repeat': repeat,
                    'target_speed': float(
                        target_speed
                    )
                })

        self.stage_index = 0

        # ======================================================
        # Joint state
        # ======================================================

        self.left_velocity = 0.0
        self.right_velocity = 0.0

        self.left_effort = float('nan')
        self.right_effort = float('nan')

        self.left_received = False
        self.right_received = False

        # ======================================================
        # Velocity history
        # ======================================================

        history_size = max(
            5,
            int(
                self.steady_window_sec
                *
                self.control_frequency
            )
        )

        self.left_velocity_history = deque(
            maxlen=history_size
        )

        self.right_velocity_history = deque(
            maxlen=history_size
        )

        # ======================================================
        # STARTUP
        # ======================================================

        self.startup_torque = 0.0

        self.left_breakaway_count = 0
        self.right_breakaway_count = 0

        self.left_breakaway_detected = False
        self.right_breakaway_detected = False

        self.left_breakaway_torque = float('nan')
        self.right_breakaway_torque = float('nan')

        self.left_breakaway_velocity = float('nan')
        self.right_breakaway_velocity = float('nan')

        required_samples = (
            self.breakaway_required_time
            *
            self.control_frequency
        )

        self.breakaway_required_samples = max(
            1,
            int(
                math.ceil(
                    required_samples
                )
            )
        )

        # ======================================================
        # PI
        # ======================================================

        self.left_integral = 0.0
        self.right_integral = 0.0

        self.left_torque = 0.0
        self.right_torque = 0.0

        # 내부 reference
        self.current_reference_speed = 0.0

        # ======================================================
        # State machine
        # ======================================================

        self.phase = 'WAIT_JOINT'

        self.test_finished = False

        self.test_start_time = (
            self.get_clock().now()
        )

        self.phase_start_time = (
            self.get_clock().now()
        )

        self.steady_start_time = None

        # ======================================================
        # Measurement buffer
        # ======================================================

        self.current_measurement_rows = []

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

        self.run_name = (
            f'dynamic_friction_{timestamp}'
        )

        self.raw_path = os.path.join(
            self.output_directory,
            self.run_name + '_raw.csv'
        )

        self.summary_path = os.path.join(
            self.output_directory,
            self.run_name + '_summary.csv'
        )

        self.metadata_path = os.path.join(
            self.output_directory,
            self.run_name + '_metadata.json'
        )

        # ======================================================
        # Raw CSV
        # ======================================================

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

            'stage_index',
            'repeat',
            'phase',

            'target_speed_rad_s',
            'reference_speed_rad_s',

            'left_velocity_rad_s',
            'right_velocity_rad_s',

            'left_velocity_filtered_rad_s',
            'right_velocity_filtered_rad_s',

            'left_velocity_std_rad_s',
            'right_velocity_std_rad_s',

            'left_error_rad_s',
            'right_error_rad_s',

            'left_torque_cmd_nm',
            'right_torque_cmd_nm',

            'left_joint_effort_nm',
            'right_joint_effort_nm',

            'left_integral',
            'right_integral',

            'left_breakaway_detected',
            'right_breakaway_detected',
        ])

        self.raw_file.flush()

        # ======================================================
        # Summary CSV
        # ======================================================

        self.summary_file = open(
            self.summary_path,
            'w',
            newline=''
        )

        self.summary_writer = csv.writer(
            self.summary_file
        )

        self.summary_writer.writerow([

            'stage_index',
            'repeat',
            'target_speed_rad_s',

            'left_breakaway_torque_nm',
            'right_breakaway_torque_nm',

            'left_breakaway_velocity_rad_s',
            'right_breakaway_velocity_rad_s',

            'left_mean_velocity_rad_s',
            'left_std_velocity_rad_s',

            'right_mean_velocity_rad_s',
            'right_std_velocity_rad_s',

            'left_mean_torque_cmd_nm',
            'left_std_torque_cmd_nm',

            'right_mean_torque_cmd_nm',
            'right_std_torque_cmd_nm',

            'left_mean_effort_nm',
            'left_std_effort_nm',

            'right_mean_effort_nm',
            'right_std_effort_nm',

            'sample_count',
        ])

        self.summary_file.flush()

        # ======================================================
        # Metadata
        # ======================================================

        metadata = {

            'experiment':
                'dynamic drivetrain friction characterization',

            'timestamp':
                timestamp,

            'condition':
                'wheels airborne / no ground contact',

            'method': (
                'Static breakaway is overcome using a slow '
                'torque ramp. After breakaway, control is '
                'transferred to an independent PI velocity '
                'controller using bumpless integral '
                'initialization. The velocity reference is '
                'ramped to the test speed. Dynamic friction '
                'torque is estimated from steady-state '
                'motor torque.'
            ),

            'target_speeds_rad_s':
                self.target_speeds,

            'repeat_count':
                self.repeat_count,

            'control_frequency_hz':
                self.control_frequency,

            'startup_torque_ramp_rate_nm_s':
                self.startup_torque_ramp_rate,

            'breakaway_velocity_threshold_rad_s':
                self.breakaway_velocity_threshold,

            'breakaway_required_time_sec':
                self.breakaway_required_time,

            'max_torque_nm':
                self.max_torque,

            'velocity_reference_ramp_rate_rad_s2':
                self.velocity_reference_ramp_rate,

            'velocity_kp':
                self.velocity_kp,

            'velocity_ki':
                self.velocity_ki,

            'steady_window_sec':
                self.steady_window_sec,

            'steady_mean_error_threshold_rad_s':
                self.steady_mean_error_threshold,

            'steady_velocity_std_threshold_rad_s':
                self.steady_velocity_std_threshold,

            'steady_required_time_sec':
                self.steady_required_time,

            'measurement_duration_sec':
                self.measurement_duration,

            'zero_hold_duration_sec':
                self.zero_hold_duration,

            'raw_file':
                self.raw_path,

            'summary_file':
                self.summary_path,
        }

        with open(
            self.metadata_path,
            'w'
        ) as metadata_file:

            json.dump(
                metadata,
                metadata_file,
                indent=4
            )

        # ======================================================
        # ROS interfaces
        # ======================================================

        self.joint_state_sub = (
            self.create_subscription(
                JointState,
                '/joint_states',
                self.joint_state_callback,
                100
            )
        )

        self.command_pub = (
            self.create_publisher(
                MitCommand,
                '/bldc_mit_speed_cmd',
                20
            )
        )

        self.timer = self.create_timer(
            self.dt,
            self.control_loop
        )

        # ======================================================
        # Startup log
        # ======================================================

        self.get_logger().info(
            '========================================'
        )

        self.get_logger().info(
            'Dynamic friction characterization started'
        )

        self.get_logger().info(
            f'Target speeds = {self.target_speeds}'
        )

        self.get_logger().info(
            f'Repeat count = {self.repeat_count}'
        )

        self.get_logger().info(
            f'Startup torque ramp = '
            f'{self.startup_torque_ramp_rate:.2f} Nm/s'
        )

        self.get_logger().info(
            f'Breakaway threshold = '
            f'{self.breakaway_velocity_threshold:.2f} rad/s'
        )

        self.get_logger().info(
            f'PI: Kp={self.velocity_kp:.3f}, '
            f'Ki={self.velocity_ki:.3f}'
        )

        self.get_logger().info(
            f'Reference ramp = '
            f'{self.velocity_reference_ramp_rate:.2f} rad/s^2'
        )

        self.get_logger().info(
            f'Max torque = {self.max_torque:.2f} Nm'
        )

        self.get_logger().info(
            f'Raw data = {self.raw_path}'
        )

        self.get_logger().info(
            f'Summary = {self.summary_path}'
        )

        self.get_logger().info(
            f'Metadata = {self.metadata_path}'
        )

        self.get_logger().info(
            '========================================'
        )


    # ==========================================================
    # Utility
    # ==========================================================

    def clamp(
        self,
        value,
        minimum,
        maximum
    ):

        return max(
            minimum,
            min(
                value,
                maximum
            )
        )


    def mean(
        self,
        values
    ):

        if len(values) == 0:
            return float('nan')

        return sum(values) / len(values)


    def std(
        self,
        values
    ):

        if len(values) < 2:
            return 0.0

        value_mean = self.mean(
            values
        )

        variance = sum(
            (
                value - value_mean
            ) ** 2
            for value in values
        ) / (
            len(values) - 1
        )

        return math.sqrt(
            variance
        )


    def now_sec(
        self
    ):

        return (
            self.get_clock().now().nanoseconds
            *
            1e-9
        )


    def elapsed_time(
        self
    ):

        return (
            self.get_clock().now()
            -
            self.test_start_time
        ).nanoseconds * 1e-9


    def phase_elapsed(
        self
    ):

        return (
            self.get_clock().now()
            -
            self.phase_start_time
        ).nanoseconds * 1e-9


    def reset_phase_time(
        self
    ):

        self.phase_start_time = (
            self.get_clock().now()
        )


    # ==========================================================
    # Joint state
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

                self.left_velocity = float(
                    msg.velocity[i]
                )

                self.left_received = True

                if i < len(msg.effort):

                    self.left_effort = float(
                        msg.effort[i]
                    )

            elif msg.name[i] == 'right_wheel_joint':

                self.right_velocity = float(
                    msg.velocity[i]
                )

                self.right_received = True

                if i < len(msg.effort):

                    self.right_effort = float(
                        msg.effort[i]
                    )


    # ==========================================================
    # Motor command
    # ==========================================================

    def publish_motor_command(
        self,
        motor_id,
        torque
    ):

        msg = MitCommand()

        msg.motor_id = motor_id

        msg.p_des = 0.0
        msg.v_des = 0.0

        msg.kp = 0.0
        msg.kd = 0.0

        msg.tau_ff = float(
            torque
        )

        self.command_pub.publish(
            msg
        )


    def publish_torques(
        self,
        left_torque,
        right_torque
    ):

        self.publish_motor_command(
            1,
            left_torque
        )

        self.publish_motor_command(
            2,
            right_torque
        )


    def stop_motors(
        self
    ):

        if not rclpy.ok():
            return

        for _ in range(10):

            self.publish_torques(
                0.0,
                0.0
            )


    # ==========================================================
    # Velocity filter
    # ==========================================================

    def update_velocity_history(
        self
    ):

        self.left_velocity_history.append(
            self.left_velocity
        )

        self.right_velocity_history.append(
            self.right_velocity
        )


    def filtered_left_velocity(
        self
    ):

        return self.mean(
            list(
                self.left_velocity_history
            )
        )


    def filtered_right_velocity(
        self
    ):

        return self.mean(
            list(
                self.right_velocity_history
            )
        )


    def left_velocity_std(
        self
    ):

        return self.std(
            list(
                self.left_velocity_history
            )
        )


    def right_velocity_std(
        self
    ):

        return self.std(
            list(
                self.right_velocity_history
            )
        )


    # ==========================================================
    # Reference ramp
    # ==========================================================

    def update_reference_speed(
        self,
        target_speed
    ):

        max_delta = (
            self.velocity_reference_ramp_rate
            *
            self.dt
        )

        error = (
            target_speed
            -
            self.current_reference_speed
        )

        if error > max_delta:

            self.current_reference_speed += (
                max_delta
            )

        elif error < -max_delta:

            self.current_reference_speed -= (
                max_delta
            )

        else:

            self.current_reference_speed = (
                target_speed
            )


    # ==========================================================
    # PI controller
    # ==========================================================

    def update_pi_controller(
        self,
        reference_speed
    ):

        left_error = (
            reference_speed
            -
            self.left_velocity
        )

        right_error = (
            reference_speed
            -
            self.right_velocity
        )

        candidate_left_integral = (
            self.left_integral
            +
            left_error
            *
            self.dt
        )

        candidate_right_integral = (
            self.right_integral
            +
            right_error
            *
            self.dt
        )

        raw_left_torque = (
            self.velocity_kp
            *
            left_error
            +
            self.velocity_ki
            *
            candidate_left_integral
        )

        raw_right_torque = (
            self.velocity_kp
            *
            right_error
            +
            self.velocity_ki
            *
            candidate_right_integral
        )

        left_torque = self.clamp(
            raw_left_torque,
            -self.max_torque,
            self.max_torque
        )

        right_torque = self.clamp(
            raw_right_torque,
            -self.max_torque,
            self.max_torque
        )

        # Anti-windup
        if (
            abs(raw_left_torque)
            < self.max_torque
            or
            raw_left_torque * left_error < 0.0
        ):

            self.left_integral = (
                candidate_left_integral
            )

        if (
            abs(raw_right_torque)
            < self.max_torque
            or
            raw_right_torque * right_error < 0.0
        ):

            self.right_integral = (
                candidate_right_integral
            )

        self.left_torque = left_torque
        self.right_torque = right_torque

        return (
            left_error,
            right_error
        )


    # ==========================================================
    # Bumpless PI initialization
    #
    # tau =
    # Kp * error + Ki * integral
    #
    # 따라서
    #
    # integral =
    # (tau_current - Kp*error)/Ki
    #
    # 로 초기화하면 PI 시작 순간 torque jump를 줄일 수 있음.
    # ==========================================================

    def initialize_pi_bumpless(
        self,
        target_speed
    ):

        current_reference = (
            0.5
            *
            (
                self.filtered_left_velocity()
                +
                self.filtered_right_velocity()
            )
        )

        # 목표 방향과 반대쪽으로 추정되는 경우
        # 최소한 0부터 시작
        if target_speed > 0.0:

            current_reference = max(
                0.0,
                current_reference
            )

        else:

            current_reference = min(
                0.0,
                current_reference
            )

        self.current_reference_speed = (
            current_reference
        )

        left_error = (
            self.current_reference_speed
            -
            self.left_velocity
        )

        right_error = (
            self.current_reference_speed
            -
            self.right_velocity
        )

        if abs(
            self.velocity_ki
        ) > 1e-9:

            self.left_integral = (
                self.left_torque
                -
                self.velocity_kp
                *
                left_error
            ) / self.velocity_ki

            self.right_integral = (
                self.right_torque
                -
                self.velocity_kp
                *
                right_error
            ) / self.velocity_ki

        else:

            self.left_integral = 0.0
            self.right_integral = 0.0


    # ==========================================================
    # Raw logging
    # ==========================================================

    def save_raw_row(
        self,
        target_speed,
        reference_speed,
        left_error,
        right_error
    ):

        if (
            self.stage_index
            <
            len(
                self.test_sequence
            )
        ):

            current = (
                self.test_sequence[
                    self.stage_index
                ]
            )

            repeat = (
                current['repeat']
            )

        else:

            repeat = 0

        left_filtered = (
            self.filtered_left_velocity()
        )

        right_filtered = (
            self.filtered_right_velocity()
        )

        left_std = (
            self.left_velocity_std()
        )

        right_std = (
            self.right_velocity_std()
        )

        row = [

            self.now_sec(),
            self.elapsed_time(),

            self.stage_index,
            repeat,
            self.phase,

            target_speed,
            reference_speed,

            self.left_velocity,
            self.right_velocity,

            left_filtered,
            right_filtered,

            left_std,
            right_std,

            left_error,
            right_error,

            self.left_torque,
            self.right_torque,

            self.left_effort,
            self.right_effort,

            self.left_integral,
            self.right_integral,

            int(
                self.left_breakaway_detected
            ),

            int(
                self.right_breakaway_detected
            ),
        ]

        self.raw_writer.writerow(
            row
        )

        if self.phase == 'MEASURE':

            self.current_measurement_rows.append({

                'left_velocity':
                    self.left_velocity,

                'right_velocity':
                    self.right_velocity,

                'left_torque':
                    self.left_torque,

                'right_torque':
                    self.right_torque,

                'left_effort':
                    self.left_effort,

                'right_effort':
                    self.right_effort,
            })


    # ==========================================================
    # Reset stage
    # ==========================================================

    def reset_stage_states(
        self
    ):

        self.startup_torque = 0.0

        self.left_breakaway_count = 0
        self.right_breakaway_count = 0

        self.left_breakaway_detected = False
        self.right_breakaway_detected = False

        self.left_breakaway_torque = float('nan')
        self.right_breakaway_torque = float('nan')

        self.left_breakaway_velocity = float('nan')
        self.right_breakaway_velocity = float('nan')

        self.left_integral = 0.0
        self.right_integral = 0.0

        self.left_torque = 0.0
        self.right_torque = 0.0

        self.current_reference_speed = 0.0

        self.steady_start_time = None

        self.current_measurement_rows = []

        self.left_velocity_history.clear()
        self.right_velocity_history.clear()


    # ==========================================================
    # State transitions
    # ==========================================================

    def start_zero_hold(
        self
    ):

        self.reset_stage_states()

        self.phase = 'ZERO_HOLD'

        self.reset_phase_time()


    def start_startup(
        self
    ):

        self.phase = 'STARTUP'

        self.reset_phase_time()

        current = (
            self.test_sequence[
                self.stage_index
            ]
        )

        self.get_logger().info(
            ''
        )

        self.get_logger().info(
            '========================================'
        )

        self.get_logger().info(
            f'Stage '
            f'{self.stage_index + 1}/'
            f'{len(self.test_sequence)}'
        )

        self.get_logger().info(
            f'Repeat = '
            f'{current["repeat"]}'
        )

        self.get_logger().info(
            f'Target speed = '
            f'{current["target_speed"]:+.2f} rad/s'
        )

        self.get_logger().info(
            'STARTUP torque ramp begins'
        )

        self.get_logger().info(
            '========================================'
        )


    def start_speed_control(
        self,
        target_speed
    ):

        self.phase = 'SPEED_CONTROL'

        self.initialize_pi_bumpless(
            target_speed
        )

        self.reset_phase_time()

        self.steady_start_time = None

        self.get_logger().info(
            'Both wheels passed breakaway.'
        )

        self.get_logger().info(
            f'LEFT breakaway = '
            f'{self.left_breakaway_torque:+.3f} Nm'
        )

        self.get_logger().info(
            f'RIGHT breakaway = '
            f'{self.right_breakaway_torque:+.3f} Nm'
        )

        self.get_logger().info(
            'Switching to bumpless PI velocity control.'
        )


    def start_measurement(
        self
    ):

        self.phase = 'MEASURE'

        self.reset_phase_time()

        self.current_measurement_rows = []

        self.get_logger().info(
            'Steady state detected.'
        )

        self.get_logger().info(
            f'Measuring for '
            f'{self.measurement_duration:.1f} s.'
        )


    # ==========================================================
    # Finish measurement
    # ==========================================================

    def finish_measurement_stage(
        self
    ):

        rows = (
            self.current_measurement_rows
        )

        current = (
            self.test_sequence[
                self.stage_index
            ]
        )

        left_velocity = [
            row['left_velocity']
            for row in rows
        ]

        right_velocity = [
            row['right_velocity']
            for row in rows
        ]

        left_torque = [
            row['left_torque']
            for row in rows
        ]

        right_torque = [
            row['right_torque']
            for row in rows
        ]

        left_effort = [
            row['left_effort']
            for row in rows
            if math.isfinite(
                row['left_effort']
            )
        ]

        right_effort = [
            row['right_effort']
            for row in rows
            if math.isfinite(
                row['right_effort']
            )
        ]

        self.summary_writer.writerow([

            self.stage_index,
            current['repeat'],
            current['target_speed'],

            self.left_breakaway_torque,
            self.right_breakaway_torque,

            self.left_breakaway_velocity,
            self.right_breakaway_velocity,

            self.mean(
                left_velocity
            ),

            self.std(
                left_velocity
            ),

            self.mean(
                right_velocity
            ),

            self.std(
                right_velocity
            ),

            self.mean(
                left_torque
            ),

            self.std(
                left_torque
            ),

            self.mean(
                right_torque
            ),

            self.std(
                right_torque
            ),

            self.mean(
                left_effort
            ),

            self.std(
                left_effort
            ),

            self.mean(
                right_effort
            ),

            self.std(
                right_effort
            ),

            len(rows),
        ])

        self.summary_file.flush()
        self.raw_file.flush()

        self.get_logger().info(
            ''
        )

        self.get_logger().info(
            '----------------------------------------'
        )

        self.get_logger().info(
            'STEADY-STATE RESULT'
        )

        self.get_logger().info(
            f'Target = '
            f'{current["target_speed"]:+.2f} rad/s'
        )

        self.get_logger().info(
            f'LEFT  : '
            f'omega='
            f'{self.mean(left_velocity):+.3f} '
            f'± {self.std(left_velocity):.3f} rad/s, '
            f'tau='
            f'{self.mean(left_torque):+.3f} '
            f'± {self.std(left_torque):.3f} Nm'
        )

        self.get_logger().info(
            f'RIGHT : '
            f'omega='
            f'{self.mean(right_velocity):+.3f} '
            f'± {self.std(right_velocity):.3f} rad/s, '
            f'tau='
            f'{self.mean(right_torque):+.3f} '
            f'± {self.std(right_torque):.3f} Nm'
        )

        self.get_logger().info(
            '----------------------------------------'
        )


    # ==========================================================
    # Stage advancing
    # ==========================================================

    def advance_stage(
        self
    ):

        self.stage_index += 1

        if (
            self.stage_index
            >=
            len(
                self.test_sequence
            )
        ):

            self.finish_test()

            return

        self.start_zero_hold()


    # ==========================================================
    # Finish test
    # ==========================================================

    def finish_test(
        self
    ):

        self.stop_motors()

        self.test_finished = True

        self.raw_file.flush()
        self.summary_file.flush()

        self.raw_file.close()
        self.summary_file.close()

        self.get_logger().info(
            ''
        )

        self.get_logger().info(
            '========================================'
        )

        self.get_logger().info(
            'DYNAMIC FRICTION TEST COMPLETE'
        )

        self.get_logger().info(
            f'Raw data: '
            f'{self.raw_path}'
        )

        self.get_logger().info(
            f'Summary: '
            f'{self.summary_path}'
        )

        self.get_logger().info(
            f'Metadata: '
            f'{self.metadata_path}'
        )

        self.get_logger().info(
            '========================================'
        )


    # ==========================================================
    # Control loop
    # ==========================================================

    def control_loop(
        self
    ):

        if self.test_finished:
            return

        # ======================================================
        # Wait for feedback
        # ======================================================

        if not (
            self.left_received
            and
            self.right_received
        ):

            self.get_logger().warn(
                'Waiting for /joint_states...',
                throttle_duration_sec=1.0
            )

            return

        self.update_velocity_history()

        # ======================================================
        # Initial state
        # ======================================================

        if self.phase == 'WAIT_JOINT':

            self.start_zero_hold()

            return

        current = (
            self.test_sequence[
                self.stage_index
            ]
        )

        target_speed = float(
            current['target_speed']
        )

        direction = (
            1.0
            if target_speed > 0.0
            else -1.0
        )

        # ======================================================
        # ZERO HOLD
        # ======================================================

        if self.phase == 'ZERO_HOLD':

            self.left_torque = 0.0
            self.right_torque = 0.0

            self.publish_torques(
                0.0,
                0.0
            )

            self.save_raw_row(
                0.0,
                0.0,
                -self.left_velocity,
                -self.right_velocity
            )

            zero_time_complete = (
                self.phase_elapsed()
                >=
                self.zero_hold_duration
            )

            wheels_slow = (
                abs(
                    self.filtered_left_velocity()
                )
                <=
                self.zero_velocity_threshold
                and
                abs(
                    self.filtered_right_velocity()
                )
                <=
                self.zero_velocity_threshold
            )

            if (
                zero_time_complete
                and
                wheels_slow
            ):

                self.start_startup()

            return

        # ======================================================
        # STARTUP
        #
        # 정적 마찰을 PI로 해결하지 않는다.
        # torque를 천천히 증가하여 breakaway만 검출.
        # ======================================================

        if self.phase == 'STARTUP':

            self.startup_torque += (
                self.startup_torque_ramp_rate
                *
                self.dt
            )

            self.startup_torque = min(
                self.startup_torque,
                self.max_torque
            )

            signed_startup_torque = (
                direction
                *
                self.startup_torque
            )

            self.left_torque = (
                signed_startup_torque
            )

            self.right_torque = (
                signed_startup_torque
            )

            self.publish_torques(
                self.left_torque,
                self.right_torque
            )

            left_direction_velocity = (
                direction
                *
                self.left_velocity
            )

            right_direction_velocity = (
                direction
                *
                self.right_velocity
            )

            # --------------------------------------------------
            # LEFT breakaway
            # --------------------------------------------------

            if not self.left_breakaway_detected:

                if (
                    left_direction_velocity
                    >
                    self.breakaway_velocity_threshold
                ):

                    self.left_breakaway_count += 1

                else:

                    self.left_breakaway_count = 0

                if (
                    self.left_breakaway_count
                    >=
                    self.breakaway_required_samples
                ):

                    self.left_breakaway_detected = True

                    self.left_breakaway_torque = (
                        self.left_torque
                    )

                    self.left_breakaway_velocity = (
                        self.left_velocity
                    )

                    self.get_logger().info(
                        f'LEFT breakaway detected: '
                        f'tau='
                        f'{self.left_breakaway_torque:+.3f} Nm, '
                        f'omega='
                        f'{self.left_breakaway_velocity:+.3f} rad/s'
                    )

            # --------------------------------------------------
            # RIGHT breakaway
            # --------------------------------------------------

            if not self.right_breakaway_detected:

                if (
                    right_direction_velocity
                    >
                    self.breakaway_velocity_threshold
                ):

                    self.right_breakaway_count += 1

                else:

                    self.right_breakaway_count = 0

                if (
                    self.right_breakaway_count
                    >=
                    self.breakaway_required_samples
                ):

                    self.right_breakaway_detected = True

                    self.right_breakaway_torque = (
                        self.right_torque
                    )

                    self.right_breakaway_velocity = (
                        self.right_velocity
                    )

                    self.get_logger().info(
                        f'RIGHT breakaway detected: '
                        f'tau='
                        f'{self.right_breakaway_torque:+.3f} Nm, '
                        f'omega='
                        f'{self.right_breakaway_velocity:+.3f} rad/s'
                    )

            self.save_raw_row(
                target_speed,
                0.0,
                target_speed
                -
                self.left_velocity,

                target_speed
                -
                self.right_velocity
            )

            # --------------------------------------------------
            # Both wheels passed breakaway
            # --------------------------------------------------

            if (
                self.left_breakaway_detected
                and
                self.right_breakaway_detected
            ):

                self.start_speed_control(
                    target_speed
                )

                return

            # --------------------------------------------------
            # Startup timeout / torque limit
            # --------------------------------------------------

            if (
                self.phase_elapsed()
                >=
                self.startup_timeout
            ):

                self.get_logger().warn(
                    f'STARTUP timeout at '
                    f'{target_speed:+.2f} rad/s. '
                    f'Skipping condition.'
                )

                self.stop_motors()

                self.advance_stage()

                return

            if (
                self.startup_torque
                >=
                self.max_torque
                and
                not (
                    self.left_breakaway_detected
                    and
                    self.right_breakaway_detected
                )
            ):

                self.get_logger().warn(
                    f'Max torque '
                    f'{self.max_torque:.2f} Nm reached '
                    f'before both wheels passed breakaway.'
                )

                self.stop_motors()

                self.advance_stage()

                return

            self.get_logger().info(
                f'STARTUP | '
                f'tau={signed_startup_torque:+.2f} | '
                f'L={self.left_velocity:+.3f} | '
                f'R={self.right_velocity:+.3f}',
                throttle_duration_sec=0.5
            )

            return

        # ======================================================
        # SPEED CONTROL / MEASURE
        # ======================================================

        self.update_reference_speed(
            target_speed
        )

        (
            left_error,
            right_error
        ) = self.update_pi_controller(
            self.current_reference_speed
        )

        self.publish_torques(
            self.left_torque,
            self.right_torque
        )

        self.save_raw_row(
            target_speed,
            self.current_reference_speed,
            left_error,
            right_error
        )

        # ======================================================
        # SPEED CONTROL
        # ======================================================

        if self.phase == 'SPEED_CONTROL':

            left_filtered = (
                self.filtered_left_velocity()
            )

            right_filtered = (
                self.filtered_right_velocity()
            )

            left_std = (
                self.left_velocity_std()
            )

            right_std = (
                self.right_velocity_std()
            )

            reference_at_target = (
                abs(
                    self.current_reference_speed
                    -
                    target_speed
                )
                <
                1e-6
            )

            left_mean_ok = (
                abs(
                    left_filtered
                    -
                    target_speed
                )
                <=
                self.steady_mean_error_threshold
            )

            right_mean_ok = (
                abs(
                    right_filtered
                    -
                    target_speed
                )
                <=
                self.steady_mean_error_threshold
            )

            left_std_ok = (
                left_std
                <=
                self.steady_velocity_std_threshold
            )

            right_std_ok = (
                right_std
                <=
                self.steady_velocity_std_threshold
            )

            steady_now = (
                reference_at_target
                and
                left_mean_ok
                and
                right_mean_ok
                and
                left_std_ok
                and
                right_std_ok
            )

            if steady_now:

                if self.steady_start_time is None:

                    self.steady_start_time = (
                        self.get_clock().now()
                    )

                steady_duration = (
                    self.get_clock().now()
                    -
                    self.steady_start_time
                ).nanoseconds * 1e-9

                if (
                    steady_duration
                    >=
                    self.steady_required_time
                ):

                    self.start_measurement()

                    return

            else:

                self.steady_start_time = None

            if (
                self.phase_elapsed()
                >=
                self.settling_timeout
            ):

                self.get_logger().warn(
                    f'Settling timeout at '
                    f'{target_speed:+.2f} rad/s.'
                )

                self.stop_motors()

                self.advance_stage()

                return

        # ======================================================
        # MEASURE
        # ======================================================

        elif self.phase == 'MEASURE':

            if (
                self.phase_elapsed()
                >=
                self.measurement_duration
            ):

                self.finish_measurement_stage()

                self.stop_motors()

                self.advance_stage()

                return

        # ======================================================
        # Console status
        # ======================================================

        self.get_logger().info(
            f'{self.phase:13s} | '
            f'target={target_speed:+.2f} '
            f'ref={self.current_reference_speed:+.2f} | '
            f'L={self.left_velocity:+.3f} '
            f'tau={self.left_torque:+.2f} | '
            f'R={self.right_velocity:+.3f} '
            f'tau={self.right_torque:+.2f}',
            throttle_duration_sec=0.5
        )


    # ==========================================================
    # Destroy
    # ==========================================================

    def destroy_node(
        self
    ):

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

            if (
                hasattr(
                    self,
                    'summary_file'
                )
                and
                not self.summary_file.closed
            ):

                self.summary_file.flush()
                self.summary_file.close()

        except Exception:
            pass

        super().destroy_node()


# ==============================================================
# Main
# ==============================================================

def main(
    args=None
):

    rclpy.init(
        args=args
    )

    node = (
        DynamicFrictionTestNode()
    )

    try:

        rclpy.spin(
            node
        )

    except KeyboardInterrupt:

        if rclpy.ok():

            node.get_logger().warn(
                'Experiment interrupted. '
                'Sending 0 Nm.'
            )

            node.stop_motors()

    finally:

        node.destroy_node()

        if rclpy.ok():

            rclpy.shutdown()


if __name__ == '__main__':

    main()

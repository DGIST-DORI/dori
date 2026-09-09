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


class DynamicFrictionVelocityTestNode(Node):

    def __init__(self):

        super().__init__(
            'dynamic_friction_velocity_test_node'
        )

        # ======================================================
        # Experiment conditions
        # ======================================================

        self.declare_parameter(
            'target_speeds',
            [
                3.0,
                5.0,
                7.0,
                9.0,
                -3.0,
                -5.0,
                -7.0,
                -9.0,
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
        # MIT velocity mode
        # ======================================================

        # IMPORTANT:
        #
        # kd=1.5라면 v_des=3 rad/s, v=0에서
        #
        # tau ≈ 1.5 * 3 = 4.5 Nm
        #
        # 정도밖에 나오지 않아,
        # 측정된 breakaway 약 10~12 Nm를 못 넘을 가능성이 큼.
        #
        # 따라서 실험 초기값은 5.0.
        #
        self.declare_parameter(
            'velocity_kd',
            5.0
        )

        self.declare_parameter(
            'position_kp',
            0.0
        )

        # 정상 측정에서는 외부 FF torque를 사용하지 않음
        self.declare_parameter(
            'external_tau_ff',
            0.0
        )

        # ======================================================
        # Reference ramp
        # ======================================================

        # 목표 속도를 바로 step으로 넣지 않고
        # reference를 천천히 증가시킨다.
        #
        # [rad/s^2]
        self.declare_parameter(
            'reference_ramp_rate',
            3.0
        )

        # ======================================================
        # Zero hold
        # ======================================================

        self.declare_parameter(
            'zero_hold_duration',
            3.0
        )

        self.declare_parameter(
            'zero_velocity_threshold',
            0.15
        )

        # ======================================================
        # Steady-state detection
        # ======================================================

        # 최근 몇 초의 velocity를 사용할지
        self.declare_parameter(
            'steady_window_sec',
            0.50
        )

        # 실제 평균 속도가 reference에서
        # 허용되는 최대 오차 [rad/s]
        #
        # MIT velocity mode는 마찰을 만들기 위해
        # 일정한 속도 오차가 필요할 수 있으므로
        # 지나치게 작게 두지 않음.
        self.declare_parameter(
            'steady_velocity_error_threshold',
            1.0
        )

        # 최근 velocity 표준편차
        self.declare_parameter(
            'steady_velocity_std_threshold',
            0.20
        )

        # 최근 effort 표준편차
        self.declare_parameter(
            'steady_effort_std_threshold',
            1.0
        )

        # 조건이 연속으로 유지되어야 하는 시간
        self.declare_parameter(
            'steady_required_time',
            1.5
        )

        self.declare_parameter(
            'settling_timeout',
            15.0
        )

        # ======================================================
        # Measurement
        # ======================================================

        self.declare_parameter(
            'measurement_duration',
            5.0
        )

        # ======================================================
        # Safety / sanity checks
        # ======================================================

        # 실제 속도가 목표보다 지나치게 커졌을 경우
        # 해당 시험 중지
        self.declare_parameter(
            'overspeed_limit',
            12.0
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

        self.velocity_kd = float(
            self.get_parameter(
                'velocity_kd'
            ).value
        )

        self.position_kp = float(
            self.get_parameter(
                'position_kp'
            ).value
        )

        self.external_tau_ff = float(
            self.get_parameter(
                'external_tau_ff'
            ).value
        )

        self.reference_ramp_rate = abs(
            float(
                self.get_parameter(
                    'reference_ramp_rate'
                ).value
            )
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

        self.steady_window_sec = float(
            self.get_parameter(
                'steady_window_sec'
            ).value
        )

        self.steady_velocity_error_threshold = abs(
            float(
                self.get_parameter(
                    'steady_velocity_error_threshold'
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

        self.steady_effort_std_threshold = abs(
            float(
                self.get_parameter(
                    'steady_effort_std_threshold'
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

        self.overspeed_limit = abs(
            float(
                self.get_parameter(
                    'overspeed_limit'
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
            1.0
            /
            self.control_frequency
        )

        # ======================================================
        # Experiment sequence
        #
        # 반복 순서를 교차시켜
        # 온도/시간 순서 효과 감소
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

            for speed in speeds:

                self.test_sequence.append({
                    'repeat': repeat,
                    'target_speed': float(speed)
                })

        self.stage_index = 0

        # ======================================================
        # Joint feedback
        # ======================================================

        self.left_velocity = 0.0
        self.right_velocity = 0.0

        self.left_effort = float('nan')
        self.right_effort = float('nan')

        self.left_received = False
        self.right_received = False

        # ======================================================
        # History buffer
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

        self.left_effort_history = deque(
            maxlen=history_size
        )

        self.right_effort_history = deque(
            maxlen=history_size
        )

        # ======================================================
        # State machine
        # ======================================================

        self.phase = 'WAIT_JOINT'

        self.current_reference_speed = 0.0

        self.test_finished = False

        self.test_start_time = (
            self.get_clock().now()
        )

        self.phase_start_time = (
            self.get_clock().now()
        )

        self.steady_start_time = None

        self.current_measurement_rows = []

        # ======================================================
        # Output setup
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
            f'dynamic_friction_velocity_{timestamp}'
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
        # RAW CSV
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

            'left_velocity_mean_rad_s',
            'right_velocity_mean_rad_s',

            'left_velocity_std_rad_s',
            'right_velocity_std_rad_s',

            'left_velocity_error_rad_s',
            'right_velocity_error_rad_s',

            'left_effort_nm',
            'right_effort_nm',

            'left_effort_mean_nm',
            'right_effort_mean_nm',

            'left_effort_std_nm',
            'right_effort_std_nm',

            'mit_kd',
            'mit_tau_ff',
        ])

        self.raw_file.flush()

        # ======================================================
        # SUMMARY CSV
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

            'left_mean_velocity_rad_s',
            'left_std_velocity_rad_s',

            'right_mean_velocity_rad_s',
            'right_std_velocity_rad_s',

            'left_mean_effort_nm',
            'left_std_effort_nm',

            'right_mean_effort_nm',
            'right_std_effort_nm',

            'left_mean_velocity_error_rad_s',
            'right_mean_velocity_error_rad_s',

            'sample_count',
        ])

        self.summary_file.flush()

        # ======================================================
        # Metadata JSON
        # ======================================================

        metadata = {

            'experiment':
                'dynamic drivetrain friction using MIT velocity mode',

            'condition':
                'wheels airborne, no ground contact',

            'method': (
                'Constant wheel angular velocity was commanded '
                'using MIT velocity mode. '
                'At steady rotation, wheel effort reported in '
                'joint_states was recorded as an estimate of '
                'equivalent drivetrain dynamic friction torque. '
                'Measured wheel velocity, rather than commanded '
                'velocity, should be used as the horizontal axis '
                'for friction characterization.'
            ),

            'timestamp':
                timestamp,

            'target_speeds_rad_s':
                self.target_speeds,

            'repeat_count':
                self.repeat_count,

            'control_frequency_hz':
                self.control_frequency,

            'mit_position_kp':
                self.position_kp,

            'mit_velocity_kd':
                self.velocity_kd,

            'mit_external_tau_ff_nm':
                self.external_tau_ff,

            'reference_ramp_rate_rad_s2':
                self.reference_ramp_rate,

            'steady_window_sec':
                self.steady_window_sec,

            'steady_velocity_error_threshold_rad_s':
                self.steady_velocity_error_threshold,

            'steady_velocity_std_threshold_rad_s':
                self.steady_velocity_std_threshold,

            'steady_effort_std_threshold_nm':
                self.steady_effort_std_threshold,

            'steady_required_time_sec':
                self.steady_required_time,

            'measurement_duration_sec':
                self.measurement_duration,

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
        # ROS
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
            'MIT velocity dynamic friction test'
        )

        self.get_logger().info(
            f'Target speeds = {self.target_speeds}'
        )

        self.get_logger().info(
            f'Repeats = {self.repeat_count}'
        )

        self.get_logger().info(
            f'MIT Kd = {self.velocity_kd:.3f}'
        )

        self.get_logger().info(
            f'MIT tau_ff = {self.external_tau_ff:.3f} Nm'
        )

        self.get_logger().info(
            f'Raw CSV = {self.raw_path}'
        )

        self.get_logger().info(
            f'Summary CSV = {self.summary_path}'
        )

        self.get_logger().info(
            f'Metadata = {self.metadata_path}'
        )

        self.get_logger().info(
            '========================================'
        )


    # ==========================================================
    # Statistics
    # ==========================================================

    def mean(
        self,
        values
    ):

        finite_values = [
            value
            for value in values
            if math.isfinite(value)
        ]

        if not finite_values:

            return float('nan')

        return (
            sum(finite_values)
            /
            len(finite_values)
        )


    def std(
        self,
        values
    ):

        finite_values = [
            value
            for value in values
            if math.isfinite(value)
        ]

        if len(finite_values) < 2:

            return 0.0

        average = self.mean(
            finite_values
        )

        variance = sum(
            (
                value
                -
                average
            ) ** 2
            for value in finite_values
        ) / (
            len(finite_values) - 1
        )

        return math.sqrt(
            variance
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
    # Joint states
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
    # History
    # ==========================================================

    def update_history(
        self
    ):

        self.left_velocity_history.append(
            self.left_velocity
        )

        self.right_velocity_history.append(
            self.right_velocity
        )

        self.left_effort_history.append(
            self.left_effort
        )

        self.right_effort_history.append(
            self.right_effort
        )


    # ==========================================================
    # MIT command
    # ==========================================================

    def publish_motor_command(
        self,
        motor_id,
        velocity
    ):

        msg = MitCommand()

        msg.motor_id = motor_id

        msg.p_des = 0.0
        msg.v_des = float(
            velocity
        )

        msg.kp = self.position_kp
        msg.kd = self.velocity_kd

        msg.tau_ff = self.external_tau_ff

        self.command_pub.publish(
            msg
        )


    def publish_velocity_command(
        self,
        velocity
    ):

        self.publish_motor_command(
            1,
            velocity
        )

        self.publish_motor_command(
            2,
            velocity
        )


    def stop_motors(
        self
    ):

        if not rclpy.ok():

            return

        for _ in range(10):

            msg_left = MitCommand()

            msg_left.motor_id = 1
            msg_left.p_des = 0.0
            msg_left.v_des = 0.0
            msg_left.kp = 0.0
            msg_left.kd = self.velocity_kd
            msg_left.tau_ff = 0.0

            self.command_pub.publish(
                msg_left
            )


            msg_right = MitCommand()

            msg_right.motor_id = 2
            msg_right.p_des = 0.0
            msg_right.v_des = 0.0
            msg_right.kp = 0.0
            msg_right.kd = self.velocity_kd
            msg_right.tau_ff = 0.0

            self.command_pub.publish(
                msg_right
            )


    # ==========================================================
    # Reference ramp
    # ==========================================================

    def update_reference(
        self,
        target
    ):

        max_delta = (
            self.reference_ramp_rate
            *
            self.dt
        )

        error = (
            target
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
                target
            )


    # ==========================================================
    # Raw data
    # ==========================================================

    def save_raw_row(
        self,
        target
    ):

        current = (
            self.test_sequence[
                self.stage_index
            ]
        )

        left_vel_mean = self.mean(
            self.left_velocity_history
        )

        right_vel_mean = self.mean(
            self.right_velocity_history
        )

        left_vel_std = self.std(
            self.left_velocity_history
        )

        right_vel_std = self.std(
            self.right_velocity_history
        )

        left_effort_mean = self.mean(
            self.left_effort_history
        )

        right_effort_mean = self.mean(
            self.right_effort_history
        )

        left_effort_std = self.std(
            self.left_effort_history
        )

        right_effort_std = self.std(
            self.right_effort_history
        )

        row = [

            self.get_clock().now().nanoseconds * 1e-9,
            self.elapsed_time(),

            self.stage_index,
            current['repeat'],
            self.phase,

            target,
            self.current_reference_speed,

            self.left_velocity,
            self.right_velocity,

            left_vel_mean,
            right_vel_mean,

            left_vel_std,
            right_vel_std,

            self.current_reference_speed
            -
            self.left_velocity,

            self.current_reference_speed
            -
            self.right_velocity,

            self.left_effort,
            self.right_effort,

            left_effort_mean,
            right_effort_mean,

            left_effort_std,
            right_effort_std,

            self.velocity_kd,
            self.external_tau_ff,
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

                'left_effort':
                    self.left_effort,

                'right_effort':
                    self.right_effort,
            })


    # ==========================================================
    # Stage setup
    # ==========================================================

    def start_zero_hold(
        self
    ):

        self.phase = 'ZERO_HOLD'

        self.current_reference_speed = 0.0

        self.left_velocity_history.clear()
        self.right_velocity_history.clear()

        self.left_effort_history.clear()
        self.right_effort_history.clear()

        self.current_measurement_rows = []

        self.steady_start_time = None

        self.reset_phase_time()


    def start_speed_control(
        self
    ):

        self.phase = 'SPEED_CONTROL'

        self.current_reference_speed = 0.0

        self.steady_start_time = None

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
            f'Stage {self.stage_index + 1}/'
            f'{len(self.test_sequence)}'
        )

        self.get_logger().info(
            f'Repeat = {current["repeat"]}'
        )

        self.get_logger().info(
            f'Target = '
            f'{current["target_speed"]:+.2f} rad/s'
        )

        self.get_logger().info(
            '========================================'
        )


    def start_measurement(
        self
    ):

        self.phase = 'MEASURE'

        self.current_measurement_rows = []

        self.reset_phase_time()

        self.get_logger().info(
            'Steady state detected.'
        )

        self.get_logger().info(
            f'Recording for '
            f'{self.measurement_duration:.1f} s.'
        )


    # ==========================================================
    # Finish one condition
    # ==========================================================

    def finish_measurement(
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

        left_effort = [
            row['left_effort']
            for row in rows
        ]

        right_effort = [
            row['right_effort']
            for row in rows
        ]

        left_velocity_mean = self.mean(
            left_velocity
        )

        right_velocity_mean = self.mean(
            right_velocity
        )

        left_effort_mean = self.mean(
            left_effort
        )

        right_effort_mean = self.mean(
            right_effort
        )

        self.summary_writer.writerow([

            self.stage_index,
            current['repeat'],
            current['target_speed'],

            left_velocity_mean,
            self.std(
                left_velocity
            ),

            right_velocity_mean,
            self.std(
                right_velocity
            ),

            left_effort_mean,
            self.std(
                left_effort
            ),

            right_effort_mean,
            self.std(
                right_effort
            ),

            current['target_speed']
            -
            left_velocity_mean,

            current['target_speed']
            -
            right_velocity_mean,

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
            f'LEFT  velocity = '
            f'{left_velocity_mean:+.3f} '
            f'± {self.std(left_velocity):.3f} rad/s'
        )

        self.get_logger().info(
            f'LEFT  effort = '
            f'{left_effort_mean:+.3f} '
            f'± {self.std(left_effort):.3f} Nm'
        )

        self.get_logger().info(
            f'RIGHT velocity = '
            f'{right_velocity_mean:+.3f} '
            f'± {self.std(right_velocity):.3f} rad/s'
        )

        self.get_logger().info(
            f'RIGHT effort = '
            f'{right_effort_mean:+.3f} '
            f'± {self.std(right_effort):.3f} Nm'
        )

        self.get_logger().info(
            '----------------------------------------'
        )


    # ==========================================================
    # Next test
    # ==========================================================

    def advance_stage(
        self
    ):

        self.stage_index += 1

        if (
            self.stage_index
            >=
            len(self.test_sequence)
        ):

            self.finish_test()

            return

        self.start_zero_hold()


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
            'MIT VELOCITY FRICTION TEST COMPLETE'
        )

        self.get_logger().info(
            f'Raw: {self.raw_path}'
        )

        self.get_logger().info(
            f'Summary: {self.summary_path}'
        )

        self.get_logger().info(
            f'Metadata: {self.metadata_path}'
        )

        self.get_logger().info(
            '========================================'
        )


    # ==========================================================
    # Main loop
    # ==========================================================

    def control_loop(
        self
    ):

        if self.test_finished:

            return

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

        self.update_history()

        # ------------------------------------------------------
        # Initialize
        # ------------------------------------------------------

        if self.phase == 'WAIT_JOINT':

            self.start_zero_hold()

            return

        current = (
            self.test_sequence[
                self.stage_index
            ]
        )

        target = float(
            current['target_speed']
        )

        # ======================================================
        # ZERO HOLD
        # ======================================================

        if self.phase == 'ZERO_HOLD':

            self.current_reference_speed = 0.0

            self.publish_velocity_command(
                0.0
            )

            self.save_raw_row(
                0.0
            )

            left_slow = (
                abs(
                    self.mean(
                        self.left_velocity_history
                    )
                )
                <=
                self.zero_velocity_threshold
            )

            right_slow = (
                abs(
                    self.mean(
                        self.right_velocity_history
                    )
                )
                <=
                self.zero_velocity_threshold
            )

            if (
                self.phase_elapsed()
                >=
                self.zero_hold_duration
                and
                left_slow
                and
                right_slow
            ):

                self.start_speed_control()

            return

        # ======================================================
        # Velocity control
        # ======================================================

        self.update_reference(
            target
        )

        self.publish_velocity_command(
            self.current_reference_speed
        )

        self.save_raw_row(
            target
        )

        # ======================================================
        # Overspeed protection
        # ======================================================

        if (
            abs(
                self.left_velocity
            )
            >
            self.overspeed_limit
            or
            abs(
                self.right_velocity
            )
            >
            self.overspeed_limit
        ):

            self.get_logger().error(
                'OVERSPEED detected. '
                'Stopping experiment.'
            )

            self.stop_motors()

            self.finish_test()

            return

        # ======================================================
        # SPEED CONTROL
        # ======================================================

        if self.phase == 'SPEED_CONTROL':

            left_vel_mean = self.mean(
                self.left_velocity_history
            )

            right_vel_mean = self.mean(
                self.right_velocity_history
            )

            left_vel_std = self.std(
                self.left_velocity_history
            )

            right_vel_std = self.std(
                self.right_velocity_history
            )

            left_effort_std = self.std(
                self.left_effort_history
            )

            right_effort_std = self.std(
                self.right_effort_history
            )

            reference_complete = (
                abs(
                    self.current_reference_speed
                    -
                    target
                )
                <
                1e-6
            )

            left_error_ok = (
                abs(
                    target
                    -
                    left_vel_mean
                )
                <=
                self.steady_velocity_error_threshold
            )

            right_error_ok = (
                abs(
                    target
                    -
                    right_vel_mean
                )
                <=
                self.steady_velocity_error_threshold
            )

            left_velocity_stable = (
                left_vel_std
                <=
                self.steady_velocity_std_threshold
            )

            right_velocity_stable = (
                right_vel_std
                <=
                self.steady_velocity_std_threshold
            )

            left_effort_stable = (
                left_effort_std
                <=
                self.steady_effort_std_threshold
            )

            right_effort_stable = (
                right_effort_std
                <=
                self.steady_effort_std_threshold
            )

            steady_now = (
                reference_complete
                and
                left_error_ok
                and
                right_error_ok
                and
                left_velocity_stable
                and
                right_velocity_stable
                and
                left_effort_stable
                and
                right_effort_stable
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

            # --------------------------------------------------
            # Timeout
            # --------------------------------------------------

            if (
                self.phase_elapsed()
                >=
                self.settling_timeout
            ):

                self.get_logger().warn(
                    f'Settling timeout at '
                    f'{target:+.2f} rad/s.'
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

                self.finish_measurement()

                self.stop_motors()

                self.advance_stage()

                return

        # ======================================================
        # Console
        # ======================================================

        self.get_logger().info(
            f'{self.phase:13s} | '
            f'target={target:+.2f} '
            f'ref={self.current_reference_speed:+.2f} | '
            f'L={self.left_velocity:+.3f} '
            f'eff={self.left_effort:+.2f} | '
            f'R={self.right_velocity:+.3f} '
            f'eff={self.right_effort:+.2f}',
            throttle_duration_sec=0.5
        )


    # ==========================================================
    # Destruction
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


def main(
    args=None
):

    rclpy.init(
        args=args
    )

    node = (
        DynamicFrictionVelocityTestNode()
    )

    try:

        rclpy.spin(
            node
        )

    except KeyboardInterrupt:

        if rclpy.ok():

            node.get_logger().warn(
                'Experiment interrupted. '
                'Sending zero velocity command.'
            )

            node.stop_motors()

    finally:

        node.destroy_node()

        if rclpy.ok():

            rclpy.shutdown()


if __name__ == '__main__':

    main()

import csv
import json
import math
import os

from datetime import datetime
from pathlib import Path

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import JointState
from robot_msgs.msg import MitCommand


class DynamicFrictionTorqueSweepNode(Node):

    def __init__(self):

        super().__init__(
            'dynamic_friction_torque_sweep_node'
        )

        # ======================================================
        # 1. Experiment parameters
        # ======================================================

        # +1 : forward
        # -1 : reverse
        self.declare_parameter(
            'direction',
            1
        )

        self.declare_parameter(
            'start_torque',
            0.0
        )

        self.declare_parameter(
            'max_torque',
            13.0
        )

        # [Nm/s]
        self.declare_parameter(
            'ramp_up_rate',
            0.2
        )

        self.declare_parameter(
            'ramp_down_rate',
            0.2
        )

        # Normal overspeed 발생 시 빠른 감쇠
        self.declare_parameter(
            'emergency_ramp_down_rate',
            3.0
        )

        # ======================================================
        # 2. Timing
        # ======================================================

        self.declare_parameter(
            'control_frequency',
            100.0
        )

        self.declare_parameter(
            'zero_hold_before_sec',
            3.0
        )

        self.declare_parameter(
            'peak_hold_sec',
            0.2
        )

        self.declare_parameter(
            'zero_hold_after_sec',
            3.0
        )

        # ======================================================
        # 3. Safety
        # ======================================================

        # 정상 방향 absolute overspeed
        self.declare_parameter(
            'overspeed_threshold',
            4.0
        )

        # command 방향 반대로 이 속도 이상이면 즉시 stop
        self.declare_parameter(
            'wrong_direction_velocity_threshold',
            2.0
        )

        self.declare_parameter(
            'joint_state_timeout_sec',
            0.20
        )

        # ======================================================
        # 4. Breakaway detection
        # ======================================================

        self.declare_parameter(
            'breakaway_velocity_threshold',
            0.30
        )

        # 100 Hz 기준 30 samples = 0.3 s
        self.declare_parameter(
            'breakaway_required_samples',
            30
        )

        # breakaway 후보 구간에서 최소 이동량
        self.declare_parameter(
            'breakaway_position_change_threshold',
            0.05
        )

        # ======================================================
        # 5. Output
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
            1
            if self.direction >= 0
            else -1
        )

        self.start_torque = abs(
            float(
                self.get_parameter(
                    'start_torque'
                ).value
            )
        )

        self.max_torque = abs(
            float(
                self.get_parameter(
                    'max_torque'
                ).value
            )
        )

        self.ramp_up_rate = abs(
            float(
                self.get_parameter(
                    'ramp_up_rate'
                ).value
            )
        )

        self.ramp_down_rate = abs(
            float(
                self.get_parameter(
                    'ramp_down_rate'
                ).value
            )
        )

        self.emergency_ramp_down_rate = abs(
            float(
                self.get_parameter(
                    'emergency_ramp_down_rate'
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

        self.peak_hold_sec = float(
            self.get_parameter(
                'peak_hold_sec'
            ).value
        )

        self.zero_hold_after_sec = float(
            self.get_parameter(
                'zero_hold_after_sec'
            ).value
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
        # State
        # ======================================================

        self.phase = 'WAIT_JOINT'

        self.current_torque_magnitude = (
            self.start_torque
        )

        self.test_finished = False

        self.safety_triggered = False

        self.safety_reason = ''

        self.fault_type = 'NONE'

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
        # Joint states
        # ======================================================

        self.left_position = float('nan')
        self.right_position = float('nan')

        self.left_velocity = 0.0
        self.right_velocity = 0.0

        self.left_effort = float('nan')
        self.right_effort = float('nan')

        self.left_received = False
        self.right_received = False

        self.feedback_update_count = 0

        # ======================================================
        # Breakaway detection
        # ======================================================

        self.left_breakaway_count = 0
        self.right_breakaway_count = 0

        self.left_breakaway_start_position = None
        self.right_breakaway_start_position = None

        self.left_breakaway_detected = False
        self.right_breakaway_detected = False

        self.left_breakaway_torque = float('nan')
        self.right_breakaway_torque = float('nan')

        self.left_breakaway_velocity = float('nan')
        self.right_breakaway_velocity = float('nan')

        self.left_breakaway_position_change = float('nan')
        self.right_breakaway_position_change = float('nan')

        # ======================================================
        # Maximum velocity
        # ======================================================

        self.max_abs_left_velocity = 0.0
        self.max_abs_right_velocity = 0.0

        # ======================================================
        # Output
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
            f'torque_sweep_'
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
            'phase_elapsed_sec',

            'phase',
            'direction',

            'tau_ff_cmd_nm',

            'left_position_rad',
            'right_position_rad',

            'left_velocity_rad_s',
            'right_velocity_rad_s',

            'left_directional_velocity_rad_s',
            'right_directional_velocity_rad_s',

            'left_effort_nm',
            'right_effort_nm',

            'feedback_update_count',
            'joint_state_age_sec',

            'left_breakaway_detected',
            'right_breakaway_detected',

            'safety_triggered',
            'fault_type',
        ])

        self.raw_file.flush()

        # ======================================================
        # Metadata
        # ======================================================

        metadata = {

            'experiment':
                'open-loop tau_ff torque sweep',

            'condition':
                'wheels airborne, no ground contact',

            'direction':
                direction_name,

            'direction_sign':
                self.direction,

            'control_mode': {
                'p_des': 0.0,
                'v_des': 0.0,
                'kp': 0.0,
                'kd': 0.0,
                'input': 'tau_ff only',
            },

            'max_torque_nm':
                self.max_torque,

            'ramp_up_rate_nm_s':
                self.ramp_up_rate,

            'ramp_down_rate_nm_s':
                self.ramp_down_rate,

            'breakaway_velocity_threshold_rad_s':
                self.breakaway_velocity_threshold,

            'breakaway_required_samples':
                self.breakaway_required_samples,

            'breakaway_position_change_threshold_rad':
                self.breakaway_position_change_threshold,

            'overspeed_threshold_rad_s':
                self.overspeed_threshold,

            'wrong_direction_velocity_threshold_rad_s':
                self.wrong_direction_velocity_threshold,

            'control_frequency_hz':
                self.control_frequency,

            'raw_file':
                self.raw_path,
        }

        with open(
            self.metadata_path,
            'w'
        ) as f:

            json.dump(
                metadata,
                f,
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
        # Start log
        # ======================================================

        self.get_logger().info(
            '========================================'
        )

        self.get_logger().info(
            'SAFE OPEN-LOOP TAU_FF SWEEP'
        )

        self.get_logger().info(
            f'Direction = {direction_name.upper()}'
        )

        self.get_logger().info(
            f'Max torque = '
            f'{self.max_torque:.2f} Nm'
        )

        self.get_logger().info(
            f'Ramp up/down = '
            f'{self.ramp_up_rate:.3f} / '
            f'{self.ramp_down_rate:.3f} Nm/s'
        )

        self.get_logger().info(
            f'Breakaway condition = '
            f'>{self.breakaway_velocity_threshold:.2f} rad/s '
            f'for {self.breakaway_required_samples} samples '
            f'AND Δθ>'
            f'{self.breakaway_position_change_threshold:.3f} rad'
        )

        self.get_logger().info(
            f'Wrong-direction immediate stop = '
            f'{self.wrong_direction_velocity_threshold:.2f} rad/s'
        )

        self.get_logger().info(
            f'Raw = {self.raw_path}'
        )

        self.get_logger().info(
            '========================================'
        )


    # ==========================================================
    # Utility
    # ==========================================================

    def elapsed_time(self):

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


    def signed_torque(self):

        return (
            self.direction
            *
            self.current_torque_magnitude
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
    # Joint callback
    # ==========================================================

    def joint_state_callback(
        self,
        msg
    ):

        self.last_joint_state_time = (
            self.get_clock().now()
        )

        self.feedback_update_count += 1

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

        self.max_abs_left_velocity = max(
            self.max_abs_left_velocity,
            abs(
                self.left_velocity
            )
        )

        self.max_abs_right_velocity = max(
            self.max_abs_right_velocity,
            abs(
                self.right_velocity
            )
        )


    # ==========================================================
    # MIT torque command
    # ==========================================================

    def publish_motor_torque(
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


    def publish_torque(
        self,
        torque
    ):

        self.publish_motor_torque(
            1,
            torque
        )

        self.publish_motor_torque(
            2,
            torque
        )


    def send_zero_torque(self):

        if not rclpy.ok():

            return

        for _ in range(10):

            self.publish_torque(
                0.0
            )


    # ==========================================================
    # Raw logging
    # ==========================================================

    def save_raw_row(self):

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

        self.raw_writer.writerow([

            self.get_clock().now().nanoseconds
            *
            1e-9,

            self.elapsed_time(),

            self.phase_elapsed(),

            self.phase,

            self.direction,

            self.signed_torque(),

            self.left_position,
            self.right_position,

            self.left_velocity,
            self.right_velocity,

            left_directional_velocity,
            right_directional_velocity,

            self.left_effort,
            self.right_effort,

            self.feedback_update_count,

            self.joint_state_age(),

            int(
                self.left_breakaway_detected
            ),

            int(
                self.right_breakaway_detected
            ),

            int(
                self.safety_triggered
            ),

            self.fault_type,
        ])


    # ==========================================================
    # Breakaway detector
    # ==========================================================

    def update_breakaway_detection(self):

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

        if not self.left_breakaway_detected:

            if (
                left_directional_velocity
                >
                self.breakaway_velocity_threshold
            ):

                if (
                    self.left_breakaway_count
                    ==
                    0
                ):

                    self.left_breakaway_start_position = (
                        self.left_position
                    )

                self.left_breakaway_count += 1

            else:

                self.left_breakaway_count = 0

                self.left_breakaway_start_position = None

            if (
                self.left_breakaway_count
                >=
                self.breakaway_required_samples
                and
                self.left_breakaway_start_position
                is not None
            ):

                directional_position_change = (
                    self.direction
                    *
                    (
                        self.left_position
                        -
                        self.left_breakaway_start_position
                    )
                )

                if (
                    directional_position_change
                    >=
                    self.breakaway_position_change_threshold
                ):

                    self.left_breakaway_detected = True

                    self.left_breakaway_torque = (
                        self.signed_torque()
                    )

                    self.left_breakaway_velocity = (
                        self.left_velocity
                    )

                    self.left_breakaway_position_change = (
                        directional_position_change
                    )

                    self.get_logger().info(
                        ''
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
                        f'Directional Δposition = '
                        f'{directional_position_change:+.4f} rad'
                    )

                else:

                    self.left_breakaway_count = 0

                    self.left_breakaway_start_position = None

        # ======================================================
        # RIGHT
        # ======================================================

        if not self.right_breakaway_detected:

            if (
                right_directional_velocity
                >
                self.breakaway_velocity_threshold
            ):

                if (
                    self.right_breakaway_count
                    ==
                    0
                ):

                    self.right_breakaway_start_position = (
                        self.right_position
                    )

                self.right_breakaway_count += 1

            else:

                self.right_breakaway_count = 0

                self.right_breakaway_start_position = None

            if (
                self.right_breakaway_count
                >=
                self.breakaway_required_samples
                and
                self.right_breakaway_start_position
                is not None
            ):

                directional_position_change = (
                    self.direction
                    *
                    (
                        self.right_position
                        -
                        self.right_breakaway_start_position
                    )
                )

                if (
                    directional_position_change
                    >=
                    self.breakaway_position_change_threshold
                ):

                    self.right_breakaway_detected = True

                    self.right_breakaway_torque = (
                        self.signed_torque()
                    )

                    self.right_breakaway_velocity = (
                        self.right_velocity
                    )

                    self.right_breakaway_position_change = (
                        directional_position_change
                    )

                    self.get_logger().info(
                        ''
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
                        f'Directional Δposition = '
                        f'{directional_position_change:+.4f} rad'
                    )

                else:

                    self.right_breakaway_count = 0

                    self.right_breakaway_start_position = None


    # ==========================================================
    # Immediate fault stop
    # ==========================================================

    def immediate_fault_stop(
        self,
        reason
    ):

        self.safety_triggered = True

        self.safety_reason = reason

        self.fault_type = (
            'WRONG_DIRECTION'
        )

        self.get_logger().error(
            ''
        )

        self.get_logger().error(
            '========================================'
        )

        self.get_logger().error(
            'IMMEDIATE SAFETY STOP'
        )

        self.get_logger().error(
            reason
        )

        self.get_logger().error(
            'Commanding 0 Nm immediately.'
        )

        self.get_logger().error(
            '========================================'
        )

        # fault 직전 row 먼저 기록
        self.save_raw_row()

        self.current_torque_magnitude = 0.0

        self.send_zero_torque()

        self.set_phase(
            'ZERO_HOLD_AFTER'
        )


    # ==========================================================
    # Normal overspeed ramp-down
    # ==========================================================

    def trigger_emergency_ramp_down(
        self,
        reason
    ):

        if (
            self.phase
            ==
            'EMERGENCY_RAMP_DOWN'
        ):

            return

        self.safety_triggered = True

        self.safety_reason = reason

        self.fault_type = (
            'OVERSPEED'
        )

        self.get_logger().warn(
            ''
        )

        self.get_logger().warn(
            '========================================'
        )

        self.get_logger().warn(
            'OVERSPEED'
        )

        self.get_logger().warn(
            reason
        )

        self.get_logger().warn(
            'Fast torque ramp-down started.'
        )

        self.get_logger().warn(
            '========================================'
        )

        self.set_phase(
            'EMERGENCY_RAMP_DOWN'
        )


    # ==========================================================
    # Safety checks
    # ==========================================================

    def check_safety(self):

        # ------------------------------------------------------
        # Feedback timeout
        # ------------------------------------------------------

        age = (
            self.joint_state_age()
        )

        if (
            age
            >
            self.joint_state_timeout_sec
        ):

            self.safety_triggered = True

            self.safety_reason = (
                f'/joint_states timeout '
                f'{age:.3f} s'
            )

            self.fault_type = (
                'FEEDBACK_TIMEOUT'
            )

            self.current_torque_magnitude = 0.0

            self.send_zero_torque()

            self.set_phase(
                'ZERO_HOLD_AFTER'
            )

            return False

        # ------------------------------------------------------
        # Direction-aware velocity
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

        # ------------------------------------------------------
        # Wrong-direction motion
        # ------------------------------------------------------

        if (
            left_directional_velocity
            <=
            -self.wrong_direction_velocity_threshold
            or
            right_directional_velocity
            <=
            -self.wrong_direction_velocity_threshold
        ):

            self.immediate_fault_stop(

                'Wrong-direction motion: '
                f'L={self.left_velocity:+.3f}, '
                f'R={self.right_velocity:+.3f} rad/s'
            )

            return False

        # ------------------------------------------------------
        # Normal absolute overspeed
        # ------------------------------------------------------

        if (
            abs(
                self.left_velocity
            )
            >=
            self.overspeed_threshold
            or
            abs(
                self.right_velocity
            )
            >=
            self.overspeed_threshold
        ):

            self.trigger_emergency_ramp_down(

                'Overspeed: '
                f'L={self.left_velocity:+.3f}, '
                f'R={self.right_velocity:+.3f} rad/s'
            )

            return False

        return True


    # ==========================================================
    # Summary
    # ==========================================================

    def write_summary(self):

        direction_name = (
            'forward'
            if self.direction > 0
            else 'reverse'
        )

        summary = {

            'direction':
                direction_name,

            'safety_triggered':
                self.safety_triggered,

            'fault_type':
                self.fault_type,

            'safety_reason':
                self.safety_reason,

            'left_breakaway_detected':
                self.left_breakaway_detected,

            'left_breakaway_torque_nm':
                (
                    self.left_breakaway_torque
                    if math.isfinite(
                        self.left_breakaway_torque
                    )
                    else None
                ),

            'left_breakaway_velocity_rad_s':
                (
                    self.left_breakaway_velocity
                    if math.isfinite(
                        self.left_breakaway_velocity
                    )
                    else None
                ),

            'left_breakaway_position_change_rad':
                (
                    self.left_breakaway_position_change
                    if math.isfinite(
                        self.left_breakaway_position_change
                    )
                    else None
                ),

            'right_breakaway_detected':
                self.right_breakaway_detected,

            'right_breakaway_torque_nm':
                (
                    self.right_breakaway_torque
                    if math.isfinite(
                        self.right_breakaway_torque
                    )
                    else None
                ),

            'right_breakaway_velocity_rad_s':
                (
                    self.right_breakaway_velocity
                    if math.isfinite(
                        self.right_breakaway_velocity
                    )
                    else None
                ),

            'right_breakaway_position_change_rad':
                (
                    self.right_breakaway_position_change
                    if math.isfinite(
                        self.right_breakaway_position_change
                    )
                    else None
                ),

            'max_abs_left_velocity_rad_s':
                self.max_abs_left_velocity,

            'max_abs_right_velocity_rad_s':
                self.max_abs_right_velocity,

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

    def finish_test(self):

        self.current_torque_magnitude = 0.0

        self.send_zero_torque()

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
            'SAFE TORQUE SWEEP COMPLETE'
        )

        self.get_logger().info(
            f'Fault type = '
            f'{self.fault_type}'
        )

        if self.left_breakaway_detected:

            self.get_logger().info(
                f'LEFT breakaway = '
                f'{self.left_breakaway_torque:+.3f} Nm'
            )

        else:

            self.get_logger().warn(
                'LEFT breakaway not detected'
            )

        if self.right_breakaway_detected:

            self.get_logger().info(
                f'RIGHT breakaway = '
                f'{self.right_breakaway_torque:+.3f} Nm'
            )

        else:

            self.get_logger().warn(
                'RIGHT breakaway not detected'
            )

        self.get_logger().info(
            f'Max |L velocity| = '
            f'{self.max_abs_left_velocity:.3f} rad/s'
        )

        self.get_logger().info(
            f'Max |R velocity| = '
            f'{self.max_abs_right_velocity:.3f} rad/s'
        )

        self.get_logger().info(
            f'Raw = {self.raw_path}'
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

                self.current_torque_magnitude = 0.0

                self.get_logger().info(
                    '/joint_states received.'
                )

                self.set_phase(
                    'ZERO_HOLD_BEFORE'
                )

            return

        # ======================================================
        # Safety
        # ======================================================

        if (
            self.phase
            not in [
                'ZERO_HOLD_BEFORE',
                'ZERO_HOLD_AFTER',
                'EMERGENCY_RAMP_DOWN'
            ]
        ):

            if not self.check_safety():

                return

        # ======================================================
        # ZERO BEFORE
        # ======================================================

        if self.phase == 'ZERO_HOLD_BEFORE':

            self.current_torque_magnitude = 0.0

            self.publish_torque(
                0.0
            )

            self.save_raw_row()

            if (
                self.phase_elapsed()
                >=
                self.zero_hold_before_sec
            ):

                self.get_logger().info(
                    'RAMP_UP started.'
                )

                self.set_phase(
                    'RAMP_UP'
                )

            return

        # ======================================================
        # RAMP UP
        # ======================================================

        if self.phase == 'RAMP_UP':

            self.current_torque_magnitude += (
                self.ramp_up_rate
                *
                self.dt
            )

            self.current_torque_magnitude = min(
                self.current_torque_magnitude,
                self.max_torque
            )

            self.publish_torque(
                self.signed_torque()
            )

            self.update_breakaway_detection()

            self.save_raw_row()

            if (
                self.current_torque_magnitude
                >=
                self.max_torque
            ):

                self.get_logger().info(
                    'Maximum torque reached.'
                )

                self.set_phase(
                    'PEAK_HOLD'
                )

                return

            self.get_logger().info(
                f'RAMP_UP   | '
                f'tau={self.signed_torque():+6.2f} | '
                f'L={self.left_velocity:+6.3f} | '
                f'R={self.right_velocity:+6.3f}',
                throttle_duration_sec=0.5
            )

            return

        # ======================================================
        # PEAK HOLD
        # ======================================================

        if self.phase == 'PEAK_HOLD':

            self.publish_torque(
                self.signed_torque()
            )

            self.save_raw_row()

            if (
                self.phase_elapsed()
                >=
                self.peak_hold_sec
            ):

                self.get_logger().info(
                    'RAMP_DOWN started.'
                )

                self.set_phase(
                    'RAMP_DOWN'
                )

            return

        # ======================================================
        # RAMP DOWN
        # ======================================================

        if self.phase == 'RAMP_DOWN':

            self.current_torque_magnitude -= (
                self.ramp_down_rate
                *
                self.dt
            )

            self.current_torque_magnitude = max(
                0.0,
                self.current_torque_magnitude
            )

            self.publish_torque(
                self.signed_torque()
            )

            self.save_raw_row()

            if (
                self.current_torque_magnitude
                <=
                0.0
            ):

                self.set_phase(
                    'ZERO_HOLD_AFTER'
                )

                return

            self.get_logger().info(
                f'RAMP_DOWN | '
                f'tau={self.signed_torque():+6.2f} | '
                f'L={self.left_velocity:+6.3f} | '
                f'R={self.right_velocity:+6.3f}',
                throttle_duration_sec=0.5
            )

            return

        # ======================================================
        # EMERGENCY RAMP DOWN
        # ======================================================

        if self.phase == 'EMERGENCY_RAMP_DOWN':

            self.current_torque_magnitude -= (
                self.emergency_ramp_down_rate
                *
                self.dt
            )

            self.current_torque_magnitude = max(
                0.0,
                self.current_torque_magnitude
            )

            self.publish_torque(
                self.signed_torque()
            )

            self.save_raw_row()

            if (
                self.current_torque_magnitude
                <=
                0.0
            ):

                self.set_phase(
                    'ZERO_HOLD_AFTER'
                )

            return

        # ======================================================
        # ZERO AFTER
        # ======================================================

        if self.phase == 'ZERO_HOLD_AFTER':

            self.current_torque_magnitude = 0.0

            self.publish_torque(
                0.0
            )

            self.save_raw_row()

            if (
                self.phase_elapsed()
                >=
                self.zero_hold_after_sec
            ):

                self.finish_test()

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
        DynamicFrictionTorqueSweepNode()
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

            node.current_torque_magnitude = 0.0

            node.send_zero_torque()

    finally:

        node.destroy_node()

        if rclpy.ok():

            rclpy.shutdown()


if __name__ == '__main__':

    main()

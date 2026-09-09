#!/usr/bin/env python3

import csv
import math
import os
import statistics
from datetime import datetime
from pathlib import Path

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64MultiArray
from controller_manager_msgs.srv import SwitchController


class AutomaticAngleBreakawayMapNode(Node):
    """
    Angle-dependent STATIC breakaway torque experiment.

    Per target angle:
      1) LEFT static breakaway x repeat_count
      2) RIGHT static breakaway x repeat_count
      3) next angle

    Kinetic measurement is intentionally disabled in this version.

    Positioning:
      - tolerance: +/- position_tolerance_deg (default 3 deg)
      - every attempt first moves to a backoff phase, then approaches target
      - max 4 attempts; after that proceed from actual phase
      - after static effort-mode zero relaxation, phase is checked again

    Static breakaway:
      - candidate when directional speed >= 0.30 rad/s
      - freeze torque while candidate is verified
      - normal: >=0.30 rad/s for 0.30 s AND dtheta >=0.05 rad
      - fast:   >=1.00 rad/s for 0.20 s
      - rapid:  >=3.00 rad/s after candidate -> immediate confirmation
      - hard safety: abs(speed) > 4.0 rad/s -> immediate stop

    """

    def __init__(self):
        super().__init__('automatic_angle_breakaway_map_node')

        # ======================================================
        # Parameters: experiment
        # ======================================================
        self.declare_parameter('direction', 1)
        self.declare_parameter('start_angle_deg', 0.0)
        self.declare_parameter('angle_step_deg', 15.0)
        self.declare_parameter('angle_count', 24)
        self.declare_parameter('repeat_count', 3)
        self.declare_parameter('control_frequency', 100.0)
        self.declare_parameter('max_torque', 13.0)

        # Static torque ramp
        self.declare_parameter('fast_ramp_end_torque', 5.0)
        self.declare_parameter('fast_ramp_rate', 2.0)
        self.declare_parameter('slow_ramp_rate', 0.2)

        # Positioning
        self.declare_parameter('position_tolerance_deg', 3.0)
        self.declare_parameter('position_backoff_deg', 10.0)
        self.declare_parameter('position_backoff_timeout_sec', 6.0)
        self.declare_parameter('position_attempt_timeout_sec', 12.0)
        self.declare_parameter('position_settle_sec', 0.5)
        self.declare_parameter('max_position_attempts', 3)
        self.declare_parameter('zero_relax_sec', 2.0)
        self.declare_parameter('post_test_zero_sec', 2.0)

        # Static breakaway detector
        self.declare_parameter('breakaway_velocity_threshold', 0.30)
        self.declare_parameter('normal_breakaway_hold_sec', 0.30)
        self.declare_parameter('breakaway_position_change_threshold', 0.05)
        self.declare_parameter('fast_breakaway_velocity_threshold', 1.0)
        self.declare_parameter('fast_breakaway_hold_sec', 0.20)
        self.declare_parameter('rapid_breakaway_velocity_threshold', 3.0)

        # Kinetic
        self.declare_parameter('kinetic_test_velocity', 0.50)
        self.declare_parameter('kinetic_launch_release_velocity', 0.30)
        self.declare_parameter('kinetic_launch_timeout_sec', 3.0)
        self.declare_parameter('kinetic_launch_fallback_torque', 3.0)
        self.declare_parameter('kinetic_launch_torque_scale', 1.0)
        self.declare_parameter('kinetic_launch_torque_limit', 13.0)
        # Outer PI tau_ff used after launch for bumpless handover.
        # The motor's internal speed loop is still active; this PI only supplies the missing torque.
        self.declare_parameter('kinetic_pi_kp', 2.0)
        self.declare_parameter('kinetic_pi_ki', 3.0)
        self.declare_parameter('kinetic_pi_torque_limit', 13.0)
        self.declare_parameter('kinetic_pi_slew_rate', 3.0)
        self.declare_parameter('kinetic_pi_integral_limit', 6.0)
        self.declare_parameter('kinetic_velocity_tolerance', 0.10)
        self.declare_parameter('kinetic_settle_sec', 1.0)
        self.declare_parameter('kinetic_settle_timeout_sec', 8.0)
        self.declare_parameter('kinetic_sample_sec', 2.0)
        self.declare_parameter('kinetic_min_valid_fraction', 0.80)

        # Safety
        self.declare_parameter('overspeed_threshold', 4.0)
        self.declare_parameter('wrong_direction_velocity_threshold', 2.0)
        self.declare_parameter('passive_wheel_velocity_limit', 4.0)
        self.declare_parameter('joint_state_timeout_sec', 0.20)

        # Output
        self.declare_parameter(
            'output_directory',
            os.path.expanduser('~/robot_ws/data/friction')
        )

        # ======================================================
        # Read parameters
        # ======================================================
        self.direction = 1 if int(self.get_parameter('direction').value) >= 0 else -1
        self.start_angle_deg = float(self.get_parameter('start_angle_deg').value)
        self.angle_step_deg = float(self.get_parameter('angle_step_deg').value)
        self.angle_count = int(self.get_parameter('angle_count').value)
        self.repeat_count = max(1, int(self.get_parameter('repeat_count').value))
        self.control_frequency = float(self.get_parameter('control_frequency').value)
        self.dt = 1.0 / self.control_frequency
        self.max_torque = abs(float(self.get_parameter('max_torque').value))

        self.fast_ramp_end_torque = abs(float(self.get_parameter('fast_ramp_end_torque').value))
        self.fast_ramp_rate = abs(float(self.get_parameter('fast_ramp_rate').value))
        self.slow_ramp_rate = abs(float(self.get_parameter('slow_ramp_rate').value))

        self.position_tolerance_deg = abs(float(self.get_parameter('position_tolerance_deg').value))
        self.position_backoff_deg = abs(float(self.get_parameter('position_backoff_deg').value))
        self.position_backoff_timeout_sec = float(self.get_parameter('position_backoff_timeout_sec').value)
        self.position_attempt_timeout_sec = float(self.get_parameter('position_attempt_timeout_sec').value)
        self.position_settle_sec = float(self.get_parameter('position_settle_sec').value)
        self.max_position_attempts = max(1, int(self.get_parameter('max_position_attempts').value))
        self.zero_relax_sec = float(self.get_parameter('zero_relax_sec').value)
        self.post_test_zero_sec = float(self.get_parameter('post_test_zero_sec').value)

        self.breakaway_velocity_threshold = abs(float(self.get_parameter('breakaway_velocity_threshold').value))
        self.normal_breakaway_hold_sec = float(self.get_parameter('normal_breakaway_hold_sec').value)
        self.breakaway_position_change_threshold = abs(float(self.get_parameter('breakaway_position_change_threshold').value))
        self.fast_breakaway_velocity_threshold = abs(float(self.get_parameter('fast_breakaway_velocity_threshold').value))
        self.fast_breakaway_hold_sec = float(self.get_parameter('fast_breakaway_hold_sec').value)
        self.rapid_breakaway_velocity_threshold = abs(float(self.get_parameter('rapid_breakaway_velocity_threshold').value))

        self.kinetic_test_velocity = abs(float(self.get_parameter('kinetic_test_velocity').value))
        self.kinetic_launch_release_velocity = abs(float(self.get_parameter('kinetic_launch_release_velocity').value))
        self.kinetic_launch_timeout_sec = float(self.get_parameter('kinetic_launch_timeout_sec').value)
        self.kinetic_launch_fallback_torque = abs(float(self.get_parameter('kinetic_launch_fallback_torque').value))
        self.kinetic_launch_torque_scale = abs(float(self.get_parameter('kinetic_launch_torque_scale').value))
        self.kinetic_launch_torque_limit = abs(float(self.get_parameter('kinetic_launch_torque_limit').value))
        self.kinetic_pi_kp = abs(float(self.get_parameter('kinetic_pi_kp').value))
        self.kinetic_pi_ki = abs(float(self.get_parameter('kinetic_pi_ki').value))
        self.kinetic_pi_torque_limit = abs(float(self.get_parameter('kinetic_pi_torque_limit').value))
        self.kinetic_pi_slew_rate = abs(float(self.get_parameter('kinetic_pi_slew_rate').value))
        self.kinetic_pi_integral_limit = abs(float(self.get_parameter('kinetic_pi_integral_limit').value))
        self.kinetic_velocity_tolerance = abs(float(self.get_parameter('kinetic_velocity_tolerance').value))
        self.kinetic_settle_sec = float(self.get_parameter('kinetic_settle_sec').value)
        self.kinetic_settle_timeout_sec = float(self.get_parameter('kinetic_settle_timeout_sec').value)
        self.kinetic_sample_sec = float(self.get_parameter('kinetic_sample_sec').value)
        self.kinetic_min_valid_fraction = float(self.get_parameter('kinetic_min_valid_fraction').value)

        self.overspeed_threshold = abs(float(self.get_parameter('overspeed_threshold').value))
        self.wrong_direction_velocity_threshold = abs(float(self.get_parameter('wrong_direction_velocity_threshold').value))
        self.passive_wheel_velocity_limit = abs(float(self.get_parameter('passive_wheel_velocity_limit').value))
        self.joint_state_timeout_sec = float(self.get_parameter('joint_state_timeout_sec').value)

        self.output_directory = os.path.expanduser(
            str(self.get_parameter('output_directory').value)
        )

        # ======================================================
        # Target angles / trial sequence
        # ======================================================
        self.target_angles_deg = [
            (self.start_angle_deg + i * self.angle_step_deg) % 360.0
            for i in range(self.angle_count)
        ]

        # sequence per angle: LEFT x repeat_count -> RIGHT x repeat_count -> next angle
        self.condition = 'STATIC_LEFT'
        self.angle_index = 0
        self.repeat_index = 0
        self.test_wheel = 'left'
        self.position_purpose = 'STATIC'

        # Static results retained per angle for kinetic launch
        self.angle_static_breakaway = {
            'left': [],
            'right': [],
        }

        # ======================================================
        # Joint feedback
        # ======================================================
        self.left_position = 0.0
        self.right_position = 0.0
        self.left_velocity = 0.0
        self.right_velocity = 0.0
        self.left_effort = 0.0
        self.right_effort = 0.0
        self.left_received = False
        self.right_received = False
        self.last_joint_state_time = None
        self.feedback_seq = 0

        # ======================================================
        # State machine / timing
        # ======================================================
        self.phase = 'WAIT_JOINT'
        self.phase_start_time = self.get_clock().now()
        self.test_finished = False
        self.switch_future = None

        # Position state
        self.position_attempt = 0
        self.position_status = 'NOT_SET'
        self.position_left_error_deg = None
        self.position_right_error_deg = None
        self.resolved_left_target = None
        self.resolved_right_target = None
        self.resolved_left_backoff_target = None
        self.resolved_right_backoff_target = None
        self.position_target_resolved = False
        self.settle_start_time = None

        # Trial initial positions
        self.initial_left_position = None
        self.initial_right_position = None
        self.initial_left_phase_deg = None
        self.initial_right_phase_deg = None

        # Static measurement
        self.current_torque = 0.0
        self.current_ramp_rate = self.fast_ramp_rate
        self.breakaway_candidate_active = False
        self.breakaway_candidate_position = None
        self.breakaway_candidate_torque = None
        self.breakaway_candidate_feedback_effort = None
        self.breakaway_candidate_velocity = None
        self.normal_hold_start_time = None
        self.fast_hold_start_time = None
        self.last_detector_feedback_seq = -1

        self.breakaway_detected = False
        self.breakaway_detection_method = 'NONE'
        self.breakaway_command_torque = None
        self.breakaway_feedback_effort = None
        self.breakaway_velocity = None
        self.breakaway_position = None
        self.breakaway_delta_position = None
        self.max_torque_reached = False

        # Kinetic measurement
        self.kinetic_target_velocity = self.direction * self.kinetic_test_velocity
        self.kinetic_launch_left_torque = 0.0
        self.kinetic_launch_right_torque = 0.0
        self.kinetic_launch_left_active = False
        self.kinetic_launch_right_active = False
        self.kinetic_launch_start_time = None
        self.kinetic_pi_left_active = False
        self.kinetic_pi_right_active = False
        self.kinetic_pi_left_integral = 0.0
        self.kinetic_pi_right_integral = 0.0
        self.kinetic_pi_left_tau_ff = 0.0
        self.kinetic_pi_right_tau_ff = 0.0
        self.kinetic_settle_window_start = None
        self.kinetic_settle_phase_start = None
        self.kinetic_sample_start = None
        self.last_kinetic_feedback_seq = -1
        self.kinetic_all_count = 0
        self.kinetic_valid_count = 0
        self.kinetic_left_velocity_samples = []
        self.kinetic_right_velocity_samples = []
        self.kinetic_left_effort_samples = []
        self.kinetic_right_effort_samples = []
        self.kinetic_valid = False
        self.kinetic_valid_fraction = 0.0
        self.kinetic_mean_left_velocity = None
        self.kinetic_mean_right_velocity = None
        self.kinetic_mean_left_effort = None
        self.kinetic_mean_right_effort = None
        self.kinetic_std_left_effort = None
        self.kinetic_std_right_effort = None

        # Fault
        self.safety_triggered = False
        self.fault_type = 'NONE'
        self.safety_reason = ''

        # ======================================================
        # ROS interfaces
        # ======================================================
        self.switch_client = self.create_client(
            SwitchController,
            '/controller_manager/switch_controller'
        )

        self.position_pub = self.create_publisher(
            Float64MultiArray,
            '/bldc_position_controller/commands',
            10
        )
        self.left_effort_pub = self.create_publisher(
            Float64MultiArray,
            '/left_bldc_effort_controller/commands',
            10
        )
        self.right_effort_pub = self.create_publisher(
            Float64MultiArray,
            '/right_bldc_effort_controller/commands',
            10
        )
        self.left_drive_pub = self.create_publisher(
            Float64MultiArray,
            '/left_bldc_drive_controller/commands',
            10
        )
        self.right_drive_pub = self.create_publisher(
            Float64MultiArray,
            '/right_bldc_drive_controller/commands',
            10
        )

        self.joint_sub = self.create_subscription(
            JointState,
            '/joint_states',
            self.joint_callback,
            100
        )

        # ======================================================
        # CSV output
        # ======================================================
        Path(self.output_directory).mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        direction_name = 'forward' if self.direction > 0 else 'reverse'
        self.run_name = (
            f'friction_static_only_{direction_name}_'
            f'repeat{self.repeat_count}_{timestamp}'
        )
        self.raw_path = os.path.join(
            self.output_directory,
            self.run_name + '_raw.csv'
        )
        self.summary_path = os.path.join(
            self.output_directory,
            self.run_name + '_summary.csv'
        )

        self.raw_file = open(self.raw_path, 'w', newline='')
        self.raw_writer = csv.writer(self.raw_file)
        self.raw_writer.writerow([
            'ros_time_sec', 'phase', 'condition', 'position_purpose',
            'angle_index', 'target_phase_deg', 'repeat_number', 'test_wheel',
            'direction', 'position_attempt', 'position_status',
            'position_left_error_deg', 'position_right_error_deg',
            'command_torque_nm', 'ramp_rate_nm_s',
            'breakaway_candidate_active', 'breakaway_candidate_torque_nm',
            'normal_hold_elapsed_sec', 'fast_hold_elapsed_sec',
            'kinetic_target_velocity_rad_s',
            'kinetic_launch_left_torque_nm', 'kinetic_launch_right_torque_nm',
            'kinetic_launch_left_active', 'kinetic_launch_right_active',
            'kinetic_pi_left_active', 'kinetic_pi_right_active',
            'kinetic_pi_left_tau_ff_nm', 'kinetic_pi_right_tau_ff_nm',
            'left_position_rad', 'right_position_rad',
            'left_velocity_rad_s', 'right_velocity_rad_s',
            'left_effort_nm', 'right_effort_nm',
            'breakaway_detected', 'breakaway_detection_method',
            'safety_triggered', 'fault_type'
        ])

        self.summary_file = open(self.summary_path, 'w', newline='')
        self.summary_writer = csv.writer(self.summary_file)
        self.summary_writer.writerow([
            'test_type', 'angle_index', 'target_phase_deg', 'repeat_number',
            'wheel', 'direction', 'position_attempts_used', 'position_status',
            'position_left_error_deg', 'position_right_error_deg',
            'initial_left_position_rad', 'initial_right_position_rad',
            'initial_left_phase_deg', 'initial_right_phase_deg',
            'breakaway_detected', 'breakaway_detection_method',
            'breakaway_command_torque_nm', 'breakaway_feedback_effort_nm',
            'breakaway_velocity_rad_s', 'breakaway_position_rad',
            'breakaway_delta_position_rad', 'max_torque_reached',
            'kinetic_target_velocity_rad_s',
            'kinetic_launch_left_torque_nm', 'kinetic_launch_right_torque_nm',
            'kinetic_valid', 'kinetic_valid_fraction',
            'kinetic_mean_left_velocity_rad_s', 'kinetic_mean_right_velocity_rad_s',
            'kinetic_mean_left_effort_nm', 'kinetic_mean_right_effort_nm',
            'kinetic_std_left_effort_nm', 'kinetic_std_right_effort_nm',
            'safety_triggered', 'fault_type', 'safety_reason'
        ])

        self.timer = self.create_timer(self.dt, self.control_loop)

        self.get_logger().info('========================================')
        self.get_logger().info('STATIC BREAKAWAY EXPERIMENT - 3 REPEATS')
        self.get_logger().info(
            f'Per angle: LEFT static x{self.repeat_count}, RIGHT static x{self.repeat_count}; kinetic disabled'
        )
        self.get_logger().info(
            f'Position: +/-{self.position_tolerance_deg:.1f} deg, '
            f'backoff={self.position_backoff_deg:.1f} deg, '
            f'max attempts={self.max_position_attempts}'
        )
        self.get_logger().info(
            f'Breakaway: normal >= {self.breakaway_velocity_threshold:.2f} rad/s '
            f'for {self.normal_breakaway_hold_sec:.2f}s + dtheta >= '
            f'{self.breakaway_position_change_threshold:.3f} rad; '
            f'fast >= {self.fast_breakaway_velocity_threshold:.2f} rad/s '
            f'for {self.fast_breakaway_hold_sec:.2f}s; '
            f'rapid >= {self.rapid_breakaway_velocity_threshold:.2f} rad/s'
        )
        self.get_logger().info(f'Raw={self.raw_path}')
        self.get_logger().info(f'Summary={self.summary_path}')
        self.get_logger().info('========================================')

    # ==========================================================
    # Generic helpers
    # ==========================================================
    @staticmethod
    def phase_deg(angle_rad):
        return math.degrees(angle_rad) % 360.0

    @staticmethod
    def circular_phase_error_deg(actual_deg, target_deg):
        return abs(((actual_deg - target_deg + 180.0) % 360.0) - 180.0)

    @staticmethod
    def nearest_equivalent_angle(current_rad, desired_phase_rad):
        turns = round((current_rad - desired_phase_rad) / (2.0 * math.pi))
        return desired_phase_rad + turns * 2.0 * math.pi

    @staticmethod
    def mean(values):
        if not values:
            return None
        return float(statistics.fmean(values))

    @staticmethod
    def std(values):
        if len(values) < 2:
            return 0.0 if len(values) == 1 else None
        return float(statistics.stdev(values))

    def target_phase_deg(self):
        return self.target_angles_deg[self.angle_index]

    def phase_elapsed(self):
        return (self.get_clock().now() - self.phase_start_time).nanoseconds * 1e-9

    def elapsed_from(self, start_time):
        if start_time is None:
            return 0.0
        return (self.get_clock().now() - start_time).nanoseconds * 1e-9

    def set_phase(self, phase):
        self.phase = phase
        self.phase_start_time = self.get_clock().now()

    def joint_state_age(self):
        if self.last_joint_state_time is None:
            return float('inf')
        return (self.get_clock().now() - self.last_joint_state_time).nanoseconds * 1e-9

    # ==========================================================
    # Feedback
    # ==========================================================
    def joint_callback(self, msg):
        found = False
        for i, name in enumerate(msg.name):
            if name == 'left_wheel_joint':
                found = True
                if i < len(msg.position):
                    self.left_position = float(msg.position[i])
                if i < len(msg.velocity):
                    self.left_velocity = float(msg.velocity[i])
                    self.left_received = True
                if i < len(msg.effort):
                    self.left_effort = float(msg.effort[i])

            elif name == 'right_wheel_joint':
                found = True
                if i < len(msg.position):
                    self.right_position = float(msg.position[i])
                if i < len(msg.velocity):
                    self.right_velocity = float(msg.velocity[i])
                    self.right_received = True
                if i < len(msg.effort):
                    self.right_effort = float(msg.effort[i])

        if found:
            self.last_joint_state_time = self.get_clock().now()
            self.feedback_seq += 1

    # ==========================================================
    # Controller switching
    # ==========================================================
    def send_switch(self, activate, deactivate):
        if not self.switch_client.service_is_ready():
            self.get_logger().warn(
                'Waiting for controller manager...',
                throttle_duration_sec=1.0
            )
            return False

        req = SwitchController.Request()
        req.activate_controllers = activate
        req.deactivate_controllers = deactivate
        req.strictness = SwitchController.Request.BEST_EFFORT
        req.activate_asap = True
        self.switch_future = self.switch_client.call_async(req)
        return True

    def request_position_mode(self):
        return self.send_switch(
            ['bldc_position_controller'],
            [
                'left_bldc_effort_controller',
                'right_bldc_effort_controller',
                'left_bldc_drive_controller',
                'right_bldc_drive_controller',
            ]
        )

    def request_static_effort_mode(self):
        return self.send_switch(
            [
                'left_bldc_effort_controller',
                'right_bldc_effort_controller',
            ],
            [
                'bldc_position_controller',
                'left_bldc_drive_controller',
                'right_bldc_drive_controller',
            ]
        )

    def request_kinetic_mode(self):
        return self.send_switch(
            [
                'left_bldc_drive_controller',
                'right_bldc_drive_controller',
            ],
            [
                'bldc_position_controller',
                'left_bldc_effort_controller',
                'right_bldc_effort_controller',
            ]
        )

    def switch_finished_successfully(self):
        if self.switch_future is None:
            return None
        if not self.switch_future.done():
            return None
        try:
            result = self.switch_future.result()
            ok = bool(result.ok)
        except Exception as e:
            self.get_logger().error(f'Controller switch exception: {e}')
            ok = False
        self.switch_future = None
        return ok

    # ==========================================================
    # Command publishing
    # ==========================================================
    def publish_position_values(self, left, right):
        msg = Float64MultiArray()
        msg.data = [float(left), float(right)]
        self.position_pub.publish(msg)

    def publish_effort(self, left, right):
        lm = Float64MultiArray()
        lm.data = [float(left)]
        rm = Float64MultiArray()
        rm.data = [float(right)]
        self.left_effort_pub.publish(lm)
        self.right_effort_pub.publish(rm)

    def publish_zero_effort(self):
        self.publish_effort(0.0, 0.0)

    def publish_static_test_torque(self):
        if self.test_wheel == 'left':
            self.publish_effort(self.current_torque, 0.0)
        else:
            self.publish_effort(0.0, self.current_torque)

    def publish_drive(self, left_velocity, left_tau_ff, right_velocity, right_tau_ff):
        lm = Float64MultiArray()
        lm.data = [float(left_velocity), float(left_tau_ff)]
        rm = Float64MultiArray()
        rm.data = [float(right_velocity), float(right_tau_ff)]
        self.left_drive_pub.publish(lm)
        self.right_drive_pub.publish(rm)

    def publish_zero_drive(self):
        self.publish_drive(0.0, 0.0, 0.0, 0.0)

    # ==========================================================
    # Positioning
    # ==========================================================
    def reset_positioning(self, purpose):
        self.position_purpose = purpose
        self.position_attempt = 0
        self.position_status = 'NOT_SET'
        self.position_left_error_deg = None
        self.position_right_error_deg = None
        self.resolved_left_target = None
        self.resolved_right_target = None
        self.resolved_left_backoff_target = None
        self.resolved_right_backoff_target = None
        self.position_target_resolved = False
        self.settle_start_time = None

    def backoff_phase_deg(self):
        # Approach target in the experiment direction.
        # Forward: target-backoff -> target.
        # Reverse: target+backoff -> target.
        return (
            self.target_phase_deg()
            - self.direction * self.position_backoff_deg
        ) % 360.0

    def resolve_backoff_targets(self):
        desired = math.radians(self.backoff_phase_deg())
        self.resolved_left_backoff_target = self.nearest_equivalent_angle(
            self.left_position, desired
        )
        self.resolved_right_backoff_target = self.nearest_equivalent_angle(
            self.right_position, desired
        )

    def resolve_position_targets(self):
        desired = math.radians(self.target_phase_deg())
        self.resolved_left_target = self.nearest_equivalent_angle(
            self.left_position, desired
        )
        self.resolved_right_target = self.nearest_equivalent_angle(
            self.right_position, desired
        )
        self.position_target_resolved = True

    def phase_errors_to(self, phase_target_deg):
        left_error = self.circular_phase_error_deg(
            self.phase_deg(self.left_position), phase_target_deg
        )
        right_error = self.circular_phase_error_deg(
            self.phase_deg(self.right_position), phase_target_deg
        )
        return left_error, right_error

    def update_target_errors(self):
        (
            self.position_left_error_deg,
            self.position_right_error_deg,
        ) = self.phase_errors_to(self.target_phase_deg())

    def positions_within_tolerance(self):
        self.update_target_errors()
        return (
            self.position_left_error_deg <= self.position_tolerance_deg
            and self.position_right_error_deg <= self.position_tolerance_deg
        )

    def start_position_attempt(self, need_switch=True):
        self.position_attempt += 1
        self.position_target_resolved = False
        self.settle_start_time = None

        self.get_logger().info(
            f'POSITION ATTEMPT {self.position_attempt}/{self.max_position_attempts} | '
            f'purpose={self.position_purpose} | target={self.target_phase_deg():.1f} deg | '
            f'condition={self.condition} | repeat={self.repeat_index + 1}/{self.repeat_count}'
        )

        if need_switch:
            self.set_phase('REQUEST_POSITION_MODE')
        else:
            self.resolve_backoff_targets()
            self.set_phase('MOVE_TO_BACKOFF')

    def accept_position_after_max_attempts(self, reason):
        self.update_target_errors()
        self.position_status = 'MAX_RETRIES_ACCEPTED'
        self.get_logger().warn(
            f'MAX POSITION ATTEMPTS REACHED | proceeding from actual position | '
            f'Lerr={self.position_left_error_deg:.2f} deg | '
            f'Rerr={self.position_right_error_deg:.2f} deg | {reason}'
        )
        self.continue_after_positioning()

    def capture_trial_initial_position(self):
        self.initial_left_position = self.left_position
        self.initial_right_position = self.right_position
        self.initial_left_phase_deg = self.phase_deg(self.left_position)
        self.initial_right_phase_deg = self.phase_deg(self.right_position)
        self.update_target_errors()

    def continue_after_positioning(self):
        # We are still in position mode here.
        if self.position_purpose == 'STATIC':
            self.set_phase('REQUEST_STATIC_EFFORT_MODE')
        else:
            self.set_phase('REQUEST_KINETIC_MODE')

    # ==========================================================
    # Static measurement
    # ==========================================================
    def reset_static_measurement(self):
        self.current_torque = 0.0
        self.current_ramp_rate = self.fast_ramp_rate
        self.breakaway_candidate_active = False
        self.breakaway_candidate_position = None
        self.breakaway_candidate_torque = None
        self.breakaway_candidate_feedback_effort = None
        self.breakaway_candidate_velocity = None
        self.normal_hold_start_time = None
        self.fast_hold_start_time = None
        self.last_detector_feedback_seq = -1

        self.breakaway_detected = False
        self.breakaway_detection_method = 'NONE'
        self.breakaway_command_torque = None
        self.breakaway_feedback_effort = None
        self.breakaway_velocity = None
        self.breakaway_position = None
        self.breakaway_delta_position = None
        self.max_torque_reached = False

        self.reset_fault()

    def test_wheel_state(self):
        if self.test_wheel == 'left':
            return self.left_position, self.left_velocity, self.left_effort
        return self.right_position, self.right_velocity, self.right_effort

    def passive_wheel_velocity(self):
        return self.right_velocity if self.test_wheel == 'left' else self.left_velocity

    def start_breakaway_candidate(self, position, velocity, effort):
        self.breakaway_candidate_active = True
        self.breakaway_candidate_position = position
        self.breakaway_candidate_torque = self.current_torque
        self.breakaway_candidate_feedback_effort = effort
        self.breakaway_candidate_velocity = velocity

        now = self.get_clock().now()
        self.normal_hold_start_time = now
        v_dir = self.direction * velocity
        self.fast_hold_start_time = (
            now if v_dir >= self.fast_breakaway_velocity_threshold else None
        )

        self.get_logger().info(
            f'BREAKAWAY CANDIDATE | angle={self.target_phase_deg():.1f} | '
            f'{self.test_wheel.upper()} | repeat={self.repeat_index + 1}/{self.repeat_count} | '
            f'tau={self.current_torque:+.3f} Nm | v={velocity:+.3f} rad/s | TORQUE FROZEN'
        )

    def clear_breakaway_candidate(self):
        self.breakaway_candidate_active = False
        self.breakaway_candidate_position = None
        self.breakaway_candidate_torque = None
        self.breakaway_candidate_feedback_effort = None
        self.breakaway_candidate_velocity = None
        self.normal_hold_start_time = None
        self.fast_hold_start_time = None

    def confirm_breakaway(self, method):
        if self.breakaway_detected:
            return
        position, velocity, _ = self.test_wheel_state()
        self.breakaway_detected = True
        self.breakaway_detection_method = method
        self.breakaway_command_torque = self.breakaway_candidate_torque
        self.breakaway_feedback_effort = self.breakaway_candidate_feedback_effort
        self.breakaway_velocity = velocity
        self.breakaway_position = position
        self.breakaway_delta_position = self.direction * (
            position - self.breakaway_candidate_position
        )

        self.get_logger().info('****************************************')
        self.get_logger().info(
            f'BREAKAWAY CONFIRMED | method={method} | '
            f'angle={self.target_phase_deg():.1f} | {self.test_wheel.upper()} | '
            f'repeat={self.repeat_index + 1}/{self.repeat_count} | '
            f'onset_tau={self.breakaway_command_torque:+.3f} Nm | '
            f'current_v={self.breakaway_velocity:+.3f} rad/s'
        )
        self.get_logger().info('****************************************')

    def update_breakaway_detector(self):
        if self.feedback_seq == self.last_detector_feedback_seq:
            return
        self.last_detector_feedback_seq = self.feedback_seq

        position, velocity, effort = self.test_wheel_state()
        v_dir = self.direction * velocity

        if not self.breakaway_candidate_active:
            if v_dir >= self.breakaway_velocity_threshold:
                self.start_breakaway_candidate(position, velocity, effort)
            return

        if v_dir < self.breakaway_velocity_threshold:
            self.get_logger().info(
                f'CANDIDATE CANCELLED | v={velocity:+.3f} rad/s'
            )
            self.clear_breakaway_candidate()
            return

        normal_elapsed = self.elapsed_from(self.normal_hold_start_time)
        delta = self.direction * (position - self.breakaway_candidate_position)

        if v_dir >= self.rapid_breakaway_velocity_threshold:
            self.confirm_breakaway('RAPID_ACCELERATION')
            return

        if v_dir >= self.fast_breakaway_velocity_threshold:
            if self.fast_hold_start_time is None:
                self.fast_hold_start_time = self.get_clock().now()
            fast_elapsed = self.elapsed_from(self.fast_hold_start_time)
        else:
            self.fast_hold_start_time = None
            fast_elapsed = 0.0

        if fast_elapsed >= self.fast_breakaway_hold_sec:
            self.confirm_breakaway('FAST_VELOCITY_HOLD')
            return

        if (
            normal_elapsed >= self.normal_breakaway_hold_sec
            and delta >= self.breakaway_position_change_threshold
        ):
            self.confirm_breakaway('PERSISTENT_MOTION_HOLD')

    # ==========================================================
    # Kinetic measurement
    # ==========================================================
    def reset_kinetic_measurement(self):
        self.kinetic_target_velocity = self.direction * self.kinetic_test_velocity
        self.kinetic_launch_left_torque = 0.0
        self.kinetic_launch_right_torque = 0.0
        self.kinetic_launch_left_active = False
        self.kinetic_launch_right_active = False
        self.kinetic_launch_start_time = None
        self.kinetic_pi_left_active = False
        self.kinetic_pi_right_active = False
        self.kinetic_pi_left_integral = 0.0
        self.kinetic_pi_right_integral = 0.0
        self.kinetic_pi_left_tau_ff = 0.0
        self.kinetic_pi_right_tau_ff = 0.0
        self.kinetic_settle_window_start = None
        self.kinetic_settle_phase_start = None
        self.kinetic_sample_start = None
        self.last_kinetic_feedback_seq = -1
        self.kinetic_all_count = 0
        self.kinetic_valid_count = 0
        self.kinetic_left_velocity_samples = []
        self.kinetic_right_velocity_samples = []
        self.kinetic_left_effort_samples = []
        self.kinetic_right_effort_samples = []
        self.kinetic_valid = False
        self.kinetic_valid_fraction = 0.0
        self.kinetic_mean_left_velocity = None
        self.kinetic_mean_right_velocity = None
        self.kinetic_mean_left_effort = None
        self.kinetic_mean_right_effort = None
        self.kinetic_std_left_effort = None
        self.kinetic_std_right_effort = None
        self.reset_fault()

    def median_breakaway_for_wheel(self, wheel):
        vals = [
            abs(float(v))
            for v in self.angle_static_breakaway[wheel]
            if v is not None and math.isfinite(float(v))
        ]
        if vals:
            return float(statistics.median(vals))
        return self.kinetic_launch_fallback_torque

    def prepare_kinetic_launch(self):
        left_mag = self.median_breakaway_for_wheel('left')
        right_mag = self.median_breakaway_for_wheel('right')

        left_mag = min(
            left_mag * self.kinetic_launch_torque_scale,
            self.kinetic_launch_torque_limit,
            self.max_torque
        )
        right_mag = min(
            right_mag * self.kinetic_launch_torque_scale,
            self.kinetic_launch_torque_limit,
            self.max_torque
        )

        self.kinetic_launch_left_torque = self.direction * left_mag
        self.kinetic_launch_right_torque = self.direction * right_mag
        self.kinetic_launch_left_active = True
        self.kinetic_launch_right_active = True
        self.kinetic_launch_start_time = self.get_clock().now()

        self.get_logger().info(
            f'KINETIC LAUNCH START | target_v={self.kinetic_target_velocity:+.3f} rad/s | '
            f'left_tau_ff={self.kinetic_launch_left_torque:+.3f} Nm | '
            f'right_tau_ff={self.kinetic_launch_right_torque:+.3f} Nm'
        )

    def _clamp(self, value, lo, hi):
        return max(lo, min(hi, value))

    def _slew(self, current, target, rate_limit):
        max_step = rate_limit * self.dt
        delta = self._clamp(target - current, -max_step, max_step)
        return current + delta

    def _start_pi_handover_for_wheel(self, wheel):
        # Bumpless transfer: initialize PI integral so PI output starts at the
        # currently applied launch tau_ff instead of suddenly dropping to zero.
        if wheel == 'left':
            velocity = self.left_velocity
            launch_tau = self.kinetic_launch_left_torque
        else:
            velocity = self.right_velocity
            launch_tau = self.kinetic_launch_right_torque

        error = self.kinetic_target_velocity - velocity
        if self.kinetic_pi_ki > 1e-9:
            integral = (launch_tau - self.kinetic_pi_kp * error) / self.kinetic_pi_ki
            integral = self._clamp(
                integral,
                -self.kinetic_pi_integral_limit,
                self.kinetic_pi_integral_limit
            )
        else:
            integral = 0.0

        if wheel == 'left':
            self.kinetic_launch_left_active = False
            self.kinetic_pi_left_active = True
            self.kinetic_pi_left_integral = integral
            self.kinetic_pi_left_tau_ff = launch_tau
        else:
            self.kinetic_launch_right_active = False
            self.kinetic_pi_right_active = True
            self.kinetic_pi_right_integral = integral
            self.kinetic_pi_right_tau_ff = launch_tau

        self.get_logger().info(
            f'{wheel.upper()} BUMPLESS PI HANDOVER | '
            f'v={velocity:+.3f} rad/s | tau_ff_start={launch_tau:+.3f} Nm | '
            f'integral_init={integral:+.3f}'
        )

    def update_launch_handover(self):
        left_v_dir = self.direction * self.left_velocity
        right_v_dir = self.direction * self.right_velocity

        if (
            self.kinetic_launch_left_active
            and left_v_dir >= self.kinetic_launch_release_velocity
        ):
            self._start_pi_handover_for_wheel('left')

        if (
            self.kinetic_launch_right_active
            and right_v_dir >= self.kinetic_launch_release_velocity
        ):
            self._start_pi_handover_for_wheel('right')

    def update_kinetic_pi(self):
        # Outer PI supplements the internal MIT velocity loop.
        # Anti-windup: integrate only if unsaturated or if the error drives
        # the command back toward the allowed range.
        limit = min(self.kinetic_pi_torque_limit, self.max_torque)

        def one_wheel(active, velocity, integral, current_tau):
            if not active:
                return integral, current_tau

            error = self.kinetic_target_velocity - velocity
            candidate_integral = self._clamp(
                integral + error * self.dt,
                -self.kinetic_pi_integral_limit,
                self.kinetic_pi_integral_limit
            )
            unsat = self.kinetic_pi_kp * error + self.kinetic_pi_ki * candidate_integral
            target_tau = self._clamp(unsat, -limit, limit)

            saturated_high = unsat > limit
            saturated_low = unsat < -limit
            if (saturated_high and error > 0.0) or (saturated_low and error < 0.0):
                # Keep previous integral if it would wind farther into saturation.
                candidate_integral = integral
                unsat = self.kinetic_pi_kp * error + self.kinetic_pi_ki * candidate_integral
                target_tau = self._clamp(unsat, -limit, limit)

            next_tau = self._slew(current_tau, target_tau, self.kinetic_pi_slew_rate)
            return candidate_integral, next_tau

        self.kinetic_pi_left_integral, self.kinetic_pi_left_tau_ff = one_wheel(
            self.kinetic_pi_left_active,
            self.left_velocity,
            self.kinetic_pi_left_integral,
            self.kinetic_pi_left_tau_ff
        )
        self.kinetic_pi_right_integral, self.kinetic_pi_right_tau_ff = one_wheel(
            self.kinetic_pi_right_active,
            self.right_velocity,
            self.kinetic_pi_right_integral,
            self.kinetic_pi_right_tau_ff
        )

    def current_kinetic_tau_ff(self):
        left_tau = (
            self.kinetic_launch_left_torque
            if self.kinetic_launch_left_active
            else self.kinetic_pi_left_tau_ff
        )
        right_tau = (
            self.kinetic_launch_right_torque
            if self.kinetic_launch_right_active
            else self.kinetic_pi_right_tau_ff
        )
        return left_tau, right_tau

    def publish_kinetic_control_command(self):
        self.update_kinetic_pi()
        left_tau, right_tau = self.current_kinetic_tau_ff()
        self.publish_drive(
            self.kinetic_target_velocity,
            left_tau,
            self.kinetic_target_velocity,
            right_tau
        )

    def kinetic_speed_ok(self):
        left_error = self.left_velocity - self.kinetic_target_velocity
        right_error = self.right_velocity - self.kinetic_target_velocity
        return (
            abs(left_error) <= self.kinetic_velocity_tolerance
            and abs(right_error) <= self.kinetic_velocity_tolerance
        )

    def collect_kinetic_sample(self):
        if self.feedback_seq == self.last_kinetic_feedback_seq:
            return
        self.last_kinetic_feedback_seq = self.feedback_seq
        self.kinetic_all_count += 1

        if self.kinetic_speed_ok():
            self.kinetic_valid_count += 1
            self.kinetic_left_velocity_samples.append(self.left_velocity)
            self.kinetic_right_velocity_samples.append(self.right_velocity)
            self.kinetic_left_effort_samples.append(self.left_effort)
            self.kinetic_right_effort_samples.append(self.right_effort)

    def finalize_kinetic(self):
        if self.kinetic_all_count > 0:
            self.kinetic_valid_fraction = self.kinetic_valid_count / self.kinetic_all_count
        else:
            self.kinetic_valid_fraction = 0.0

        self.kinetic_mean_left_velocity = self.mean(self.kinetic_left_velocity_samples)
        self.kinetic_mean_right_velocity = self.mean(self.kinetic_right_velocity_samples)
        self.kinetic_mean_left_effort = self.mean(self.kinetic_left_effort_samples)
        self.kinetic_mean_right_effort = self.mean(self.kinetic_right_effort_samples)
        self.kinetic_std_left_effort = self.std(self.kinetic_left_effort_samples)
        self.kinetic_std_right_effort = self.std(self.kinetic_right_effort_samples)

        self.kinetic_valid = (
            self.kinetic_valid_count > 0
            and self.kinetic_valid_fraction >= self.kinetic_min_valid_fraction
            and not self.safety_triggered
        )

        self.get_logger().info(
            f'KINETIC RESULT | valid={int(self.kinetic_valid)} | '
            f'fraction={self.kinetic_valid_fraction:.3f} | '
            f'vL_mean={self.kinetic_mean_left_velocity} | '
            f'vR_mean={self.kinetic_mean_right_velocity} | '
            f'tauL_mean={self.kinetic_mean_left_effort} Nm | '
            f'tauR_mean={self.kinetic_mean_right_effort} Nm'
        )

    # ==========================================================
    # Safety
    # ==========================================================
    def reset_fault(self):
        self.safety_triggered = False
        self.fault_type = 'NONE'
        self.safety_reason = ''

    def trigger_fault(self, fault_type, reason):
        self.safety_triggered = True
        self.fault_type = fault_type
        self.safety_reason = reason
        self.get_logger().error(
            f'SAFETY FAULT | {fault_type} | {reason}'
        )

    def check_common_safety(self):
        if self.joint_state_age() > self.joint_state_timeout_sec:
            self.trigger_fault('FEEDBACK_TIMEOUT', '/joint_states timeout')
            return False
        return True

    def check_static_safety(self):
        if not self.check_common_safety():
            return False

        _, v_test, _ = self.test_wheel_state()
        v_dir = self.direction * v_test
        v_passive = self.passive_wheel_velocity()

        if v_dir < -self.wrong_direction_velocity_threshold:
            self.trigger_fault(
                'WRONG_DIRECTION',
                f'test wheel velocity={v_test:+.3f} rad/s'
            )
            return False

        if abs(v_passive) > self.passive_wheel_velocity_limit:
            self.trigger_fault(
                'PASSIVE_WHEEL_OVERSPEED',
                f'passive wheel velocity={v_passive:+.3f} rad/s'
            )
            return False

        # Preserve valid candidate onset before hard safety.
        if (
            self.breakaway_candidate_active
            and v_dir >= self.rapid_breakaway_velocity_threshold
        ):
            self.confirm_breakaway('RAPID_ACCELERATION')
            return True

        if abs(v_test) > self.overspeed_threshold:
            self.trigger_fault(
                'OVERSPEED_SAFETY',
                f'test wheel velocity={v_test:+.3f} rad/s'
            )
            return False

        return True

    def check_kinetic_safety(self):
        if not self.check_common_safety():
            return False

        for wheel, velocity in (
            ('left', self.left_velocity),
            ('right', self.right_velocity),
        ):
            v_dir = self.direction * velocity
            if v_dir < -self.wrong_direction_velocity_threshold:
                self.trigger_fault(
                    'KINETIC_WRONG_DIRECTION',
                    f'{wheel} velocity={velocity:+.3f} rad/s'
                )
                return False
            if abs(velocity) > self.overspeed_threshold:
                self.trigger_fault(
                    'KINETIC_OVERSPEED',
                    f'{wheel} velocity={velocity:+.3f} rad/s'
                )
                return False
        return True

    # ==========================================================
    # CSV
    # ==========================================================
    def save_raw(self):
        normal_elapsed = self.elapsed_from(self.normal_hold_start_time)
        fast_elapsed = self.elapsed_from(self.fast_hold_start_time)
        self.raw_writer.writerow([
            self.get_clock().now().nanoseconds * 1e-9,
            self.phase,
            self.condition,
            self.position_purpose,
            self.angle_index,
            self.target_phase_deg(),
            self.repeat_index + 1,
            self.test_wheel if self.condition != 'KINETIC' else 'both',
            self.direction,
            self.position_attempt,
            self.position_status,
            self.position_left_error_deg,
            self.position_right_error_deg,
            self.current_torque,
            self.current_ramp_rate,
            int(self.breakaway_candidate_active),
            self.breakaway_candidate_torque,
            normal_elapsed,
            fast_elapsed,
            self.kinetic_target_velocity,
            self.kinetic_launch_left_torque,
            self.kinetic_launch_right_torque,
            int(self.kinetic_launch_left_active),
            int(self.kinetic_launch_right_active),
            int(self.kinetic_pi_left_active),
            int(self.kinetic_pi_right_active),
            self.kinetic_pi_left_tau_ff,
            self.kinetic_pi_right_tau_ff,
            self.left_position,
            self.right_position,
            self.left_velocity,
            self.right_velocity,
            self.left_effort,
            self.right_effort,
            int(self.breakaway_detected),
            self.breakaway_detection_method,
            int(self.safety_triggered),
            self.fault_type,
        ])
        self.raw_file.flush()

    def save_static_summary(self):
        self.summary_writer.writerow([
            'STATIC',
            self.angle_index,
            self.target_phase_deg(),
            self.repeat_index + 1,
            self.test_wheel,
            self.direction,
            self.position_attempt,
            self.position_status,
            self.position_left_error_deg,
            self.position_right_error_deg,
            self.initial_left_position,
            self.initial_right_position,
            self.initial_left_phase_deg,
            self.initial_right_phase_deg,
            int(self.breakaway_detected),
            self.breakaway_detection_method,
            self.breakaway_command_torque,
            self.breakaway_feedback_effort,
            self.breakaway_velocity,
            self.breakaway_position,
            self.breakaway_delta_position,
            int(self.max_torque_reached),
            None, None, None,
            None, None,
            None, None,
            None, None,
            None, None,
            int(self.safety_triggered),
            self.fault_type,
            self.safety_reason,
        ])
        self.summary_file.flush()

    def save_kinetic_summary(self):
        self.summary_writer.writerow([
            'KINETIC',
            self.angle_index,
            self.target_phase_deg(),
            self.repeat_index + 1,
            'both',
            self.direction,
            self.position_attempt,
            self.position_status,
            self.position_left_error_deg,
            self.position_right_error_deg,
            self.initial_left_position,
            self.initial_right_position,
            self.initial_left_phase_deg,
            self.initial_right_phase_deg,
            None, None, None, None, None, None, None, None,
            self.kinetic_target_velocity,
            self.kinetic_launch_left_torque,
            self.kinetic_launch_right_torque,
            int(self.kinetic_valid),
            self.kinetic_valid_fraction,
            self.kinetic_mean_left_velocity,
            self.kinetic_mean_right_velocity,
            self.kinetic_mean_left_effort,
            self.kinetic_mean_right_effort,
            self.kinetic_std_left_effort,
            self.kinetic_std_right_effort,
            int(self.safety_triggered),
            self.fault_type,
            self.safety_reason,
        ])
        self.summary_file.flush()

    # ==========================================================
    # Trial sequencing
    # ==========================================================
    def reset_angle_static_cache(self):
        self.angle_static_breakaway = {'left': [], 'right': []}

    def begin_current_trial(self):
        """Start the current STATIC trial only."""
        self.reset_fault()
        self.reset_positioning('STATIC')

        if self.condition == 'STATIC_LEFT':
            self.test_wheel = 'left'
        elif self.condition == 'STATIC_RIGHT':
            self.test_wheel = 'right'
        else:
            self.get_logger().error(
                f'Unexpected condition in static-only mode: {self.condition}'
            )
            self.finish_experiment()
            return

        self.reset_static_measurement()
        self.start_position_attempt(need_switch=True)

    def advance_trial(self):
        """
        Static-only sequence for each angle:

          LEFT repeat 1
          LEFT repeat 2
          LEFT repeat 3
          RIGHT repeat 1
          RIGHT repeat 2
          RIGHT repeat 3
          -> next angle

        repeat_index increments after every trial.
        """
        finished_wheel = self.test_wheel
        finished_repeat = self.repeat_index + 1

        self.get_logger().info(
            f'TRIAL COMPLETE | angle={self.target_phase_deg():.1f} deg | '
            f'wheel={finished_wheel.upper()} | '
            f'repeat={finished_repeat}/{self.repeat_count}'
        )

        self.repeat_index += 1

        # Continue repeating the same wheel.
        if self.repeat_index < self.repeat_count:
            self.get_logger().info(
                f'NEXT TRIAL -> {self.test_wheel.upper()} | '
                f'angle={self.target_phase_deg():.1f} deg | '
                f'repeat={self.repeat_index + 1}/{self.repeat_count}'
            )
            self.begin_current_trial()
            return

        # Finished all LEFT repeats -> switch to RIGHT at same angle.
        if self.condition == 'STATIC_LEFT':
            self.condition = 'STATIC_RIGHT'
            self.repeat_index = 0
            self.get_logger().info(
                f'LEFT COMPLETE -> RIGHT | angle={self.target_phase_deg():.1f} deg | '
                f'repeat=1/{self.repeat_count}'
            )
            self.begin_current_trial()
            return

        # Finished all RIGHT repeats -> go to next angle.
        if self.condition == 'STATIC_RIGHT':
            self.condition = 'STATIC_LEFT'
            self.repeat_index = 0
            self.angle_index += 1

            if self.angle_index >= self.angle_count:
                self.finish_experiment()
                return

            self.reset_angle_static_cache()
            self.get_logger().info(
                f'NEXT ANGLE -> {self.target_phase_deg():.1f} deg | '
                f'starting LEFT repeat=1/{self.repeat_count}'
            )
            self.begin_current_trial()
            return

        self.get_logger().error(
            f'Unexpected condition while advancing: {self.condition}'
        )
        self.finish_experiment()

    # ==========================================================
    # Finish
    # ==========================================================
    def finish_experiment(self):
        try:
            self.current_torque = 0.0
            self.publish_zero_effort()
        except Exception:
            pass
        self.raw_file.flush()
        self.summary_file.flush()
        self.test_finished = True
        self.get_logger().info('========================================')
        self.get_logger().info('EXPERIMENT COMPLETE')
        self.get_logger().info(f'Raw={self.raw_path}')
        self.get_logger().info(f'Summary={self.summary_path}')
        self.get_logger().info('========================================')

    # ==========================================================
    # Main control loop
    # ==========================================================
    def control_loop(self):
        if self.test_finished:
            return

        # ------------------------------------------------------
        # Wait feedback
        # ------------------------------------------------------
        if self.phase == 'WAIT_JOINT':
            if self.left_received and self.right_received:
                self.get_logger().info('/joint_states received.')
                self.reset_angle_static_cache()
                self.begin_current_trial()
            return

        # ------------------------------------------------------
        # Position controller switch
        # ------------------------------------------------------
        if self.phase == 'REQUEST_POSITION_MODE':
            if self.request_position_mode():
                self.set_phase('WAIT_POSITION_SWITCH')
            return

        if self.phase == 'WAIT_POSITION_SWITCH':
            result = self.switch_finished_successfully()
            if result is None:
                return
            if not result:
                self.get_logger().error('Failed to switch to POSITION mode.')
                self.finish_experiment()
                return

            # Every attempt includes a real backoff move first.
            self.resolve_backoff_targets()
            self.set_phase('MOVE_TO_BACKOFF')
            return

        # ------------------------------------------------------
        # Backoff move
        # ------------------------------------------------------
        if self.phase == 'MOVE_TO_BACKOFF':
            self.publish_position_values(
                self.resolved_left_backoff_target,
                self.resolved_right_backoff_target
            )

            backoff_left_err, backoff_right_err = self.phase_errors_to(
                self.backoff_phase_deg()
            )

            self.get_logger().info(
                f'BACKOFF | purpose={self.position_purpose} | '
                f'attempt={self.position_attempt}/{self.max_position_attempts} | '
                f'backoff={self.backoff_phase_deg():.1f} | '
                f'L={self.phase_deg(self.left_position):.2f} err={backoff_left_err:.2f} | '
                f'R={self.phase_deg(self.right_position):.2f} err={backoff_right_err:.2f}',
                throttle_duration_sec=0.5
            )

            backoff_ok = (
                backoff_left_err <= self.position_tolerance_deg
                and backoff_right_err <= self.position_tolerance_deg
            )

            if backoff_ok or self.phase_elapsed() >= self.position_backoff_timeout_sec:
                self.resolve_position_targets()
                self.settle_start_time = None
                self.set_phase('MOVE_TO_TARGET')
            return

        # ------------------------------------------------------
        # Target approach
        # ------------------------------------------------------
        if self.phase == 'MOVE_TO_TARGET':
            self.publish_position_values(
                self.resolved_left_target,
                self.resolved_right_target
            )
            self.update_target_errors()

            self.get_logger().info(
                f'MOVING | purpose={self.position_purpose} | '
                f'attempt={self.position_attempt}/{self.max_position_attempts} | '
                f'target={self.target_phase_deg():5.1f} | '
                f'Lphase={self.phase_deg(self.left_position):6.2f} '
                f'err={self.position_left_error_deg:5.2f} | '
                f'Rphase={self.phase_deg(self.right_position):6.2f} '
                f'err={self.position_right_error_deg:5.2f}',
                throttle_duration_sec=0.5
            )

            if self.positions_within_tolerance():
                if self.settle_start_time is None:
                    self.settle_start_time = self.get_clock().now()

                if self.elapsed_from(self.settle_start_time) >= self.position_settle_sec:
                    self.position_status = (
                        'WITHIN_3DEG' if self.position_attempt == 1
                        else 'WITHIN_3DEG_AFTER_RETRY'
                    )
                    self.get_logger().info(
                        f'POSITION READY | purpose={self.position_purpose} | '
                        f'attempt={self.position_attempt} | '
                        f'L={self.phase_deg(self.left_position):.2f} deg | '
                        f'R={self.phase_deg(self.right_position):.2f} deg'
                    )
                    self.continue_after_positioning()
                    return
            else:
                self.settle_start_time = None

            if self.phase_elapsed() >= self.position_attempt_timeout_sec:
                if self.position_attempt < self.max_position_attempts:
                    self.get_logger().warn(
                        f'POSITION ATTEMPT {self.position_attempt} FAILED | '
                        f'Lerr={self.position_left_error_deg:.2f} | '
                        f'Rerr={self.position_right_error_deg:.2f} | '
                        f'backoff and retry...'
                    )
                    # Already in position mode: do not switch again.
                    self.start_position_attempt(need_switch=False)
                    return

                self.accept_position_after_max_attempts('target timeout')
            return

        # ------------------------------------------------------
        # Static controller switch
        # ------------------------------------------------------
        if self.phase == 'REQUEST_STATIC_EFFORT_MODE':
            if self.request_static_effort_mode():
                self.set_phase('WAIT_STATIC_EFFORT_SWITCH')
            return

        if self.phase == 'WAIT_STATIC_EFFORT_SWITCH':
            result = self.switch_finished_successfully()
            if result is None:
                return
            if not result:
                self.get_logger().error('Failed to switch to STATIC EFFORT mode.')
                self.finish_experiment()
                return
            self.publish_zero_effort()
            self.set_phase('STATIC_RELAX_ZERO')
            return

        # ------------------------------------------------------
        # Zero relax and re-check position
        # ------------------------------------------------------
        if self.phase == 'STATIC_RELAX_ZERO':
            self.publish_zero_effort()
            if self.phase_elapsed() < self.zero_relax_sec:
                return

            if not self.positions_within_tolerance():
                if self.position_attempt < self.max_position_attempts:
                    self.get_logger().warn(
                        f'POST-RELAX DRIFT | Lerr={self.position_left_error_deg:.2f} | '
                        f'Rerr={self.position_right_error_deg:.2f} | '
                        f'backoff and retry ({self.position_attempt + 1}/'
                        f'{self.max_position_attempts})'
                    )
                    # Need to switch back from effort to position mode.
                    self.start_position_attempt(need_switch=True)
                    return

                self.position_status = 'MAX_RETRIES_ACCEPTED_AFTER_RELAX'
                self.get_logger().warn(
                    f'POST-RELAX STILL OUTSIDE +/-{self.position_tolerance_deg:.1f} deg '
                    f'AFTER {self.max_position_attempts} ATTEMPTS | '
                    f'proceeding from actual phase'
                )

            self.capture_trial_initial_position()
            self.reset_static_measurement()
            # reset_static_measurement resets fault only; preserve position metadata.
            self.get_logger().info(
                f'STATIC TEST START | angle={self.target_phase_deg():.1f} | '
                f'{self.test_wheel.upper()} | repeat={self.repeat_index + 1}/'
                f'{self.repeat_count} | actualL={self.initial_left_phase_deg:.2f} | '
                f'actualR={self.initial_right_phase_deg:.2f}'
            )
            self.set_phase('STATIC_TORQUE_RAMP')
            return

        # ------------------------------------------------------
        # Static torque ramp
        # ------------------------------------------------------
        if self.phase == 'STATIC_TORQUE_RAMP':
            if not self.check_static_safety():
                self.current_torque = 0.0
                self.publish_zero_effort()
                self.save_raw()
                self.save_static_summary()
                self.set_phase('STATIC_POST_ZERO')
                return

            # Safety check may confirm RAPID_ACCELERATION.
            if self.breakaway_detected:
                self.current_torque = 0.0
                self.publish_zero_effort()
                self.save_raw()
                self.save_static_summary()
                self.set_phase('STATIC_POST_ZERO')
                return

            if self.breakaway_candidate_active:
                # Freeze torque while candidate is being verified.
                self.publish_static_test_torque()
                self.update_breakaway_detector()
                self.save_raw()

                if self.breakaway_detected:
                    self.current_torque = 0.0
                    self.publish_zero_effort()
                    self.save_static_summary()
                    self.set_phase('STATIC_POST_ZERO')
                return

            current_mag = abs(self.current_torque)
            if current_mag < self.fast_ramp_end_torque:
                self.current_ramp_rate = self.fast_ramp_rate
                next_mag = min(
                    current_mag + self.fast_ramp_rate * self.dt,
                    self.fast_ramp_end_torque
                )
            else:
                self.current_ramp_rate = self.slow_ramp_rate
                next_mag = current_mag + self.slow_ramp_rate * self.dt

            next_mag = min(next_mag, self.max_torque)
            self.current_torque = self.direction * next_mag
            self.publish_static_test_torque()
            self.update_breakaway_detector()
            self.save_raw()

            if next_mag >= self.max_torque and not self.breakaway_candidate_active:
                self.max_torque_reached = True
                self.current_torque = 0.0
                self.publish_zero_effort()
                self.get_logger().warn(
                    f'NO STATIC BREAKAWAY up to {self.max_torque:.2f} Nm'
                )
                self.save_static_summary()
                self.set_phase('STATIC_POST_ZERO')
                return

            return

        # ------------------------------------------------------
        # Static post-zero -> next static trial
        # ------------------------------------------------------
        if self.phase == 'STATIC_POST_ZERO':
            self.current_torque = 0.0
            self.publish_zero_effort()

            if self.phase_elapsed() >= self.post_test_zero_sec:
                # Cache is kept only for later analysis; kinetic testing is disabled.
                if self.breakaway_detected and self.breakaway_command_torque is not None:
                    self.angle_static_breakaway[self.test_wheel].append(
                        abs(self.breakaway_command_torque)
                    )
                self.advance_trial()
            return

        # ------------------------------------------------------
        # Kinetic states below are retained only as unused helper code from
        # the previous version. advance_trial() never enters them.
        # ------------------------------------------------------
        # Kinetic mode switch
        # ------------------------------------------------------
        if self.phase == 'REQUEST_KINETIC_MODE':
            if self.request_kinetic_mode():
                self.set_phase('WAIT_KINETIC_SWITCH')
            return

        if self.phase == 'WAIT_KINETIC_SWITCH':
            result = self.switch_finished_successfully()
            if result is None:
                return
            if not result:
                self.get_logger().error(
                    'Failed to switch to KINETIC mode. '
                    'Check that both drive controllers are loaded inactive.'
                )
                self.finish_experiment()
                return

            self.capture_trial_initial_position()
            self.reset_kinetic_measurement()
            self.prepare_kinetic_launch()
            self.set_phase('KINETIC_LAUNCH')
            return

        # ------------------------------------------------------
        # Kinetic launch: use static-breakaway-based tau_ff briefly
        # ------------------------------------------------------
        if self.phase == 'KINETIC_LAUNCH':
            if not self.check_kinetic_safety():
                self.publish_zero_drive()
                self.save_raw()
                self.finalize_kinetic()
                self.save_kinetic_summary()
                self.set_phase('KINETIC_POST_ZERO')
                return

            self.update_launch_handover()
            self.publish_kinetic_control_command()
            self.save_raw()

            self.get_logger().info(
                f'KINETIC LAUNCH | target={self.kinetic_target_velocity:+.3f} | '
                f'vL={self.left_velocity:+.3f} tauFFL={self.current_kinetic_tau_ff()[0]:+.3f} '
                f'piL={int(self.kinetic_pi_left_active)} | '
                f'vR={self.right_velocity:+.3f} tauFFR={self.current_kinetic_tau_ff()[1]:+.3f} '
                f'piR={int(self.kinetic_pi_right_active)}',
                throttle_duration_sec=0.25
            )

            if (
                not self.kinetic_launch_left_active
                and not self.kinetic_launch_right_active
            ):
                self.get_logger().info(
                    'KINETIC LAUNCH COMPLETE -> both wheels handed over to PI tau_ff'
                )
                self.publish_kinetic_control_command()
                self.kinetic_settle_phase_start = self.get_clock().now()
                self.kinetic_settle_window_start = None
                self.set_phase('KINETIC_SETTLE')
                return

            if self.elapsed_from(self.kinetic_launch_start_time) >= self.kinetic_launch_timeout_sec:
                self.trigger_fault(
                    'KINETIC_LAUNCH_TIMEOUT',
                    f'vL={self.left_velocity:+.3f}, vR={self.right_velocity:+.3f}'
                )
                self.publish_zero_drive()
                self.finalize_kinetic()
                self.save_kinetic_summary()
                self.set_phase('KINETIC_POST_ZERO')
            return

        # ------------------------------------------------------
        # Kinetic settle after launch torque removal
        # ------------------------------------------------------
        if self.phase == 'KINETIC_SETTLE':
            if not self.check_kinetic_safety():
                self.publish_zero_drive()
                self.save_raw()
                self.finalize_kinetic()
                self.save_kinetic_summary()
                self.set_phase('KINETIC_POST_ZERO')
                return

            self.publish_kinetic_control_command()
            self.save_raw()

            left_error = self.left_velocity - self.kinetic_target_velocity
            right_error = self.right_velocity - self.kinetic_target_velocity
            speed_ok = self.kinetic_speed_ok()

            self.get_logger().info(
                f'KINETIC SETTLE | target={self.kinetic_target_velocity:+.3f} | '
                f'vL={self.left_velocity:+.3f} errL={left_error:+.3f} | '
                f'vR={self.right_velocity:+.3f} errR={right_error:+.3f} | '
                f'tauL={self.left_effort:+.3f} | tauR={self.right_effort:+.3f} | '
                f'piFFL={self.kinetic_pi_left_tau_ff:+.3f} | '
                f'piFFR={self.kinetic_pi_right_tau_ff:+.3f}',
                throttle_duration_sec=0.5
            )

            if speed_ok:
                if self.kinetic_settle_window_start is None:
                    self.kinetic_settle_window_start = self.get_clock().now()
                elif self.elapsed_from(self.kinetic_settle_window_start) >= self.kinetic_settle_sec:
                    self.get_logger().info(
                        f'KINETIC SPEED SETTLED for {self.kinetic_settle_sec:.2f}s -> sampling'
                    )
                    self.kinetic_sample_start = self.get_clock().now()
                    self.last_kinetic_feedback_seq = -1
                    self.kinetic_all_count = 0
                    self.kinetic_valid_count = 0
                    self.kinetic_left_velocity_samples = []
                    self.kinetic_right_velocity_samples = []
                    self.kinetic_left_effort_samples = []
                    self.kinetic_right_effort_samples = []
                    self.set_phase('KINETIC_SAMPLE')
                    return
            else:
                self.kinetic_settle_window_start = None

            if self.elapsed_from(self.kinetic_settle_phase_start) >= self.kinetic_settle_timeout_sec:
                self.trigger_fault(
                    'KINETIC_SETTLING_TIMEOUT',
                    f'target={self.kinetic_target_velocity:+.3f}, '
                    f'vL={self.left_velocity:+.3f}, vR={self.right_velocity:+.3f}'
                )
                self.publish_zero_drive()
                self.finalize_kinetic()
                self.save_kinetic_summary()
                self.set_phase('KINETIC_POST_ZERO')
            return

        # ------------------------------------------------------
        # Kinetic steady-state sample
        # ------------------------------------------------------
        if self.phase == 'KINETIC_SAMPLE':
            if not self.check_kinetic_safety():
                self.publish_zero_drive()
                self.save_raw()
                self.finalize_kinetic()
                self.save_kinetic_summary()
                self.set_phase('KINETIC_POST_ZERO')
                return

            self.publish_kinetic_control_command()
            self.collect_kinetic_sample()
            self.save_raw()

            if self.elapsed_from(self.kinetic_sample_start) >= self.kinetic_sample_sec:
                self.finalize_kinetic()
                self.publish_zero_drive()
                self.save_kinetic_summary()
                self.set_phase('KINETIC_POST_ZERO')
            return

        # ------------------------------------------------------
        # Kinetic post-zero -> next kinetic repeat / next angle
        # ------------------------------------------------------
        if self.phase == 'KINETIC_POST_ZERO':
            self.publish_zero_drive()
            if self.phase_elapsed() >= self.post_test_zero_sec:
                self.advance_trial()
            return

    # ==========================================================
    # Shutdown
    # ==========================================================
    def destroy_node(self):
        try:
            self.current_torque = 0.0
            self.publish_zero_effort()
        except Exception:
            pass

        try:
            if hasattr(self, 'raw_file') and not self.raw_file.closed:
                self.raw_file.flush()
                self.raw_file.close()
            if hasattr(self, 'summary_file') and not self.summary_file.closed:
                self.summary_file.flush()
                self.summary_file.close()
        except Exception:
            pass

        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = AutomaticAngleBreakawayMapNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        if rclpy.ok():
            node.get_logger().warn('Interrupted -> commanding zero.')
            node.current_torque = 0.0
            node.publish_zero_effort()
            node.publish_zero_drive()
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()

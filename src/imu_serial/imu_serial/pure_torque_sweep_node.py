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


class PureTorqueSweepNode(Node):

    def __init__(self):

        super().__init__(
            'pure_torque_sweep_node'
        )

        # ======================================================
        # Parameters
        # ======================================================

        # +1 forward, -1 reverse
        self.declare_parameter(
            'direction',
            1
        )

        self.declare_parameter(
            'max_torque',
            13.0
        )

        self.declare_parameter(
            'ramp_up_rate',
            0.2
        )

        self.declare_parameter(
            'ramp_down_rate',
            0.2
        )

        self.declare_parameter(
            'emergency_ramp_down_rate',
            5.0
        )

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

        # Same-direction overspeed
        self.declare_parameter(
            'overspeed_threshold',
            4.0
        )

        # Opposite-direction motion -> immediate zero
        self.declare_parameter(
            'wrong_direction_velocity_threshold',
            2.0
        )

        self.declare_parameter(
            'joint_state_timeout_sec',
            0.20
        )

        # Breakaway
        self.declare_parameter(
            'breakaway_velocity_threshold',
            0.30
        )

        self.declare_parameter(
            'breakaway_required_samples',
            30
        )

        self.declare_parameter(
            'breakaway_position_change_threshold',
            0.05
        )

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

        self.dt = 1.0 / self.control_frequency

        # ======================================================
        # State
        # ======================================================

        self.phase = 'WAIT_JOINT'

        self.current_torque = 0.0

        self.test_finished = False

        self.safety_triggered = False
        self.fault_type = 'NONE'
        self.safety_reason = ''

        self.test_start_time = (
            self.get_clock().now()
        )

        self.phase_start_time = (
            self.get_clock().now()
        )

        self.last_joint_state_time = None

        # ======================================================
        # Feedback
        # ======================================================

        self.left_position = 0.0
        self.right_position = 0.0

        self.left_velocity = 0.0
        self.right_velocity = 0.0

        self.left_effort = 0.0
        self.right_effort = 0.0

        self.left_received = False
        self.right_received = False

        # ======================================================
        # Breakaway
        # ======================================================

        self.left_count = 0
        self.right_count = 0

        self.left_start_position = None
        self.right_start_position = None

        self.left_breakaway = False
        self.right_breakaway = False

        self.left_breakaway_torque = None
        self.right_breakaway_torque = None

        self.left_breakaway_velocity = None
        self.right_breakaway_velocity = None

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
            f'pure_torque_sweep_'
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

        self.writer = csv.writer(
            self.raw_file
        )

        self.writer.writerow([

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

            'left_breakaway',
            'right_breakaway',

            'safety_triggered',
            'fault_type',
        ])

        # ======================================================
        # ROS
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

        self.get_logger().info(
            '========================================'
        )

        self.get_logger().info(
            'PURE EFFORT-ONLY TORQUE SWEEP'
        )

        self.get_logger().info(
            f'Direction = {direction_name}'
        )

        self.get_logger().info(
            f'Max torque = {self.max_torque:.2f} Nm'
        )

        self.get_logger().info(
            'Expected hardware mode: CURRENT_LOOP'
        )

        self.get_logger().info(
            'Expected MIT command: '
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


    def set_phase(self, phase):

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
    # Feedback
    # ==========================================================

    def joint_callback(self, msg):

        self.last_joint_state_time = (
            self.get_clock().now()
        )

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

    def publish_torque(self, torque):

        msg_left = Float64MultiArray()
        msg_left.data = [float(torque)]

        msg_right = Float64MultiArray()
        msg_right.data = [float(torque)]

        self.left_pub.publish(
            msg_left
        )

        self.right_pub.publish(
            msg_right
        )


    def send_zero(self):

        for _ in range(10):
            self.publish_torque(0.0)


    # ==========================================================
    # Logging
    # ==========================================================

    def save_row(self):

        self.writer.writerow([

            self.get_clock().now().nanoseconds
            * 1e-9,

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

            int(self.left_breakaway),
            int(self.right_breakaway),

            int(self.safety_triggered),
            self.fault_type,
        ])


    # ==========================================================
    # Breakaway
    # ==========================================================

    def update_breakaway(self):

        left_dv = (
            self.direction
            *
            self.left_velocity
        )

        right_dv = (
            self.direction
            *
            self.right_velocity
        )

        # LEFT
        if not self.left_breakaway:

            if left_dv > self.breakaway_velocity_threshold:

                if self.left_count == 0:
                    self.left_start_position = (
                        self.left_position
                    )

                self.left_count += 1

            else:

                self.left_count = 0
                self.left_start_position = None

            if (
                self.left_count
                >=
                self.breakaway_required_samples
                and
                self.left_start_position is not None
            ):

                delta = (
                    self.direction
                    *
                    (
                        self.left_position
                        -
                        self.left_start_position
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

                    self.left_breakaway_velocity = (
                        self.left_velocity
                    )

                    self.get_logger().info(
                        f'LEFT BREAKAWAY | '
                        f'tau={self.current_torque:+.3f} Nm | '
                        f'v={self.left_velocity:+.3f} rad/s | '
                        f'dtheta={delta:+.4f} rad'
                    )

        # RIGHT
        if not self.right_breakaway:

            if right_dv > self.breakaway_velocity_threshold:

                if self.right_count == 0:
                    self.right_start_position = (
                        self.right_position
                    )

                self.right_count += 1

            else:

                self.right_count = 0
                self.right_start_position = None

            if (
                self.right_count
                >=
                self.breakaway_required_samples
                and
                self.right_start_position is not None
            ):

                delta = (
                    self.direction
                    *
                    (
                        self.right_position
                        -
                        self.right_start_position
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

                    self.right_breakaway_velocity = (
                        self.right_velocity
                    )

                    self.get_logger().info(
                        f'RIGHT BREAKAWAY | '
                        f'tau={self.current_torque:+.3f} Nm | '
                        f'v={self.right_velocity:+.3f} rad/s | '
                        f'dtheta={delta:+.4f} rad'
                    )


    # ==========================================================
    # Immediate stop
    # ==========================================================

    def immediate_stop(
        self,
        fault_type,
        reason
    ):

        self.safety_triggered = True

        self.fault_type = fault_type
        self.safety_reason = reason

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
            'Commanding 0 Nm.'
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


    # ==========================================================
    # Safety
    # ==========================================================

    def check_safety(self):

        if (
            self.joint_state_age()
            >
            self.joint_state_timeout_sec
        ):

            self.immediate_stop(
                'FEEDBACK_TIMEOUT',
                'joint_states timeout'
            )

            return False

        left_directional = (
            self.direction
            *
            self.left_velocity
        )

        right_directional = (
            self.direction
            *
            self.right_velocity
        )

        # Opposite direction
        if (
            left_directional
            <
            -self.wrong_direction_velocity_threshold
            or
            right_directional
            <
            -self.wrong_direction_velocity_threshold
        ):

            self.immediate_stop(

                'WRONG_DIRECTION',

                f'Wrong direction: '
                f'L={self.left_velocity:+.3f}, '
                f'R={self.right_velocity:+.3f}'
            )

            return False

        # Normal overspeed -> immediate zero for first validation.
        #
        # 나중에 정상임이 확인되면 ramp-down으로 변경 가능.
        if (
            abs(self.left_velocity)
            >
            self.overspeed_threshold
            or
            abs(self.right_velocity)
            >
            self.overspeed_threshold
        ):

            self.immediate_stop(

                'OVERSPEED',

                f'Overspeed: '
                f'L={self.left_velocity:+.3f}, '
                f'R={self.right_velocity:+.3f}'
            )

            return False

        return True


    # ==========================================================
    # Finish
    # ==========================================================

    def finish(self):

        self.current_torque = 0.0

        self.send_zero()

        self.raw_file.flush()

        summary = {

            'direction':
                self.direction,

            'left_breakaway':
                self.left_breakaway,

            'left_breakaway_torque_nm':
                self.left_breakaway_torque,

            'left_breakaway_velocity_rad_s':
                self.left_breakaway_velocity,

            'right_breakaway':
                self.right_breakaway,

            'right_breakaway_torque_nm':
                self.right_breakaway_torque,

            'right_breakaway_velocity_rad_s':
                self.right_breakaway_velocity,

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

        self.test_finished = True

        self.get_logger().info(
            '========================================'
        )

        self.get_logger().info(
            'PURE TORQUE TEST COMPLETE'
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
            f'Fault = {self.fault_type}'
        )

        self.get_logger().info(
            f'Raw = {self.raw_path}'
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

        # WAIT
        if self.phase == 'WAIT_JOINT':

            self.publish_torque(0.0)

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

        # ZERO BEFORE
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

                self.set_phase(
                    'RAMP_UP'
                )

                self.get_logger().info(
                    'RAMP_UP started.'
                )

            return

        # Safety during active torque
        if self.phase in [
            'RAMP_UP',
            'PEAK_HOLD',
            'RAMP_DOWN'
        ]:

            if not self.check_safety():
                return

        # RAMP UP
        if self.phase == 'RAMP_UP':

            magnitude = (
                abs(self.current_torque)
                +
                self.ramp_up_rate
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

            self.get_logger().info(
                f'RAMP_UP | '
                f'tau={self.current_torque:+6.2f} | '
                f'L v={self.left_velocity:+6.3f} '
                f'eff={self.left_effort:+6.2f} | '
                f'R v={self.right_velocity:+6.3f} '
                f'eff={self.right_effort:+6.2f}',
                throttle_duration_sec=0.5
            )

            if (
                magnitude
                >=
                self.max_torque
            ):

                self.set_phase(
                    'PEAK_HOLD'
                )

            return

        # PEAK HOLD
        if self.phase == 'PEAK_HOLD':

            self.publish_torque(
                self.current_torque
            )

            self.save_row()

            if (
                self.phase_elapsed()
                >=
                self.peak_hold_sec
            ):

                self.set_phase(
                    'RAMP_DOWN'
                )

                self.get_logger().info(
                    'RAMP_DOWN started.'
                )

            return

        # RAMP DOWN
        if self.phase == 'RAMP_DOWN':

            magnitude = max(
                0.0,
                abs(self.current_torque)
                -
                self.ramp_down_rate
                *
                self.dt
            )

            self.current_torque = (
                self.direction
                *
                magnitude
            )

            self.publish_torque(
                self.current_torque
            )

            self.save_row()

            self.get_logger().info(
                f'RAMP_DOWN | '
                f'tau={self.current_torque:+6.2f} | '
                f'L v={self.left_velocity:+6.3f} '
                f'eff={self.left_effort:+6.2f} | '
                f'R v={self.right_velocity:+6.3f} '
                f'eff={self.right_effort:+6.2f}',
                throttle_duration_sec=0.5
            )

            if magnitude <= 0.0:

                self.set_phase(
                    'ZERO_AFTER'
                )

            return

        # ZERO AFTER
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


    def destroy_node(self):

        try:

            if (
                hasattr(self, 'raw_file')
                and
                not self.raw_file.closed
            ):

                self.raw_file.flush()
                self.raw_file.close()

        except Exception:
            pass

        super().destroy_node()


def main(args=None):

    rclpy.init(args=args)

    node = PureTorqueSweepNode()

    try:

        rclpy.spin(node)

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

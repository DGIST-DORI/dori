"""Dedicated AK45-36 Servo bridge; starts in receive-only state."""

import socket
import struct
import time

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool, Float64, Int32
from dori_msgs.msg import SystemError

from dori_hardware.cubemars_servo import EFF, RTR, FRAME, Motor4Guard, ServoProtocol


class Motor4ServoNode(Node):
    def __init__(self):
        super().__init__("motor4_servo_node")
        defaults = dict(can_interface="can1", can_id=4, pole_pairs=14, gear_ratio=36.0,
                        minimum_deg=-182.0, maximum_deg=2.0, speed_deg_s=10.0,
                        acceleration_deg_s2=20.0, feedback_timeout_sec=0.25,
                        command_timeout_sec=0.35, read_only=False)
        p = {name: self.declare_parameter(name, value).value for name, value in defaults.items()}
        if p["can_id"] != 4:
            raise ValueError("This bridge is dedicated to motor 4; refusing another CAN ID")
        self.protocol = ServoProtocol(p["can_id"], p["pole_pairs"], p["gear_ratio"])
        self.guard = Motor4Guard(p["minimum_deg"], p["maximum_deg"],
                                 p["feedback_timeout_sec"], p["command_timeout_sec"])
        self.speed = p["speed_deg_s"]
        self.acceleration = p["acceleration_deg_s2"]
        self.protocol.position(0, self.speed, self.acceleration)  # Validate before opening CAN.
        self.read_only = p["read_only"]
        self.last_target = None
        self.last_can_command_at = None
        self.stop_pending = False
        self.stop_attempts = 0
        self.error_reported = False
        self.bus = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        # Accept only ID 4 Servo data frames. CAN_ERR_FLAG must NOT be in this
        # mask: Linux would register an error-frame filter instead. Error
        # reception is disabled by default (CAN_RAW_ERR_FILTER == 0).
        self.bus.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER,
                            struct.pack("=II", EFF | 0x2904, EFF | RTR | 0x1FFFFFFF))
        self.bus.bind((p["can_interface"],))
        self.bus.setblocking(False)
        self.joints = self.create_publisher(JointState, "/motor4/joint_states", 10)
        self.errors = self.create_publisher(SystemError, "/system/error", 10)
        self.create_subscription(Float64, "/motor4/position_cmd", self.command, 1)
        self.create_subscription(Bool, "/motor4/stop", self.stop_callback, 1)
        self.create_subscription(Int32, "/system/action_state", self.action,
                                 QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_timer(0.01, self.poll)
        self.get_logger().info("AK45-36 CAN ID 4 Servo bridge: awaiting fresh feedback; no startup motion")

    def report_error(self, reason):
        self.guard.faulted = True
        if self.error_reported:
            return
        self.error_reported = True
        msg = SystemError()
        msg.source_node = self.get_name()
        msg.error_code = 412
        msg.description = reason
        self.errors.publish(msg)
        self.get_logger().error(reason)

    def send(self, frame):
        if self.read_only:
            return False
        try:
            if self.bus.send(frame) != len(frame):
                raise OSError("Short CAN write")
            return True
        except OSError as error:
            self.report_error(f"Motor4 CAN write failed: {error}")
            return False

    def stop(self):
        if not self.guard.owned and not self.stop_pending:
            return
        self.stop_pending = True
        self.stop_attempts += 1
        self.guard.owned = False
        self.last_target = None
        self.last_can_command_at = None
        if self.send(self.protocol.stop()):
            self.stop_pending = False
            self.stop_attempts = 0

    def stop_callback(self, msg):
        if msg.data:
            self.stop()

    def action(self, msg):
        self.guard.action_state = msg.data
        if msg.data != 2:
            self.stop()

    def command(self, msg):
        if self.read_only:
            return
        now = time.monotonic()
        if self.stop_pending or not self.guard.accept(msg.data, now):
            self.stop()
            self.report_error("Motor4 goal rejected: state, feedback, fault or angle limits")
            return
        # Refresh unchanged goals on CAN too; updating only the ROS watchdog
        # can let the actuator's own communications timeout release torque.
        if (self.guard.owned and self.last_target == msg.data and
                self.last_can_command_at is not None and now - self.last_can_command_at < 0.05):
            return
        if self.send(self.protocol.position(msg.data, self.speed, self.acceleration)):
            self.guard.owned = True
            self.last_target = msg.data
            self.last_can_command_at = now

    def poll(self):
        for _ in range(200):
            try:
                packet, _, flags, _ = self.bus.recvmsg(FRAME.size)
            except BlockingIOError:
                break
            except OSError as error:
                self.report_error(f"Motor4 CAN read failed: {error}")
                break
            if len(packet) != FRAME.size or flags & socket.MSG_DONTROUTE:
                continue
            can_id, length, payload = FRAME.unpack(packet)
            state = self.protocol.feedback(can_id, payload[:length])
            if state is None:
                continue
            self.guard.state = state
            self.guard.feedback_at = time.monotonic()
            if state.error:
                self.report_error(f"Motor4 reported Servo error {state.error}")
                continue  # Never publish faulted feedback as a valid pose.
            msg = JointState()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.name = ["motor_4_joint"]
            from math import radians
            msg.position = [radians(state.position_deg)]
            msg.velocity = [state.velocity_rad_s]
            self.joints.publish(msg)
        if self.guard.needs_stop(time.monotonic()):
            self.stop()
            self.report_error("Motor4 stopped: state changed, feedback expired or controller heartbeat lost")
        if self.stop_pending and self.stop_attempts < 5:
            self.stop()

    def close(self):
        self.stop()
        self.bus.close()


def main(args=None):
    rclpy.init(args=args)
    node = Motor4ServoNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    except RuntimeError:
        # Context shutdown can race a callback or take_message in Humble.
        if rclpy.ok():
            raise
    finally:
        node.close()
        node.destroy_node()
        rclpy.try_shutdown()

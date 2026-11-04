#!/usr/bin/env python3
"""Exercise both transform nodes with synthetic joints on an isolated ROS domain.

Launches no hardware driver, CAN socket, DXL bridge or robot input node.
Requires sourcing ros2_ws/install/local_setup.bash and ROS_DOMAIN_ID=86.
"""

import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from sensor_msgs.msg import JointState
from std_msgs.msg import Float64, Float64MultiArray, Int32
from dori_msgs.msg import TransformStep
import yaml

ROOT = Path(__file__).resolve().parents[2]


class Simulation(Node):
    def __init__(self, params):
        super().__init__("motor4_transform_simulation")
        self.reference = [params["left_bldc_alignment_offset_deg"],
                          params["right_bldc_alignment_offset_deg"],
                          params["motor3_grid_offset_deg"], params["motor4_a_reference_deg"]]
        self.position = list(self.reference)
        self.steps, self.motor4_goals, self.dxl_goals = [], [], []
        self.status = 0
        self.action = self.create_publisher(Int32, "/system/action_state",
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.request = self.create_publisher(Int32, "/transform/request", 10)
        self.wheels = self.create_publisher(JointState, "/joint_states", 10)
        self.dxl = self.create_publisher(JointState, "/dxl_joint_states", 10)
        self.motor4 = self.create_publisher(JointState, "/motor4/joint_states", 10)
        self.create_subscription(TransformStep, "/transform/step_cmd", self.step, 10)
        self.create_subscription(Float64, "/motor4/position_cmd", self.motor4_goal, 10)
        self.create_subscription(Float64MultiArray, "/dxl_position_cmd", self.dxl_goal, 10)
        self.create_subscription(Int32, "/transform/status", self.state, 10)
        self.create_timer(0.01, self.feedback)

    def step(self, msg):
        self.steps.append((msg.motor_id, msg.motor_type, msg.target_angle_deg))
        # Wheel dynamics are outside this routing/sequence test.
        if msg.motor_id in (1, 2):
            self.position[msg.motor_id - 1] = msg.target_angle_deg

    def motor4_goal(self, msg):
        self.motor4_goals.append(msg.data)
        self.position[3] = msg.data

    def dxl_goal(self, msg):
        self.dxl_goals.append(tuple(msg.data))
        if int(msg.data[0]) == 3:
            self.position[2] = msg.data[1]

    def state(self, msg):
        self.status = msg.data

    def feedback(self):
        for publisher, names, indices in (
            (self.wheels, ["left_wheel_joint", "right_wheel_joint"], [0, 1]),
            (self.dxl, ["motor_3_joint"], [2]),
            (self.motor4, ["motor_4_joint"], [3]),
        ):
            msg = JointState()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.name = names
            msg.position = [math.radians(self.position[i]) for i in indices]
            msg.velocity = [0.0] * len(indices)
            publisher.publish(msg)

    def spin_until(self, predicate, timeout=15):
        deadline = time.monotonic() + timeout
        while not predicate():
            assert time.monotonic() < deadline, (self.status, self.steps)
            rclpy.spin_once(self, timeout_sec=0.01)


def main():
    assert os.environ.get("ROS_DOMAIN_ID") == "86", "Use isolated ROS_DOMAIN_ID=86"
    config = ROOT / "ros2_ws/src/dori_control/config/transform_params.yaml"
    params = yaml.safe_load(config.read_text())["transform_manager_node"]["ros__parameters"]
    processes, logs = [], []
    rclpy.init()
    simulation = Simulation(params)
    try:
        for executable, overrides in (
            ("transform_manager_node", ["-p", "initial_step_delay_sec:=0.05"]),
            ("transform_controller_node", ["-p", "settle_time_sec:=0.03"]),
        ):
            log = tempfile.TemporaryFile(mode="w+")
            logs.append(log)
            processes.append(subprocess.Popen([
                str(ROOT / "ros2_ws/install/dori_control/lib/dori_control" / executable),
                "--ros-args", "--params-file", str(config), *overrides], stdout=log, stderr=log))
        simulation.spin_until(lambda: simulation.request.get_subscription_count() == 1 and
                              simulation.action.get_subscription_count() == 1)
        simulation.action.publish(Int32(data=2))
        ready_at = time.monotonic() + 0.5
        simulation.spin_until(lambda: time.monotonic() >= ready_at)
        for request, expected in ((2, -180.0), (1, 0.0)):
            simulation.steps.clear()
            simulation.status = 0
            simulation.request.publish(Int32(data=request))
            simulation.spin_until(lambda: simulation.status in (3, 4))
            assert simulation.status == 3, simulation.steps
            assert len(simulation.steps) == 19, simulation.steps
            assert all(kind == 3 for motor, kind, _ in simulation.steps if motor == 4)
            assert abs(simulation.position[3] - expected) < 1e-6
            assert all(int(goal[0]) == 3 for goal in simulation.dxl_goals)
        assert simulation.motor4_goals
        assert all(abs(a - b) < 1e-6 for a, b in zip(simulation.position, simulation.reference))
        simulation.action.publish(Int32(data=0))
        print("PASS: A->B->A, 19 steps each, motor4 Servo routing, no motor4 DXL commands, exact endpoints")
    except BaseException:
        for log in logs:
            log.seek(0)
            print(log.read()[-6000:])
        raise
    finally:
        for process in processes:
            process.send_signal(signal.SIGINT)
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for log in logs:
            log.close()
        simulation.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Software-only transform regression. Never starts a hardware driver.
Run with ROS_DOMAIN_ID=93 ROS_LOCALHOST_ONLY=1 after sourcing install/setup.bash.
"""
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time

if os.environ.get('ROS_DOMAIN_ID') != '93' or os.environ.get('ROS_LOCALHOST_ONLY') != '1':
    raise RuntimeError('Requires isolated ROS_DOMAIN_ID=93 ROS_LOCALHOST_ONLY=1')

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Int32, Bool, Float64MultiArray
from robot_msgs.msg import TransformStep, TransformStepResult, CommandFeedback, MitCommand
from dynamixel_sdk_custom_interfaces.srv import GetPosition
from dynamixel_sdk_custom_interfaces.msg import SetPosition

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / 'install/robot_transform/lib/robot_transform'
PARAMS = ROOT / 'src/robot_transform/config/transform_params.yaml'


class Harness:
    def __init__(self):
        self.node = Node('transform_regression')
        self.procs = []
        self.logs = []
        self.tmp = tempfile.TemporaryDirectory(prefix='transform_regression_')
        self.current = [36.51, -43.1659, -6.77, 8.88]
        self.velocity = [0.0] * 4
        self.feed = True
        self.excluded = set()
        self.bldc = self.node.create_publisher(JointState, '/joint_states', 20)
        self.dxl = self.node.create_publisher(JointState, '/dxl_joint_states', 20)
        self.timer = self.node.create_timer(0.02, self.pump)

    def pump(self):
        if not self.feed:
            return
        names = ['left_wheel_joint', 'right_wheel_joint', 'motor_3_joint', 'motor_4_joint']
        for indices, pub in [([0, 1], self.bldc), ([2, 3], self.dxl)]:
            m = JointState()
            m.header.stamp = self.node.get_clock().now().to_msg()
            for i in indices:
                if i in self.excluded:
                    continue
                m.name.append(names[i])
                m.position.append(math.radians(self.current[i]))
                m.velocity.append(self.velocity[i])
            pub.publish(m)

    def spin(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rclpy.spin_once(self.node, timeout_sec=0.01)
            for p in self.procs:
                if p.poll() is not None:
                    raise AssertionError('Child exited: ' + '\n'.join(Path(f.name).read_text() for f in self.logs))

    def wait(self, predicate, label, timeout=5):
        end = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= end:
                raise AssertionError(label + '\n' + '\n'.join(Path(f.name).read_text()[-4000:] for f in self.logs))
            self.spin(0.02)

    def start(self, executable, *args):
        log = open(Path(self.tmp.name) / (executable + str(len(self.procs)) + '.log'), 'w+')
        self.logs.append(log)
        p = subprocess.Popen([str(BIN / executable), '--ros-args', *args],
                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        self.procs.append(p)
        self.spin(1.0)

    def stop(self):
        for p in self.procs:
            p.send_signal(signal.SIGINT)
        for p in self.procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        self.procs.clear()

    def close(self):
        self.stop()
        self.node.destroy_node()
        for log in self.logs:
            log.close()
        self.tmp.cleanup()


def manager_test():
    h = Harness()
    try:
        steps, statuses, feedback = [], [], []
        h.node.create_subscription(TransformStep, '/transform/step_cmd', steps.append, 20)
        h.node.create_subscription(Int32, '/transform/status', lambda m: statuses.append(m.data), 20)
        h.node.create_subscription(CommandFeedback, '/transform/command_feedback', feedback.append, 20)
        request = h.node.create_publisher(Int32, '/transform/request', 20)
        result = h.node.create_publisher(TransformStepResult, '/transform/step_result', 20)
        pause = h.node.create_publisher(Bool, '/transform/pause', 20)
        resume = h.node.create_publisher(Bool, '/transform/resume', 20)
        h.start('transform_manager_node', '--params-file', str(PARAMS), '-p', 'initial_step_delay_sec:=0.05')
        cycle_steps = []
        for cycle, target_pose in enumerate([2, 1, 2, 1]):
            steps.clear()
            statuses.clear()
            request.publish(Int32(data=target_pose))
            recorded = []
            for i in range(19):
                h.wait(lambda: len(steps) > i, f'missing cycle {cycle} step {i}')
                step = steps[i]
                recorded.append((step.motor_id, step.target_angle_deg))
                # Measured endpoint error must not redefine the next target.
                h.current[step.motor_id - 1] = step.target_angle_deg + 1.0
                h.spin(0.08)
                if cycle == 0 and i == 4:
                    pause.publish(Bool(data=True))
                    h.wait(lambda: statuses[-1] == 2, 'manager pause')
                    # A result arriving during pause must not be discarded/replayed.
                    result.publish(TransformStepResult(motor_id=step.motor_id, success=True))
                    h.spin(0.1)
                    assert len(steps) == i + 1
                    resume.publish(Bool(data=True))
                else:
                    result.publish(TransformStepResult(motor_id=step.motor_id, success=True))
            h.wait(lambda: statuses and statuses[-1] == 3, 'final pose confirmation')
            assert len(steps) == 19
            cycle_steps.append(recorded)
        for first, second in [(cycle_steps[0], cycle_steps[2]), (cycle_steps[1], cycle_steps[3])]:
            assert all(a[0] == b[0] and abs(a[1] - b[1]) < 1e-8 for a, b in zip(first, second))
        # motor4, not motor3, decides pose. Missing motor3 still blocks preparation.
        h.excluded = {2}
        h.spin(0.6)
        before = len(steps)
        feedback.clear()
        request.publish(Int32(data=2))
        h.wait(lambda: feedback, 'missing feedback rejection')
        assert not feedback[-1].accepted and len(steps) == before
        assert 'motor 3' in feedback[-1].message
        h.excluded.clear()
        h.spin(0.1)
        steps.clear()
        request.publish(Int32(data=2))
        # A fabricated last-step success cannot certify a wrong physical pose.
        for i in range(19):
            h.wait(lambda: len(steps) > i, 'wrong-pose test step')
            step = steps[i]
            h.current[step.motor_id - 1] = step.target_angle_deg
            if i == 18:
                h.current[3] = 8.88  # stays A while B was requested
            h.spin(0.04)
            result.publish(TransformStepResult(motor_id=step.motor_id, success=True))
        h.wait(lambda: statuses[-1] == 4, 'wrong final pose must fail')
        print('PASS manager: fixed A/B cycles, error drift, pause/result race, missing feedback, final motor4 check', flush=True)
    finally:
        h.close()


def controller_test():
    h = Harness()
    try:
        results, commands, stops, speeds = [], [], [], []
        h.node.create_subscription(TransformStepResult, '/transform/step_result', results.append, 20)
        h.node.create_subscription(Float64MultiArray, '/dxl_position_cmd', commands.append, 20)
        h.node.create_subscription(Int32, '/dxl_stop_cmd', stops.append, 20)
        h.node.create_subscription(MitCommand, '/bldc_mit_speed_cmd', speeds.append, 100)
        pub = h.node.create_publisher(TransformStep, '/transform/step_cmd', 20)
        pause = h.node.create_publisher(Bool, '/transform/pause', 20)
        resume = h.node.create_publisher(Bool, '/transform/resume', 20)
        h.start('transform_controller_node', '--params-file', str(PARAMS))
        def send(motor, target, timeout=3.0):
            pub.publish(TransformStep(motor_id=motor, motor_type=1 if motor < 3 else 2,
                                      target_angle_deg=float(target), timeout_sec=timeout))
        # A pause received just before the step must also latch and inhibit motion.
        pause.publish(Bool(data=True))
        h.spin(0.08)
        send(3, -72)
        h.spin(0.12)
        assert not commands
        resume.publish(Bool(data=True))
        h.wait(lambda: commands, 'DXL negative command')
        assert list(commands[-1].data) == [3.0, -72.0]
        h.current[2] = 288  # same orientation, wrong continuous turn
        h.spin(0.35)
        assert not results
        pause.publish(Bool(data=True))
        h.wait(lambda: stops, 'DXL pause must issue bus hold')
        resume.publish(Bool(data=True))
        h.wait(lambda: len(commands) == 2, 'resume original DXL target')
        assert list(commands[-1].data) == [3.0, -72.0]
        h.current[2] = -72
        h.spin(0.4)
        assert results[-1].success
        results.clear()
        stops.clear()
        send(4, -90)
        h.wait(lambda: len(commands) == 3, 'second DXL command')
        h.excluded = {3}
        h.wait(lambda: results, 'expired DXL feedback failure')
        assert not results[-1].success
        h.wait(lambda: stops, 'expired feedback must hold DXL')
        h.excluded.clear()
        h.spin(0.1)
        results.clear()
        # BLDC command loss stops both speed channels.
        send(1, 216.51)
        h.wait(lambda: any(abs(m.v_des) > 0 for m in speeds), 'BLDC starts velocity control')
        h.excluded = {0}
        h.wait(lambda: results, 'BLDC stale feedback')
        assert not results[-1].success
        h.spin(0.08)
        last = {m.motor_id: m for m in speeds}
        assert last[1].v_des == 0 and last[2].v_des == 0
        assert last[1].tau_ff == 0 and last[2].tau_ff == 0
        results.clear()
        send(1, 400)
        h.wait(lambda: results, 'reject a new step with stale feedback')
        assert not results[-1].success
        h.excluded.clear()
        h.spin(0.1)
        results.clear()
        stops.clear()
        send(4, -90, timeout=0.15)
        h.wait(lambda: results, 'DXL timeout')
        assert results[-1].timeout and not results[-1].success
        h.wait(lambda: stops, 'DXL timeout must hold')
        print('PASS controller: signed DXL target, turn mismatch, pause races/resume, stale feedback/BLDC stop, timeout', flush=True)
    finally:
        h.close()


def dxl_io_test():
    h = Harness()
    try:
        h.feed = False
        seen, raw_commands, bus_stops = [], [], []
        failed = set()
        def read(req, res):
            res.success = req.id not in failed
            res.position = {1: -4096, 2: 1024, 3: 2048}[req.id]
            return res
        h.node.create_service(GetPosition, '/get_position', read)
        h.node.create_subscription(JointState, '/dxl_joint_states', seen.append, 50)
        h.node.create_subscription(SetPosition, '/set_position', raw_commands.append, 20)
        h.node.create_subscription(SetPosition, '/stop_position', bus_stops.append, 20)
        cmd = h.node.create_publisher(Float64MultiArray, '/dxl_position_cmd', 20)
        stop = h.node.create_publisher(Int32, '/dxl_stop_cmd', 20)
        h.start('dxl_state_publisher_node')
        h.start('dxl_bridge_node')
        h.wait(lambda: {'motor_3_joint', 'motor_4_joint', 'motor_5_joint'} <= {m.name[0] for m in seen}, 'all DXL feedback')
        last = {m.name[0]: m for m in seen}
        assert abs(last['motor_3_joint'].position[0] + 2 * math.pi) < 1e-8
        assert last['motor_3_joint'].velocity[0] == 0
        failed.add(1)
        h.spin(0.15)
        seen.clear()
        h.spin(0.3)
        assert seen and all(m.name[0] != 'motor_3_joint' for m in seen)
        cmd.publish(Float64MultiArray(data=[3.0, -90.0]))
        h.wait(lambda: raw_commands, 'signed raw goal')
        assert raw_commands[-1].id == 1 and raw_commands[-1].position == -1024
        cmd.publish(Float64MultiArray(data=[5.0, -90.0]))
        cmd.publish(Float64MultiArray(data=[3.0, float('nan')]))
        h.spin(0.15)
        assert len(raw_commands) == 1
        stop.publish(Int32(data=4))
        h.wait(lambda: bus_stops, 'logical stop mapping')
        assert bus_stops[-1].id == 2
        print('PASS DXL I/O: all IDs, signed counts, no stale republishing, range rejection, stop mapping', flush=True)
    finally:
        h.close()


if __name__ == '__main__':
    rclpy.init()
    try:
        manager_test()
        controller_test()
        dxl_io_test()
    finally:
        rclpy.shutdown()

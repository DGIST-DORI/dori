#!/usr/bin/env python3
"""Capture stable real feedback and store it as the fixed A calibration; no motion commands."""
import collections
import json
import math
from pathlib import Path
import re
import statistics
import time
from datetime import datetime
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from control_msgs.msg import DynamicJointState
from rcl_interfaces.srv import SetParametersAtomically
from rcl_interfaces.msg import Parameter, ParameterValue, ParameterType

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['left_wheel_joint', 'right_wheel_joint', 'motor_3_joint', 'motor_4_joint']

def main():
    rclpy.init()
    n = Node('capture_transform_reference')
    history = {name: collections.deque() for name in NAMES}
    hardware_age = {}
    def sample(msg):
        now = time.monotonic()
        ros_age = (n.get_clock().now().nanoseconds - (msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec)) / 1e9
        if not 0 <= ros_age <= 0.3: return
        for i, name in enumerate(msg.name):
            if name not in history or i >= len(msg.position) or i >= len(msg.velocity): continue
            p, v = msg.position[i], msg.velocity[i]
            if not math.isfinite(p) or not math.isfinite(v): continue
            history[name].append((now, math.degrees(p), v))
            while history[name] and now - history[name][0][0] > 2.0: history[name].popleft()
    def dynamic(msg):
        for name, values in zip(msg.joint_names, msg.interface_values):
            if 'feedback_age' in values.interface_names:
                hardware_age[name] = (time.monotonic(), values.values[values.interface_names.index('feedback_age')])
    n.create_subscription(JointState, '/joint_states', sample, 100)
    n.create_subscription(JointState, '/dxl_joint_states', sample, 100)
    n.create_subscription(DynamicJointState, '/dynamic_joint_states', dynamic, 20)
    end = time.monotonic() + 15
    calibrated = None
    while time.monotonic() < end:
        rclpy.spin_once(n, timeout_sec=0.02)
        now = time.monotonic()
        stable = True
        for name in NAMES:
            rows = history[name]
            stable &= len(rows) >= 10 and now - rows[-1][0] <= 0.3 if rows else False
            if rows:
                stable &= rows[-1][0] - rows[0][0] >= 1.5
                stable &= max(x[1] for x in rows) - min(x[1] for x in rows) <= 0.2
                stable &= abs(statistics.median(x[2] for x in rows)) <= 0.1
        for name in NAMES[:2]:
            stamp, age = hardware_age.get(name, (0, float('inf')))
            stable &= now - stamp < 0.3 and math.isfinite(age) and 0 <= age < 0.2
        if stable:
            calibrated = {name: statistics.median(x[1] for x in history[name]) for name in NAMES}
            break
    if calibrated is None:
        print(json.dumps({'error':'No stable, fresh feedback; calibration unchanged', 'last':{k:list(v)[-1:] for k,v in history.items()}, 'hardware_age':hardware_age, 'stability':{k:{'count':len(v), 'duration':v[-1][0]-v[0][0], 'range_deg':max(x[1] for x in v)-min(x[1] for x in v), 'max_abs_velocity':max(abs(x[2]) for x in v)} for k,v in history.items() if v}}, indent=2), flush=True)
        raise SystemExit(1)
    values = dict(zip(['left_bldc_alignment_offset_deg', 'right_bldc_alignment_offset_deg', 'motor3_grid_offset_deg', 'motor4_a_reference_deg'], [calibrated[k] for k in NAMES]))
    values['pose_a_reference_deg'] = calibrated['motor_4_joint'] % 360
    values['pose_b_reference_deg'] = (calibrated['motor_4_joint'] - 540) % 360
    client = n.create_client(SetParametersAtomically, '/transform_manager_node/set_parameters_atomically')
    if not client.wait_for_service(timeout_sec=3): raise RuntimeError('No manager parameter service')
    req = SetParametersAtomically.Request()
    req.parameters = [Parameter(name=k, value=ParameterValue(type=ParameterType.PARAMETER_DOUBLE, double_value=float(v))) for k,v in values.items()]
    future = client.call_async(req)
    rclpy.spin_until_future_complete(n, future, timeout_sec=3)
    if not future.done() or not future.result().result.successful: raise RuntimeError('Calibration update rejected')
    path = ROOT / 'src/robot_transform/config/transform_params.yaml'
    original = path.read_text()
    updated = original
    for key, value in values.items():
        updated, count = re.subn(r'(?m)^(    ' + re.escape(key) + r':) .+$', lambda m: m[1] + f' {value:.9f}', updated)
        if count != 1: raise RuntimeError('Configuration key not unique: ' + key)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    (ROOT / 'backups' / f'transform_params_before_live_{stamp}.yaml').write_text(original)
    tmp = path.with_suffix('.yaml.tmp')
    tmp.write_text(updated)
    tmp.replace(path)
    report = {'time':datetime.now().astimezone().isoformat(), 'pose':'A (confirmed by user)', 'feedback_deg':calibrated, 'parameters':values}
    (ROOT / 'log' / f'transform_A_reference_{stamp}.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2), flush=True)
    n.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__': main()

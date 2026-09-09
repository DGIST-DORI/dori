#!/usr/bin/env python3
"""One supervised A->B hardware trial. No automatic estop clear, retry, or reverse."""
import argparse
import json
import math
from pathlib import Path
import time
from datetime import datetime
import yaml
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from sensor_msgs.msg import JointState, Joy
from geometry_msgs.msg import Twist
from control_msgs.msg import DynamicJointState
from std_msgs.msg import Int32, Bool
from robot_msgs.msg import TransformStep, TransformStepResult, CommandFeedback, SystemError

ROOT = Path(__file__).resolve().parents[1]
NAMES = ['left_wheel_joint','right_wheel_joint','motor_3_joint','motor_4_joint']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute-a-to-b', action='store_true', required=True)
    parser.parse_args()
    rclpy.init()
    n = Node('supervised_transform_trial')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_path = ROOT / 'log' / f'transform_trial_{stamp}.jsonl'
    log = log_path.open('w', buffering=1)
    state = {'action':None, 'mode':None, 'joy':0, 'pressed':[], 'step':None,
             'status':None, 'failure':None, 'started':False, 'sent':False,
             'initial_error':0.0, 'step_time':0.0, 'drive_zero':False, 'drive_stamp':0.0}
    feedback = {}
    hardware_age = {}
    def record(kind, **data):
        row = {'time':datetime.now().astimezone().isoformat(), 'event':kind, **data}
        log.write(json.dumps(row) + '\n')
        if kind != 'sample': print(json.dumps(row), flush=True)
    def sample(msg):
        ros_age = (n.get_clock().now().nanoseconds - (msg.header.stamp.sec*10**9+msg.header.stamp.nanosec))/1e9
        if not 0 <= ros_age < .3: return
        for i, name in enumerate(msg.name):
            if name not in NAMES or i >= len(msg.position) or i >= len(msg.velocity): continue
            if math.isfinite(msg.position[i]) and math.isfinite(msg.velocity[i]):
                feedback[name] = (time.monotonic(), math.degrees(msg.position[i]), msg.velocity[i])
    def dynamic(msg):
        for name, values in zip(msg.joint_names,msg.interface_values):
            if 'feedback_age' in values.interface_names:
                hardware_age[name] = (time.monotonic(),values.values[values.interface_names.index('feedback_age')])
    def joy(msg):
        state['joy'] = time.monotonic()
        state['pressed'] = [i for i,v in enumerate(msg.buttons) if v]
    def error_for(step):
        current = feedback.get(NAMES[step.motor_id-1], (0,float('nan'),0))[1]
        delta = step.target_angle_deg-current
        return math.remainder(delta,1440) if step.motor_id < 3 else delta
    def step(msg):
        state['step'] = msg
        state['step_time'] = time.monotonic()
        state['initial_error'] = abs(error_for(msg))
        record('step',motor=msg.motor_id,target_deg=msg.target_angle_deg,
               current_deg=feedback.get(NAMES[msg.motor_id-1],(0,None,0))[1])
    def result(msg):
        record('result',motor=msg.motor_id,success=msg.success,timeout=msg.timeout,
               actual_deg=msg.actual_angle_deg,message=msg.message)
        if not msg.success: state['failure'] = msg.message
    def status(msg):
        state['status'] = msg.data
        record('status',value=msg.data)
        if msg.data == 1: state['started'] = True
        if msg.data in (2,4) and state['sent']: state['failure'] = f'transform status {msg.data}'
    def command_feedback(msg):
        record('command_feedback',accepted=msg.accepted,code=msg.code,message=msg.message)
        if state['sent'] and not msg.accepted: state['failure'] = msg.message
    def system_error(msg):
        if state['sent']: state['failure'] = str(msg)
        record('system_error',message=str(msg))
    def estop(msg):
        if msg.data and state['sent']: state['failure'] = 'Joystick/system emergency stop'
    def drive(msg):
        values = [msg.linear.x,msg.linear.y,msg.linear.z,msg.angular.x,msg.angular.y,msg.angular.z]
        state['drive_zero'] = all(math.isfinite(v) and abs(v)<1e-8 for v in values)
        state['drive_stamp'] = time.monotonic()
    n.create_subscription(Twist,'/drive/cmd_vel',drive,20)
    n.create_subscription(JointState,'/joint_states',sample,100)
    n.create_subscription(JointState,'/dxl_joint_states',sample,100)
    n.create_subscription(DynamicJointState,'/dynamic_joint_states',dynamic,20)
    n.create_subscription(Joy,'/joy',joy,20)
    n.create_subscription(TransformStep,'/transform/step_cmd',step,20)
    n.create_subscription(TransformStepResult,'/transform/step_result',result,20)
    n.create_subscription(Int32,'/transform/status',status,20)
    n.create_subscription(CommandFeedback,'/transform/command_feedback',command_feedback,20)
    n.create_subscription(SystemError,'/system/error',system_error,20)
    n.create_subscription(Bool,'/emergency_stop',estop,20)
    latch = QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
    n.create_subscription(Int32,'/system/action_state',lambda m:state.update(action=m.data),latch)
    n.create_subscription(Int32,'/system/control_mode',lambda m:state.update(mode=m.data),latch)
    request = n.create_publisher(Int32,'/manual/transform_cmd',20)
    stop = n.create_publisher(Bool,'/emergency_stop',20)
    pause = n.create_publisher(Bool,'/transform/pause',20)
    dxl_stop = n.create_publisher(Int32,'/dxl_stop_cmd',20)
    def fresh():
        now = time.monotonic()
        if now-state['joy'] > .3: return False
        for name in NAMES:
            if now-feedback.get(name,(0,0,0))[0] > .3: return False
        for name in NAMES[:2]:
            t,age = hardware_age.get(name,(0,float('inf')))
            if now-t > .3 or not math.isfinite(age) or not 0 <= age < .2: return False
        return True
    def halt(reason):
        record('halt',reason=reason)
        for _ in range(5):
            stop.publish(Bool(data=True))
            pause.publish(Bool(data=True))
            dxl_stop.publish(Int32(data=3))
            dxl_stop.publish(Int32(data=4))
            rclpy.spin_once(n,timeout_sec=.03)
    success = False
    try:
        end = time.monotonic()+5
        while time.monotonic()<end:
            rclpy.spin_once(n,timeout_sec=.02)
        neutral_drive = state['action'] == 1 and state['drive_zero'] and time.monotonic()-state['drive_stamp'] < .3
        if (state['action'] != 0 and not neutral_drive) or state['mode'] != 0 or not fresh() or state['pressed']:
            raise RuntimeError('Not armed: need MANUAL with IDLE or freshly confirmed zero-speed DRIVE, fresh motor+joystick feedback, all buttons released: '+str(state))
        params = yaml.safe_load((ROOT/'src/robot_transform/config/transform_params.yaml').read_text())['transform_manager_node']['ros__parameters']
        refs = [params[k] for k in ['left_bldc_alignment_offset_deg','right_bldc_alignment_offset_deg','motor3_grid_offset_deg','motor4_a_reference_deg']]
        for i,name in enumerate(NAMES):
            if abs(math.remainder(feedback[name][1]-refs[i], 720 if i<2 else 360)) > 2:
                raise RuntimeError('Start position changed since A calibration: '+name)
        record('start',reference_deg=refs,feedback_deg={k:v[1] for k,v in feedback.items()})
        state['sent'] = True
        request.publish(Int32(data=2))
        start = time.monotonic()
        last_sample = start
        while time.monotonic()-start < 300:
            rclpy.spin_once(n,timeout_sec=.01)
            now = time.monotonic()
            if state['failure']: raise RuntimeError(state['failure'])
            if not fresh(): raise RuntimeError('Motor or joystick feedback expired')
            if not state['started'] and now-start > 3: raise RuntimeError('No transform acceptance')
            if state['status'] == 3:
                success = True
                record('completed',feedback_deg={k:v[1] for k,v in feedback.items()})
                break
            active = state['step']
            if active:
                if abs(error_for(active)) > state['initial_error']+30:
                    raise RuntimeError('Motor moving away from planned target')
                if now-state['step_time'] > active.timeout_sec+1:
                    raise RuntimeError('Step-result watchdog timeout')
            if now-last_sample > .1:
                record('sample',feedback={k:{'deg':v[1],'velocity':v[2]} for k,v in feedback.items()})
                last_sample = now
        if not success: raise RuntimeError('Trial deadline exceeded')
    except BaseException as exc:
        if state['sent']: halt(str(exc))
        else: record('not_started',reason=str(exc))
    finally:
        record('finished',success=success,log=str(log_path))
        log.close()
        n.destroy_node()
        rclpy.shutdown()
    raise SystemExit(0 if success else 1)

if __name__ == '__main__': main()

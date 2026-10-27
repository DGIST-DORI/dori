#!/usr/bin/env python3
"""Real bridge/supervisor/C++ drive; calibrated software plant, isolated DDS 99.

Nav2's output/authority and physical sensors are the test fixtures here. The
separate integration_lidar_web suite covers actual Nav2 and HRI goal producers.
"""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

if os.getenv('ROS_DOMAIN_ID') != '99' or os.getenv('ROS_LOCALHOST_ONLY') != '1':
    raise RuntimeError('Use ROS_DOMAIN_ID=99 ROS_LOCALHOST_ONLY=1; no hardware drivers')

import rclpy
from control_msgs.msg import DynamicJointState, InterfaceValue
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import Odometry
from rcl_interfaces.msg import Parameter, ParameterValue
from rcl_interfaces.srv import SetParameters
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from robot_msgs.msg import MitCommand
from sensor_msgs.msg import JointState, LaserScan
from std_msgs.msg import Bool, Int32, String
from tf2_ros import TransformBroadcaster, StaticTransformBroadcaster

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from drive_contract import check_drive_contract


def main():
    log = ROOT/'log/validation'
    log.mkdir(parents=True, exist_ok=True)
    rclpy.init()
    n = Node('drive_chain_test_fixture')
    executor = SingleThreadedExecutor(); executor.add_node(n)
    latch = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    pub = {key: n.create_publisher(typ, topic, qos) for key, typ, topic, qos in [
        ('command', Twist, '/nav/cmd_vel', 10), ('manual', Twist, '/manual/cmd_vel', 10),
        ('authority', Bool, '/navigation/authority_heartbeat', 10),
        ('goal', Bool, '/navigation/goal_active', latch), ('arm', Int32, '/NAVIGATION_MODE', 10),
        ('mode', Int32, '/control_mode_cmd', 10), ('odom', Odometry, '/odom', 10),
        ('scan', LaserScan, '/scan', 10), ('feedback', DynamicJointState, '/dynamic_joint_states', 10),
        ('joints', JointState, '/joint_states', 10)]}
    state = dict(v=0., w=0., gain=.62, x=0., y=0., yaw=0., left=0., right=0., lpos=0., rpos=0.,
                 desired=[0., 0.], manual=0., auto=[0., 0.], drive=[0., 0.], authority=True,
                 fault=None, gate=None, motion={}, mode=None, last=time.monotonic())
    n.create_subscription(Twist, '/auto/cmd_vel', lambda m: state.update(auto=[m.linear.x, m.angular.z]), 10)
    n.create_subscription(Twist, '/drive/cmd_vel', lambda m: state.update(drive=[m.linear.x, m.angular.z]), 10)
    n.create_subscription(String, '/navigation/drive_status', lambda m: state.update(gate=m.data), latch)
    n.create_subscription(String, '/navigation/motion_interpreter', lambda m: state.update(motion=json.loads(m.data)), 10)
    n.create_subscription(Int32, '/system/control_mode', lambda m: state.update(mode=m.data), latch)
    def motor(msg):
        if msg.motor_id in (1, 2): state['left' if msg.motor_id == 1 else 'right'] = msg.v_des
    n.create_subscription(MitCommand, '/bldc_mit_speed_cmd', motor, 100)
    tf = TransformBroadcaster(n); static = StaticTransformBroadcaster(n)
    laser_tf = TransformStamped(); laser_tf.header.frame_id='base_link'; laser_tf.child_frame_id='laser'
    laser_tf.transform.rotation.w=1.; static.sendTransform(laser_tf)

    def sensors():
        now=time.monotonic(); dt=min(now-state['last'], .05); state['last']=now
        u=.234*(state['left']+state['right'])/2/1.72
        turn=.234*(state['right']-state['left'])/.184/7.
        target=state['gain']*math.copysign(max(abs(u)-.22, 0.), u)
        state['v']+=(target-state['v'])*dt/.15
        state['w']+=((1.67*turn if abs(state['v'])>.025 else 0.)-state['w'])*dt/.15
        v,w=state['v'],state['w']; state['yaw']+=w*dt
        state['x']+=v*math.cos(state['yaw'])*dt; state['y']+=v*math.sin(state['yaw'])*dt
        # Ground speed comes from LiDAR; encoder speeds intentionally differ as
        # in the measured robot. Learning must not equate the two sources.
        vl=(1.94*v-2.17*w*.184/2)/.234; vr=(1.94*v+2.17*w*.184/2)/.234
        state['lpos']+=vl*dt; state['rpos']+=vr*dt
        stamp=n.get_clock().now().to_msg()
        odom=Odometry(); odom.header.stamp=stamp; odom.header.frame_id='odom'; odom.child_frame_id='base_link'
        odom.pose.pose.position.x=state['x']; odom.pose.pose.position.y=state['y']
        odom.pose.pose.orientation.z=math.sin(state['yaw']/2); odom.pose.pose.orientation.w=math.cos(state['yaw']/2)
        odom.twist.twist.linear.x=v; odom.twist.twist.angular.z=math.nan if state['fault']=='odom' else w
        base=TransformStamped(); base.header=odom.header; base.child_frame_id='base_link'
        base.transform.translation.x=state['x']; base.transform.translation.y=state['y']; base.transform.rotation=odom.pose.pose.orientation
        localization=TransformStamped(); localization.header.stamp=stamp; localization.header.frame_id='map'
        localization.child_frame_id='odom'; localization.transform.rotation.w=1.
        tf.sendTransform([base,localization]); pub['odom'].publish(odom)
        scan=LaserScan(); scan.header.stamp=stamp; scan.header.frame_id='laser'
        scan.angle_min=-math.pi; scan.angle_increment=math.pi/180; scan.range_min=.1; scan.range_max=10.; scan.ranges=[3.]*360
        pub['scan'].publish(scan)
        joints=JointState(); joints.header.stamp=stamp; joints.name=['left_wheel_joint','right_wheel_joint']
        joints.position=[math.remainder(state['lpos'],8*math.pi),math.remainder(state['rpos'],8*math.pi)]
        joints.velocity=[vl,vr]; pub['joints'].publish(joints)
        feedback=DynamicJointState(); feedback.header.stamp=stamp; feedback.joint_names=joints.name
        feedback.interface_values=[InterfaceValue(interface_names=['feedback_age','position','velocity'],values=[.001,p,vv])
                                   for p,vv in zip(joints.position,joints.velocity)]
        if state['fault']=='encoder': feedback.interface_values[0].values[1]=math.nan
        if state['fault']=='delay':
            feedback.header.stamp=rclpy.time.Time(nanoseconds=n.get_clock().now().nanoseconds-120000000).to_msg()
            for values in feedback.interface_values: values.values[0]=.12
        pub['feedback'].publish(feedback)
        if state['authority']: pub['authority'].publish(Bool(data=True))
        command=Twist(); command.linear.x,command.angular.z=state['desired']; pub['command'].publish(command)
        manual=Twist(); manual.linear.x=state['manual']; pub['manual'].publish(manual)
    n.create_timer(.02,sensors)
    thread=threading.Thread(target=executor.spin,daemon=True); thread.start()
    processes=[]; handles=[]; report={'ok':False,'plant':'software calibrated response; no physical motors','checks':{}}
    def start(label,cmd):
        f=(log/('drive-chain-'+label+'.log')).open('w'); handles.append(f)
        p=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,start_new_session=True); processes.append(p)
        return p
    def wait(predicate, label, timeout=5):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            if any(p.poll() is not None for p in processes): raise AssertionError('Process exited: '+label)
            if predicate(): return
            time.sleep(.02)
        raise AssertionError(label+': '+str(state))
    def wait_future(future, timeout): wait(future.done,'parameter response',timeout)
    def stopped(): return max(abs(state['left']),abs(state['right']))<1e-6
    drive_cmd=['ros2','run','robot_drive','drive_controller_node','--ros-args',
               '--params-file',str(ROOT/'ros2_ws/src/robot_drive/config/drive_params.yaml'),
               '--params-file',str(ROOT/'ros2_ws/src/robot_drive/config/kinematics.yaml')]
    try:
        start('supervisor',['ros2','run','robot_supervisor','mode_manager_node'])
        drive=start('controller',drive_cmd)
        start('bridge',['/usr/bin/python3',str(ROOT/'ros2_ws/src/robot_navigation/scripts/nav_drive_bridge.py'),
              '--ros-args','--params-file',str(ROOT/'ros2_ws/src/robot_navigation/config/motion_interpreter.yaml'),
              '--params-file',str(ROOT/'ros2_ws/src/robot_drive/config/kinematics.yaml')])
        wait(lambda: state['gate']=='disabled' and state['mode']==0, 'discovery',15)
        report['contract']=check_drive_contract(n,wait_future,check_routes=False)
        assert report['contract']['ok'],report['contract']
        for node_name,param,value in [('drive_controller_node','wheel_separation',.3),('nav_drive_bridge','motion_interpreter_enabled',False)]:
            client=n.create_client(SetParameters,'/'+node_name+'/set_parameters')
            assert client.wait_for_service(timeout_sec=2)
            pv=ParameterValue(type=1,bool_value=value) if isinstance(value,bool) else ParameterValue(type=3,double_value=value)
            future=client.call_async(SetParameters.Request(parameters=[Parameter(name=param,value=pv)]))
            wait_future(future,2); assert not future.result().results[0].successful
            n.destroy_client(client)
        report['checks']['live_calibration_edits_rejected']=True
        pub['goal'].publish(Bool(data=True)); pub['arm'].publish(Int32(data=1)); state['desired']=[.3,0.]
        wait(lambda:state['gate']=='driving','auto drive armed')
        time.sleep(9)
        assert .27<state['v']<.33 and .65<state['auto'][0]<.78,state
        assert abs(state['auto'][0]-state['drive'][0])<.04,state
        report['checks']['straight']={k:state[k] for k in ('v','auto','drive','left','right','motion')}
        state['desired']=[.3,.4]; time.sleep(8)
        assert .25<state['v']<.35 and .30<state['w']<.50,state
        assert state['right']>state['left']>0,state
        report['checks']['rolling_turn']={k:state[k] for k in ('v','w','auto','drive','left','right','motion')}
        state['desired']=[.3,0.]; state['gain']=.52; time.sleep(12)
        assert .26<state['v']<.34,state
        assert state['motion']['linear']['learned_samples']>0,state
        assert state['motion']['linear']['response_gain']<.61,state
        report['checks']['adaptation']={k:state[k] for k in ('v','gain','auto','motion')}
        for fault,gate in [('odom','nonfinite_odom'),('encoder','stale_hardware_feedback'),('delay','stale_hardware_feedback')]:
            state['fault']=fault; began=time.monotonic()
            wait(lambda:state['gate']==gate and stopped(),fault+' must stop',1)
            time.sleep(.15); assert stopped(),state
            report['checks'][fault+'_stop_s']=time.monotonic()-began
            state['fault']=None; wait(lambda:state['gate']=='driving' and not stopped(),fault+' recovery',3)
        state['authority']=False; began=time.monotonic()
        wait(lambda:state['gate']=='authority_stale' and stopped(),'authority timeout',1)
        report['checks']['authority_stop_s']=time.monotonic()-began
        state['authority']=True; wait(lambda:state['gate']=='driving' and not stopped(),'authority recovery')
        # Simulate a startup mismatch (no dynamic edits can misreport geometry).
        os.killpg(drive.pid,signal.SIGINT); drive.wait(timeout=5); processes.remove(drive)
        start('mismatched-controller',drive_cmd+['-p','wheel_separation:=0.3'])
        wait(lambda:state['gate']=='hardware_scale_unverified' and stopped(),'geometry mismatch',5)
        mismatch=check_drive_contract(n,wait_future,check_routes=False)
        assert not mismatch['ok'] and any('wheel_separation' in error for error in mismatch['errors']),mismatch
        report['mismatch_diagnostic']=mismatch['errors']
        report['checks']['geometry_mismatch_stops']=True
        pub['mode'].publish(Int32(data=0)); state['manual']=.25
        wait(lambda:state['mode']==0 and state['gate']=='disabled','manual takeover')
        wait(lambda:abs(state['drive'][0]-.25)<1e-6 and state['left']>0,'manual joystick route')
        report['checks']['manual_joystick_input']=state['drive']
        state['manual']=0.; state['desired']=[0.,0.]
        wait(stopped,'manual stop',5)
        report['ok']=True
    finally:
        state['desired']=[0.,0.]; state['manual']=0.; pub['arm'].publish(Int32(data=0))
        for p in reversed(processes):
            if p.poll() is None: os.killpg(p.pid,signal.SIGINT)
        for p in processes:
            try:p.wait(timeout=5)
            except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);p.wait()
        executor.shutdown(timeout_sec=3);thread.join(timeout=3);n.destroy_node();rclpy.shutdown()
        for f in handles:f.close()
        (log/'drive-chain.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__': main()

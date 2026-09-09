#!/usr/bin/env python3
"""Read-only runtime contract check. Never publishes motor, goal or mode commands."""
import argparse
import subprocess
import json
import math
from pathlib import Path
import sys
import time
import yaml
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.qos import qos_profile_sensor_data
from rcl_interfaces.srv import GetParameters
from lifecycle_msgs.srv import GetState
from controller_manager_msgs.srv import ListControllers
from sensor_msgs.msg import JointState, LaserScan
from control_msgs.msg import DynamicJointState
from nav_msgs.msg import Odometry
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer, TransformListener, TransformException

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['base','navigation'],default='navigation')
    parser.add_argument('--duration',type=float,default=5);parser.add_argument('--output')
    args=parser.parse_args()
    args.duration=max(5.0,args.duration)  # Allow DDS discovery before attributing TF publishers.
    rclpy.init();n=Node('robot_contract_preflight');buffer=Buffer();listener=TransformListener(buffer,n)
    latest={};counts={};edges={};odom_history=[]
    def receive(topic):
        def cb(msg):
            latest[topic]=msg;counts[topic]=counts.get(topic,0)+1
            if topic=='/odom':
                odom_history.append(msg)
                if len(odom_history)>20:odom_history.pop(0)
        return cb
    for topic,typ in [('/scan',LaserScan),('/odom',Odometry),('/joint_states',JointState),('/dynamic_joint_states',DynamicJointState)]:
        n.create_subscription(typ,topic,receive(topic),qos_profile_sensor_data)
    authority=subprocess.Popen(['ros2','run','robot_drive','tf_authority_check','--ros-args','-p','duration:='+str(args.duration)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    end=time.monotonic()+args.duration
    while (time.monotonic()<end or authority.poll() is None) and time.monotonic()<end+10:
        rclpy.spin_once(n,timeout_sec=0.01)
    authority_out,authority_err=authority.communicate(timeout=10)
    for line in authority_out.splitlines():
        parts=line.split('\t')
        if len(parts)==4 and parts[0]=='EDGE':edges.setdefault((parts[1],parts[2]),[]).append(parts[3])
    errors=[];report={'counts':counts,'stage':args.stage}
    expected={'/scan':'sensor_msgs/msg/LaserScan','/odom':'nav_msgs/msg/Odometry','/joint_states':'sensor_msgs/msg/JointState','/dynamic_joint_states':'control_msgs/msg/DynamicJointState'}
    for topic,typ in expected.items():
        pubs=n.get_publishers_info_by_topic(topic)
        if len(pubs)!=1 or any(p.topic_type!=typ for p in pubs):errors.append(topic+': needs exactly one '+typ+' publisher')
        if topic not in latest:errors.append(topic+': no received data');continue
        msg=latest[topic];age=(n.get_clock().now()-Time.from_msg(msg.header.stamp)).nanoseconds/1e9
        if not -0.05<=age<=({'/scan':0.5,'/odom':0.25,'/joint_states':0.25,'/dynamic_joint_states':0.25}[topic]):errors.append(topic+': stale or future timestamp')
    if '/scan' in latest:
        scan=latest['/scan']
        if scan.header.frame_id!='laser':errors.append('/scan frame must be laser')
        if not any(math.isfinite(x) and scan.range_min<=x<=scan.range_max for x in scan.ranges):errors.append('/scan: no valid distances')
    if '/joint_states' in latest:
        j=latest['/joint_states']
        for name in ['left_wheel_joint','right_wheel_joint']:
            try:
                index=j.name.index(name)
                if not math.isfinite(j.position[index]):raise ValueError()
            except (ValueError,IndexError):errors.append('Missing/invalid wheel position: '+name)
    if '/dynamic_joint_states' in latest:
        feedback=latest['/dynamic_joint_states']
        report['wheel_feedback_age_s']={}
        for name in ['left_wheel_joint','right_wheel_joint']:
            try:
                values=feedback.interface_values[feedback.joint_names.index(name)]
                age=values.values[values.interface_names.index('feedback_age')]
                report['wheel_feedback_age_s'][name]=age if math.isfinite(age) else None
                if not math.isfinite(age) or not 0<=age<=0.2:raise ValueError()
            except (ValueError,IndexError):errors.append('Missing/stale CAN feedback: '+name)
    if odom_history:
        o=odom_history[max(0,len(odom_history)-3)]
        if o.header.frame_id!='odom' or o.child_frame_id!='base_link':errors.append('/odom frame contract violated')
        try:
            t=buffer.lookup_transform('odom','base_link',Time.from_msg(o.header.stamp))
            p,q=o.pose.pose.position,o.pose.pose.orientation
            tr,qr=t.transform.translation,t.transform.rotation
            delta=math.hypot(p.x-tr.x,p.y-tr.y)
            report['odom_tf_position_error_m']=delta
            if not math.isfinite(delta) or delta>0.01 or abs(abs(q.x*qr.x+q.y*qr.y+q.z*qr.z+q.w*qr.w)-1)>1e-4:
                errors.append('Wheel /odom and odom->base_link TF disagree')
        except TransformException:errors.append('Missing wheel odom->base_link TF at measurement time')
    for edge,gids in edges.items():
        if len(gids)>1:errors.append('Multiple TF publishers for '+str(edge))
    owners=edges.get(('odom','base_link'),[])
    if authority.returncode:errors.append('TF authority check failed: '+authority_err[-300:])
    report['odom_tf_owners']=owners
    if owners!=['wheel_odometry_node']:errors.append('odom->base_link must be owned only by wheel_odometry_node')
    expected_params=yaml.safe_load((ROOT/'src/robot_drive/config/kinematics.yaml').read_text())['/**']['ros__parameters']
    client=n.create_client(GetParameters,'/drive_controller_node/get_parameters')
    if client.wait_for_service(timeout_sec=0.5):
        request=GetParameters.Request();request.names=list(expected_params)
        future=client.call_async(request);rclpy.spin_until_future_complete(n,future,timeout_sec=2)
        if future.done() and future.result():
            for key,value in zip(request.names,future.result().values):
                if value.type!=3 or not math.isclose(value.double_value,expected_params[key],rel_tol=1e-8):errors.append('Hardware parameter mismatch: '+key)
        else:errors.append('Hardware parameter query timed out')
    else:errors.append('Drive controller parameter service missing')
    if args.stage=='base':
        c=n.create_client(ListControllers,'/controller_manager/list_controllers')
        if not c.wait_for_service(timeout_sec=.3):errors.append('Controller manager not discovered yet')
        else:
            f=c.call_async(ListControllers.Request());rclpy.spin_until_future_complete(n,f,timeout_sec=1)
            if not f.done() or not f.result():errors.append('Controller state query timed out')
            else:
                states={x.name:x.state for x in f.result().controller}
                report['controllers']=states
                for name in ['joint_state_broadcaster','left_bldc_drive_controller','right_bldc_drive_controller']:
                    if states.get(name)!='active':errors.append(name+': not active yet')
    if args.stage=='navigation':
        for name in ['map_server','amcl','controller_server','planner_server','behavior_server','bt_navigator','velocity_smoother']:
            c=n.create_client(GetState,'/'+name+'/get_state')
            if not c.wait_for_service(timeout_sec=0.2):errors.append(name+': lifecycle service missing');continue
            f=c.call_async(GetState.Request());rclpy.spin_until_future_complete(n,f,timeout_sec=1)
            if not f.done() or f.result().current_state.id!=3:errors.append(name+': not active')
        try:
            t=buffer.lookup_transform('map','odom',Time())
            age=(n.get_clock().now()-Time.from_msg(t.header.stamp)).nanoseconds/1e9
            if not -1.1<=age<=1.5:errors.append('map->odom is stale')
            buffer.lookup_transform('base_link','laser',Time())
        except TransformException:errors.append('Localization/laser TF missing; set AMCL initial pose')
        names=[name for name,_ in n.get_node_names_and_namespaces()]
        if 'cartographer_node' in names:errors.append('Stop Cartographer before AMCL navigation')
        for name in ['nav_drive_bridge','named_goal_bridge','text_llm_named_goal']:
            if names.count(name)!=1:errors.append(name+': expected one node')
        for topic in ['/nav/cmd_vel','/auto/cmd_vel']:
            pubs=n.get_publishers_info_by_topic(topic)
            if len(pubs)!=1 or pubs[0].topic_type!='geometry_msgs/msg/Twist':errors.append(topic+': wrong publisher/type')
    report.update(ok=not errors,errors=errors)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.output:Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    n.destroy_node();rclpy.shutdown()
    return int(bool(errors))


if __name__=='__main__':raise SystemExit(main())

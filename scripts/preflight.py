#!/usr/bin/env python3
"""Read-only runtime contract check. Never publishes motor, goal or mode commands."""
import argparse
import subprocess
import json
import math
from pathlib import Path
import sys
import time
import threading
import yaml
import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from rclpy.time import Time
from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy
from std_msgs.msg import Int32
from rcl_interfaces.srv import GetParameters
from lifecycle_msgs.srv import GetState
from controller_manager_msgs.srv import ListControllers, ListHardwareComponents
from sensor_msgs.msg import JointState, LaserScan, Imu
from control_msgs.msg import DynamicJointState
from nav_msgs.msg import Odometry
from tf2_msgs.msg import TFMessage
from tf2_ros import Buffer, TransformListener, TransformException
from drive_contract import check_drive_contract

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['base','navigation'],default='navigation')
    parser.add_argument('--duration',type=float,default=5);parser.add_argument('--output')
    parser.add_argument('--hri',action='store_true',help='Also require the integrated HRI actions and coordinator')
    parser.add_argument('--discovery-timeout',type=float,default=10,help='Additional DDS discovery observation time')
    args=parser.parse_args()
    if not math.isfinite(args.discovery_timeout) or not 0<=args.discovery_timeout<=60:parser.error('Invalid discovery timeout')
    args.duration=max(5.0,args.duration)  # Allow DDS discovery before attributing TF publishers.
    rclpy.init();n=Node('robot_contract_preflight');buffer=Buffer();listener=TransformListener(buffer,n)
    latest={};counts={};edges={};odom_history=[];supervisor={}
    latch=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL)
    for topic in ['/system/action_state','/system/control_mode']:
        n.create_subscription(Int32,topic,lambda m,k=topic:supervisor.update({k:m.data}),latch)
    def receive(topic):
        def cb(msg):
            latest[topic]=msg;counts[topic]=counts.get(topic,0)+1
            if topic=='/odom':
                odom_history.append(msg)
                if len(odom_history)>20:odom_history.pop(0)
        return cb
    for topic,typ in [('/scan',LaserScan),('/odom',Odometry),('/joint_states',JointState),('/dynamic_joint_states',DynamicJointState)]:
        n.create_subscription(typ,topic,receive(topic),qos_profile_sensor_data)
    # Keep subscriptions serviced while graph/service queries block the main thread.
    executor=SingleThreadedExecutor();executor.add_node(n)
    worker=threading.Thread(target=executor.spin,daemon=True);worker.start()
    def wait_future(future,timeout):
        deadline=time.monotonic()+timeout
        while not future.done() and time.monotonic()<deadline:time.sleep(.005)
    observation=args.duration+args.discovery_timeout
    authority=subprocess.Popen(['ros2','run','robot_drive','tf_authority_check','--ros-args','-p','duration:='+str(observation)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    end=time.monotonic()+observation
    while (time.monotonic()<end or authority.poll() is None) and time.monotonic()<end+10:
        time.sleep(0.01)
    authority_out,authority_err=authority.communicate(timeout=10)
    for line in authority_out.splitlines():
        parts=line.split('\t')
        if len(parts)==4 and parts[0]=='EDGE':edges.setdefault((parts[1],parts[2]),[]).append(parts[3])
    errors=[];report={'counts':counts,'stage':args.stage,'observation_s':observation}
    expected={'/scan':'sensor_msgs/msg/LaserScan','/odom':'nav_msgs/msg/Odometry','/joint_states':'sensor_msgs/msg/JointState','/dynamic_joint_states':'control_msgs/msg/DynamicJointState'}
    for topic,typ in expected.items():
        pubs=n.get_publishers_info_by_topic(topic)
        if len(pubs)!=1 or any(p.topic_type!=typ for p in pubs):errors.append(topic+': needs exactly one '+typ+' publisher')
        if topic not in latest:errors.append(topic+': no received data');continue
        # Freshness is checked after all service queries against continuously received data.
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
        history=list(odom_history)
        o=history[max(0,len(history)-3)]
        if o.header.frame_id!='odom' or o.child_frame_id!='base_link':errors.append('/odom frame contract violated')
        try:
            t=buffer.lookup_transform('odom','base_link',Time.from_msg(o.header.stamp))
            p,q=o.pose.pose.position,o.pose.pose.orientation
            tr,qr=t.transform.translation,t.transform.rotation
            delta=math.hypot(p.x-tr.x,p.y-tr.y)
            report['odom_tf_position_error_m']=delta
            if not math.isfinite(delta) or delta>0.01 or abs(abs(q.x*qr.x+q.y*qr.y+q.z*qr.z+q.w*qr.w)-1)>1e-4:
                errors.append('/odom and odom->base_link TF disagree')
        except TransformException:errors.append('Missing odom->base_link TF at measurement time')
    for edge,gids in edges.items():
        if len(gids)>1:errors.append('Multiple TF publishers for '+str(edge))
    owners=edges.get(('odom','base_link'),[])
    if authority.returncode:errors.append('TF authority check failed: '+authority_err[-300:])
    report['odom_tf_owners']=owners
    odom_publishers=[p.node_name for p in n.get_publishers_info_by_topic('/odom')]
    report['odom_source']='lidar_odometry'
    if odom_publishers!=['lidar_odometry'] or owners!=['lidar_odometry']:
        errors.append('/odom and odom->base_link must be owned only by lidar_odometry')
    expected_params=yaml.safe_load((ROOT/'ros2_ws/src/robot_drive/config/kinematics.yaml').read_text())['/**']['ros__parameters']
    client=n.create_client(GetParameters,'/drive_controller_node/get_parameters')
    if client.wait_for_service(timeout_sec=0.5):
        request=GetParameters.Request();request.names=list(expected_params)
        future=client.call_async(request);wait_future(future,2)
        if future.done() and future.result():
            for key,value in zip(request.names,future.result().values):
                if value.type!=3 or not math.isclose(value.double_value,expected_params[key],rel_tol=1e-8):errors.append('Hardware parameter mismatch: '+key)
        else:errors.append('Hardware parameter query timed out')
    else:errors.append('Drive controller parameter service missing')
    hardware=n.create_client(ListHardwareComponents,'/controller_manager/list_hardware_components')
    if not hardware.wait_for_service(timeout_sec=.5):errors.append('Hardware component state service missing')
    else:
        future=hardware.call_async(ListHardwareComponents.Request());wait_future(future,2)
        if not future.done() or not future.result():errors.append('Hardware component state query timed out')
        else:
            components=future.result().component
            report['hardware_components']={h.name:h.state.label for h in components}
            drive=[h for h in components if h.name=='CubeMarsSystem']
            if len(drive)!=1 or drive[0].state.id!=3:errors.append('CubeMarsSystem hardware is not active; controller/topic timestamps alone cannot prove CAN operation')
    if args.stage in ('base','navigation'):
        c=n.create_client(ListControllers,'/controller_manager/list_controllers')
        if not c.wait_for_service(timeout_sec=.3):errors.append('Controller manager not discovered yet')
        else:
            f=c.call_async(ListControllers.Request());wait_future(f,1)
            if not f.done() or not f.result():errors.append('Controller state query timed out')
            else:
                states={x.name:x.state for x in f.result().controller}
                report['controllers']=states
                for name in ['joint_state_broadcaster','left_bldc_drive_controller','right_bldc_drive_controller']:
                    if states.get(name)!='active':errors.append(name+': not active yet')
    if args.stage=='navigation':
        report['drive_contract'] = check_drive_contract(n, wait_future)
        errors.extend(report['drive_contract']['errors'])
        report['map_tf_owners']=edges.get(('map','odom'),[])
        if report['map_tf_owners']!=['amcl']:errors.append('map->odom must be owned only by amcl')
        for name in ['map_server','amcl','controller_server','planner_server','bt_navigator','velocity_smoother']:
            c=n.create_client(GetState,'/'+name+'/get_state')
            if not c.wait_for_service(timeout_sec=0.2):errors.append(name+': lifecycle service missing');continue
            f=c.call_async(GetState.Request());wait_future(f,1)
            if not f.done() or f.result().current_state.id!=3:errors.append(name+': not active')
        try:
            t=buffer.lookup_transform('map','odom',Time())
            age=(n.get_clock().now()-Time.from_msg(t.header.stamp)).nanoseconds/1e9
            if not -1.1<=age<=1.5:errors.append('map->odom is stale')
            buffer.lookup_transform('base_link','laser',Time())
        except TransformException:errors.append('Localization/laser TF missing; set AMCL initial pose')
        names=[name for name,_ in n.get_node_names_and_namespaces()]
        if 'cartographer_node' in names:errors.append('Stop Cartographer before AMCL navigation')
        for name in ['nav_drive_bridge','named_goal_bridge','nav2_adapter','named_goal_adapter']:
            if names.count(name)!=1:errors.append(name+': expected one node')
        goal_client=n.create_client(GetParameters,'/named_goal_bridge/get_parameters')
        if not goal_client.wait_for_service(timeout_sec=.5):errors.append('Goal source service missing')
        else:
            req=GetParameters.Request();req.names=['goal_source']
            future=goal_client.call_async(req);wait_future(future,1)
            if not future.done() or not future.result():errors.append('Goal source query failed')
            else:
                values=future.result().values
                source=values[0].string_value if len(values)==1 else ''
                report['goal_source']=source
                if source not in ('rviz','web'):errors.append('Unknown goal source')
                if source in ('rviz','web') and 'text_llm_named_goal' in names:errors.append('RViz mode must not run text_llm_named_goal')
                consumers=n.get_subscriptions_info_by_topic('/goal_pose')
                report['rviz_goal_consumers']=[p.node_name for p in consumers]
                wanted=['named_goal_bridge'] if source in ('rviz','web') else []
                if sorted(report['rviz_goal_consumers'])!=wanted or any(
                        p.topic_type!='geometry_msgs/msg/PoseStamped' for p in consumers):
                    errors.append('/goal_pose must route only through named_goal_bridge in RViz mode; remap the native bt_navigator input')
        for topic in ['/navigation/goal_active','/navigation/enabled','/navigation/authority_heartbeat']:
            pubs=n.get_publishers_info_by_topic(topic)
            if len(pubs)!=1 or pubs[0].node_name!='nav2_adapter':
                errors.append(topic+': must have exactly one DORI navigation authority')
        services={name for name,_ in n.get_service_names_and_types()}
        if '/dori/internal/navigate_to_pose/_action/send_goal' not in services:
            errors.append('Private Nav2 action missing; check Humble endpoint remappings')
    if args.hri:
        names=[name for name,_ in n.get_node_names_and_namespaces()]
        for name in ('dori_tree_executor','llm_node','tts_node','emotion_publisher_node'):
            if names.count(name)!=1:errors.append(name+': expected one HRI node')
        services={name for name,_ in n.get_service_names_and_types()}
        for action in ('/dori/llm/query','/dori/tts/speak','/dori/nav/navigate_named'):
            if action+'/_action/send_goal' not in services:errors.append(action+': HRI action unavailable')
    report['supervisor']=dict(supervisor)
    state=supervisor.get('/system/action_state')
    states={0:'IDLE',1:'DRIVE',2:'TRANSFORM',3:'TRANSFORM_PAUSED',4:'ESTOP',5:'ERROR'}
    if state not in (0,1):errors.append('Hardware supervisor inhibits driving: '+states.get(state,'MISSING/UNKNOWN'))
    control=supervisor.get('/system/control_mode')
    if control not in (0,1):errors.append('Hardware control mode missing/unknown')
    limits={'/scan':.8,'/odom':.5,'/joint_states':.25,'/dynamic_joint_states':.25}
    snapshot=dict(latest);now=n.get_clock().now().nanoseconds/1e9
    report['message_age_s']={}
    for topic,limit in limits.items():
        msg=snapshot.get(topic)
        if msg is None:continue  # Missing data was already rejected above.
        age=now-(msg.header.stamp.sec+msg.header.stamp.nanosec/1e9)
        report['message_age_s'][topic]=age
        if not -.05<=age<=limit:errors.append(topic+': stale or future timestamp')
    report['counts']=dict(counts)
    report.update(ok=not errors,errors=errors)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.output:Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    executor.shutdown(timeout_sec=3);worker.join(timeout=3)
    n.destroy_node();rclpy.shutdown()
    return int(bool(errors))


if __name__=='__main__':raise SystemExit(main())

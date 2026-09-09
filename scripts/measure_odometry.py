#!/usr/bin/env python3
"""Interactive, read-only 1 m wheel odometry measurement. Never publishes motion."""
import json,math,select,sys,time
from pathlib import Path


def metrics(first,last,path,yaw_span,actual,scale):
    x0,y0,a0=first;x,y,a=last
    dx,dy=x-x0,y-y0
    distance=math.hypot(dx,dy)
    forward=math.cos(a0)*dx+math.sin(a0)*dy
    lateral=-math.sin(a0)*dx+math.cos(a0)*dy
    straight=forward>0 and yaw_span<math.radians(10) and abs(lateral)<max(.02,distance*.05) and path<distance*1.1+.01
    return {'actual_distance_m':actual,'odom_displacement_m':distance,'odom_forward_m':forward,
            'odom_lateral_m':lateral,'odom_path_length_m':path,'heading_span_deg':math.degrees(yaw_span),
            'distance_error_m':distance-actual,'distance_error_percent':(distance/actual-1)*100,
            'current_odom_scale':scale,'straight_run':straight,
            'suggested_odom_scale':scale*actual/distance if straight and distance>.01 else None}


def run_measurement(actual,scale,logs,check_children=lambda:None):
    import rclpy
    from nav_msgs.msg import Odometry
    from rclpy.qos import qos_profile_sensor_data
    from rcl_interfaces.srv import GetParameters
    rclpy.init();n=rclpy.create_node('odometry_distance_measurement')
    latest=None;received=0;stamp=0;active=False;first=None;previous=None;path=0.;yaw_total=0.;yaw_low=0.;yaw_high=0.;sample_count=0;fault=None
    def pose(m):
        p=m.pose.pose.position;q=m.pose.pose.orientation
        return p.x,p.y,math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
    def receive(m):
        nonlocal latest,received,stamp,previous,path,yaw_total,yaw_low,yaw_high,sample_count,fault
        t=m.header.stamp.sec+m.header.stamp.nanosec/1e9
        now=n.get_clock().now().nanoseconds/1e9
        p=pose(m)
        if m.header.frame_id!='odom' or m.child_frame_id!='base_link' or not all(math.isfinite(x) for x in p) or not -.05<=now-t<=.25:
            if active:fault='Invalid odometry frame/value/timestamp'
            return
        if active and (t<=stamp or t-stamp>.2):fault='Odometry timestamp reset or gap during measurement'
        latest=m;received=time.monotonic();stamp=t
        if active:
            if previous:
                path+=math.hypot(p[0]-previous[0],p[1]-previous[1])
                yaw_total+=math.remainder(p[2]-previous[2],2*math.pi)
                yaw_low=min(yaw_low,yaw_total);yaw_high=max(yaw_high,yaw_total)
            previous=p;sample_count+=1
    n.create_subscription(Odometry,'/odom',receive,qos_profile_sensor_data)
    def spin():
        rclpy.spin_once(n,timeout_sec=.03);check_children()
    def fresh():return latest is not None and time.monotonic()-received<.25
    def stopped():
        return fresh() and abs(latest.twist.twist.linear.x)<.02 and abs(latest.twist.twist.angular.z)<.15
    try:
        client=n.create_client(GetParameters,'/wheel_odometry_node/get_parameters')
        if not client.wait_for_service(timeout_sec=3):raise RuntimeError('Odometry parameter service missing')
        req=GetParameters.Request();req.names=['odom_scale'];f=client.call_async(req)
        end=time.monotonic()+3
        while not f.done() and time.monotonic()<end:spin()
        if not f.done() or not f.result() or not math.isclose(f.result().values[0].double_value,scale):raise RuntimeError('Active odom_scale does not match requested scale')
        print(f'\n실제 {actual:g}m 직진 측정 / odom_scale={scale:g}. 주행은 조이스틱으로 직접 합니다.',flush=True)
        print('출발선에서 정지한 뒤 Enter를 누르세요. q+Enter: 종료',flush=True)
        index=0;last_print=0
        while True:
            spin()
            if active and (fault or not fresh()):
                (logs/'measurement_failed.json').write_text(json.dumps({'valid':False,'error':fault or 'Odometry reception lost'},indent=2))
                raise RuntimeError(fault or 'Odometry reception lost; measurement invalid')
            if active and time.monotonic()-last_print>.5:
                m=metrics(first,pose(latest),path,yaw_high-yaw_low,actual,scale)
                print(f"\r진행: odom {m['odom_displacement_m']:.4f}m | 전진 {m['odom_forward_m']:+.4f}m | 옆이동 {m['odom_lateral_m']:+.4f}m | 경로 {path:.4f}m   ",end='',flush=True);last_print=time.monotonic()
            if not select.select([sys.stdin],[],[],0)[0]:continue
            line=sys.stdin.readline()
            if line=='' or line.strip().lower()=='q':break
            if not stopped():
                print('\n정지한 상태에서 Enter를 눌러주세요. 신선한 /odom도 필요합니다.',flush=True);continue
            if not active:
                first=pose(latest);previous=first;path=0.;yaw_total=0.;yaw_low=0.;yaw_high=0.;fault=None;sample_count=0;active=True
                print(f'측정 시작. 실제 바닥에서 {actual:g}m 전진 후 정지하고 Enter를 누르세요.',flush=True)
            else:
                active=False;index+=1
                result=metrics(first,pose(latest),path,yaw_high-yaw_low,actual,scale)
                result.update(valid=True,samples=sample_count,start_pose=first,end_pose=pose(latest),measurement='wheel odometry vs user-measured ground distance; no automatic motor commands')
                dest=logs/f'odometry_distance_{index:02d}.json';dest.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                print(f"\n\n실제 입력 거리: {actual:.4f}m\nodom 이동거리: {result['odom_displacement_m']:.4f}m\n오차: {result['distance_error_m']:+.4f}m ({result['distance_error_percent']:+.1f}%)",flush=True)
                if result['suggested_odom_scale'] is not None:print(f"거리 기준 배율 후보: {result['suggested_odom_scale']:.6g} (자동 적용 안 함; 회전 배율은 별도 검증)",flush=True)
                else:print('직진 조건/최소 이동량을 만족하지 않아 배율 추천을 보류합니다.',flush=True)
                print(f'저장: {dest}\n출발점에서 다음 측정: Enter / 종료: q+Enter 또는 Ctrl+C',flush=True)
    finally:
        n.destroy_node()
        if rclpy.ok():rclpy.shutdown()

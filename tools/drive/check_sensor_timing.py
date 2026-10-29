#!/usr/bin/env python3
"""Read-only sensor arrival/header timing audit. No command publishers."""
import json,time,statistics
from collections import defaultdict
import rclpy
from sensor_msgs.msg import Imu,LaserScan,JointState
from nav_msgs.msg import Odometry
from tf2_msgs.msg import TFMessage
from rclpy.qos import qos_profile_sensor_data
rclpy.init();n=rclpy.create_node('sensor_timing_audit');data=defaultdict(list);warm=time.monotonic()+5

def receive(key,stamp):
    if time.monotonic()<warm:return
    now=n.get_clock().now().nanoseconds/1e9
    data[key].append((time.monotonic(),now-stamp.sec-stamp.nanosec/1e9))
for topic,typ in [('/imu/data_raw',Imu),('/imu/mapping',Imu),('/scan',LaserScan),('/odom',Odometry),('/joint_states',JointState)]:
    n.create_subscription(typ,topic,lambda m,k=topic:receive(k,m.header.stamp),qos_profile_sensor_data)
def tf_cb(m):
    for t in m.transforms:
        if t.child_frame_id in ('odom','base_link'):receive(t.header.frame_id+'->'+t.child_frame_id,t.header.stamp)
n.create_subscription(TFMessage,'/tf',tf_cb,qos_profile_sensor_data)
end=warm+10
while time.monotonic()<end:rclpy.spin_once(n,timeout_sec=.01)
report={}
for k,rows in data.items():
    ages=sorted(a for _,a in rows);gaps=[b[0]-a[0] for a,b in zip(rows,rows[1:])]
    report[k]={'count_10s':len(rows),'age_median_s':statistics.median(ages),'age_p95_s':ages[min(len(ages)-1,int(len(ages)*.95))],'age_max_s':max(ages),'max_arrival_gap_s':max(gaps,default=0)}
print(json.dumps(report,indent=2));n.destroy_node();rclpy.shutdown()

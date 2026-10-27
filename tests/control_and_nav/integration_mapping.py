#!/usr/bin/env python3
"""Domain 94: synthetic scan -> LiDAR odometry -> Cartographer -> saved map."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

if os.getenv('ROS_DOMAIN_ID') != '94' or os.getenv('ROS_LOCALHOST_ONLY') != '1':
    raise RuntimeError('Use isolated ROS_DOMAIN_ID=94 ROS_LOCALHOST_ONLY=1')

import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan
from nav_msgs.msg import Odometry, OccupancyGrid
from tf2_ros import Buffer, TransformListener
from rclpy.time import Time
from tests.control_and_nav.lidar_scene import ranges

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts'))
from robot_stack import stop_children


def main():
    (ROOT/'log').mkdir(exist_ok=True)
    rclpy.init();node = rclpy.create_node('mapping_software_probe')
    executor = SingleThreadedExecutor();executor.add_node(node)
    publisher = node.create_publisher(LaserScan, '/scan', qos_profile_sensor_data)
    state = dict(start=None, pose=[0., 0., 0.], odom=None, map=None, scans=0)
    node.create_subscription(Odometry, '/odom', lambda msg: state.update(odom=msg), qos_profile_sensor_data)
    node.create_subscription(OccupancyGrid, '/map', lambda msg: state.update(map=msg), 10)
    buffer = Buffer();listener = TransformListener(buffer, node)

    def laser():
        progress = min(1., max(0., (time.monotonic()-state['start'])/12)) if state['start'] else 0.
        pose = [1.2*progress, .1*progress, .15*progress]
        state['pose'] = pose
        msg = LaserScan();msg.header.stamp = node.get_clock().now().to_msg();msg.header.frame_id = 'laser'
        msg.angle_min = -math.pi;msg.angle_increment = 2*math.pi/720
        msg.angle_max = msg.angle_min+719*msg.angle_increment
        msg.range_min = .1;msg.range_max = 16.;msg.scan_time = .1
        msg.ranges = ranges(pose, (0., 0., math.pi), noise=.002, seed=state['scans']).tolist()
        publisher.publish(msg);state['scans'] += 1

    timer = node.create_timer(.1, laser)
    thread = threading.Thread(target=executor.spin, daemon=True);thread.start()
    children = [];logs = []

    def start(label, command):
        handle = (ROOT/'log'/('mapping_'+label+'.log')).open('w');logs.append(handle)
        process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
        children.append((label, process))

    def wait(predicate, label, seconds):
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            if any(p.poll() is not None for _, p in children):
                raise RuntimeError('Mapping node exited; inspect mapping_*.log')
            if predicate():return
            time.sleep(.1)
        raise AssertionError(label)

    try:
        start('odom', ['ros2', 'launch', 'robot_mapping', 'lidar_odometry.launch.py'])
        wait(lambda: state['odom'] is not None, 'LiDAR odometry missing', 20)
        start('cartographer', [str(ROOT/'scripts/run_mapping.sh')])
        wait(lambda: state['map'] is not None, 'Cartographer map missing', 35)
        state['start'] = time.monotonic()
        wait(lambda: time.monotonic()-state['start'] > 14, 'Trajectory incomplete', 20)
        od = state['odom'].pose.pose.position;truth = state['pose']
        error = math.hypot(od.x-truth[0], od.y-truth[1])
        assert error < .08, error
        grid = state['map'];known = sum(v >= 0 for v in grid.data);occupied = sum(v >= 65 for v in grid.data)
        assert grid.header.frame_id == 'map' and known > 1000 and occupied > 100
        tf = buffer.lookup_transform('map', 'base_link', Time())
        map_error = math.hypot(tf.transform.translation.x-truth[0], tf.transform.translation.y-truth[1])
        assert map_error < .20, map_error
        assert [x.node_name for x in node.get_publishers_info_by_topic('/odom')] == ['lidar_odometry']
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory)/'site'
            result = subprocess.run([str(ROOT/'scripts/save_map.sh'), str(prefix)], capture_output=True, text=True, timeout=20)
            assert result.returncode == 0, result.stdout+result.stderr
            assert prefix.with_suffix('.yaml').is_file() and prefix.with_suffix('.pgm').is_file()
        report = dict(ok=True, plant='synthetic LiDAR only; no motor nodes', scans=state['scans'],
            final_truth=truth, odometry_error_m=error, map_pose_error_m=map_error,
            known_cells=known, occupied_cells=occupied, map_saved=True)
        (ROOT/'log/mapping_validation.json').write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps(report, indent=2))
    finally:
        stop_children(children)
        timer.cancel();executor.shutdown(timeout_sec=3);thread.join(timeout=3)
        node.destroy_node();rclpy.shutdown()
        for handle in logs:handle.close()


if __name__ == '__main__':
    main()

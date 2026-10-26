"""ROS telemetry projection and explicit goal/mode commands; never motor commands."""
from collections import deque
import io
import json
import math
import queue
import threading
import time
import zlib
import uuid
import os
from pathlib import Path as FilePath
import numpy as np
from PIL import Image
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from sensor_msgs.msg import LaserScan, Imu, JointState
from control_msgs.msg import DynamicJointState
from std_msgs.msg import Bool, Int32, String, Float64
from tf2_ros import Buffer, TransformListener, TransformException
from .geometry import yaw, pose_values, free_cell
from .lifecycle import LifecycleReadiness
from .localization import LocalPoseSearch
from .auto_alignment import PeriodicAlignment
from .goals import GoalStore, map_key
from .relative_motion import forward_distance, forward_goal, forward_reply


class WebBridge(Node):
    def __init__(self, mode='monitor', goals_path=None):
        super().__init__('dori_web_viewer')
        self.instance_id = uuid.uuid4().hex
        self.mode = mode
        self.requested_mode = mode
        self.joints = {}
        self.snapshot_time = time.monotonic()
        self.lock = threading.Lock()
        self.snapshot = {'connected': True, 'mode': mode, 'sensors': {}}
        self.map_png = b''
        self.map_info = None
        self.map_message = None
        self.map_version = 0
        self.map_signature = None
        self.messages = {}
        self.scans = deque(maxlen=8)
        self.arrivals = {}
        self.rates = {}
        self.values = {}
        self.commands = queue.Queue(maxsize=32)
        self.owner = None
        self.lease_until = 0
        self.selected_goal = None
        self.selected_goal_name = None
        self.selected_goal_kind = 'destination'
        self.goal_revision = 0
        self.last_goal_request = -math.inf
        self.goal_store = GoalStore(goals_path or FilePath(os.getenv('ROBOT_WS',str(FilePath(__file__).resolve().parents[3])))/'maps/web_goals.json')
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        latch = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        # Cartographer publishes volatile, map_server publishes transient-local.
        self.create_subscription(OccupancyGrid, '/map', self.receive_map, 1)
        self.create_subscription(OccupancyGrid, '/map', self.receive_map, latch)
        for key, topic, typ in [('scan', '/scan', LaserScan), ('odom', '/odom', Odometry),
                                ('imu', '/imu/data_raw', Imu), ('plan', '/plan', Path),
                                ('local_plan', '/local_plan', Path),
                                ('wheel_control', '/drive/wheel_control', DynamicJointState),
                                ('hardware_feedback', '/dynamic_joint_states', DynamicJointState)]:
            self.create_subscription(typ, topic, lambda msg, k=key: self.receive(k, msg), qos_profile_sensor_data)
        for key, topic, typ, qos in [
                ('drive', '/navigation/drive_status', String, latch),
                ('motion', '/navigation/motion_interpreter', String, 5),
                ('goal_status', '/named_goal_status', String, latch),
                ('retry', '/navigation/retry_status', String, latch),
                ('odometry', '/lidar_odometry/status', String, latch),
                ('action', '/system/action_state', Int32, latch),
                ('control', '/system/control_mode', Int32, latch),
                ('active', '/navigation/goal_active', Bool, latch),
                ('enabled', '/navigation/enabled', Bool, latch),
                ('feedback', '/navigation/feedback', String, 10),
                ('pitch_deg', '/body/pitch_deg', Float64, 10),
                ('gimbal_target', '/servo3/target_deg', Float64, 10)]:
            self.create_subscription(typ, topic, lambda msg, k=key: self.value(k, msg), qos)
        for key, topic in [('nav_velocity', '/nav/cmd_vel'), ('drive_velocity', '/drive/cmd_vel'), ('manual_velocity', '/manual/cmd_vel')]:
            self.create_subscription(Twist, topic, lambda msg, k=key: self.receive(k, msg), 10)
        self.create_subscription(JointState, '/joint_states', self.receive_joints, qos_profile_sensor_data)
        self.create_subscription(JointState, '/dxl_joint_states', self.receive_joints, qos_profile_sensor_data)
        self.nav_lifecycle = LifecycleReadiness(self)
        self.create_timer(1.0, lambda: self.nav_lifecycle.poll() if self.mode == "navigation" else None)
        self.create_timer(1.0, self.detect_mode)
        self.goal_pub = self.create_publisher(PoseStamped, '/goal_pose', 10)
        self.relative_goal_pub = self.create_publisher(PoseStamped, '/relative_goal_pose', 10)
        self.initial_pub = self.create_publisher(PoseWithCovarianceStamped, '/initialpose', 10)
        self.mode_pub = self.create_publisher(Int32, '/NAVIGATION_MODE', 10)
        self.local_pose = LocalPoseSearch(self)
        self.auto_alignment = PeriodicAlignment(self)
        self.create_timer(0.05, self.process_commands)
        self.create_timer(0.2, self.refresh)

    def destroy_node(self):
        self.local_pose.close()
        self.auto_alignment.close()
        return super().destroy_node()

    def detect_mode(self):
        if self.requested_mode != 'auto':
            return
        names = {name for name, _ in self.get_node_names_and_namespaces()}
        self.mode = 'navigation' if 'named_goal_bridge' in names else 'mapping' if 'cartographer_node' in names else 'monitor'

    def receive_joints(self, message):
        stamp = Time.from_msg(message.header.stamp).nanoseconds / 1e9
        for i, name in enumerate(message.name):
            if i < len(message.position) and math.isfinite(message.position[i]):
                velocity = message.velocity[i] if i < len(message.velocity) and math.isfinite(message.velocity[i]) else None
                self.joints[name] = dict(position=message.position[i], velocity=velocity, stamp=stamp)

    def receive(self, key, message):
        self.messages[key] = message
        if key == 'scan':
            self.scans.append(message)
        now = time.monotonic()
        self.arrivals[key] = now
        self.rates.setdefault(key, deque(maxlen=30)).append(now)

    def value(self, key, message):
        self.values[key] = message.data
        if key=='goal_status':self.goal_revision+=1
        self.arrivals[key] = time.monotonic()

    def receive_map(self, msg):
        info = msg.info
        if (msg.header.frame_id != 'map' or not 0 < info.resolution < 100 or
                not 0 < info.width*info.height <= 16000000 or len(msg.data) != info.width*info.height):
            return
        data = np.asarray(msg.data, dtype=np.int8)
        signature = (zlib.crc32(data.tobytes()), info.width, info.height, info.resolution,
                     info.origin.position.x, info.origin.position.y, yaw(info.origin.orientation))
        self.arrivals['map'] = time.monotonic()
        if signature == self.map_signature:
            return
        pixels = np.where(data < 0, 205, 250-(np.clip(data, 0, 100)*2.2)).astype(np.uint8)
        output = io.BytesIO()
        Image.fromarray(np.flipud(pixels.reshape(info.height, info.width))).save(output, format='PNG')
        self.map_message = msg
        self.map_signature = signature
        self.map_version += 1
        self.map_info = dict(width=info.width, height=info.height, resolution=info.resolution,
                             origin=[info.origin.position.x, info.origin.position.y, yaw(info.origin.orientation)],
                             version=self.map_version)
        known=np.argwhere(data.reshape(info.height,info.width)>=0)
        if len(known):
            lo=known.min(axis=0);hi=known.max(axis=0)+1
            self.map_info['known_bounds']=[float(lo[1]*info.resolution),float(lo[0]*info.resolution),float(hi[1]*info.resolution),float(hi[0]*info.resolution)]
        with self.lock:
            self.map_png = output.getvalue()

    def age(self, key):
        msg = self.messages.get(key)
        if msg is None:
            return None
        if hasattr(msg, 'header'):
            return (self.get_clock().now()-Time.from_msg(msg.header.stamp)).nanoseconds/1e9
        return time.monotonic()-self.arrivals[key]

    def tf_pose(self, target, source, stamp=None):
        tf = self.buffer.lookup_transform(target, source, stamp or Time())
        p, q = tf.transform.translation, tf.transform.rotation
        return [p.x, p.y, yaw(q)]

    def readiness(self):
        problems = []
        if self.auto_alignment.busy:
            problems.append('자동 지도 보정 적용 중')
        if self.local_pose.stage not in ('idle','ready'):
            problems.append(self.local_pose.status['message'])
        if self.mode != 'navigation':
            problems.append('현재 세션은 주행 모드가 아닙니다')
        if self.mode == 'navigation':
            problems.extend(self.nav_lifecycle.problems())
        if self.map_message is None:
            problems.append('지도 미수신')
        for key, limit in [('scan', .8), ('odom', .5)]:
            age = self.age(key)
            if age is None or not -.05 <= age <= limit:
                problems.append(key+' 미수신/지연')
        if self.values.get('action') not in (0, 1):
            problems.append('로봇 제어 미준비 또는 보호 정지')
        try:
            tf = self.buffer.lookup_transform('map', 'odom', Time())
            age = (self.get_clock().now()-Time.from_msg(tf.header.stamp)).nanoseconds/1e9
            if not -1.1 <= age <= 1.5:
                problems.append('지도 위치 추정 지연')
        except TransformException:
            problems.append('초기 위치를 지정하세요')
        if self.goal_pub.get_subscription_count() == 0:
            problems.append('좌표 목표 브리지 미연결 (--goal-source web)')
        return problems

    def refresh(self):
        if self.owner and time.monotonic() > self.lease_until:
            self.stop()
        sensors = {}
        for key in ('scan', 'odom', 'imu'):
            times = self.rates.get(key, [])
            hz = (len(times)-1)/(times[-1]-times[0]) if len(times)>1 and times[-1]>times[0] else 0
            age = self.age(key)
            sensors[key] = dict(age=age, hz=hz if age is not None and age < 1 else 0)
        frame = 'map' if self.map_info else 'odom'
        robot = None
        try:
            if self.age('odom') is None or not -.05 <= self.age('odom') <= .5:
                raise TransformException('Odometry unavailable')
            robot = self.tf_pose(frame, 'base_link')
        except TransformException:
            # Keep the map selectable for relocalization. Without a map, render
            # raw sensor coordinates; never overlay them on a map without TF.
            if not self.map_info:
                scan = self.messages.get('scan')
                frame = scan.header.frame_id if scan else 'laser'
                try:
                    robot = self.tf_pose(frame, 'base_link')
                except TransformException:
                    robot = None
        scan_points = []
        scan = None
        scan_error = None
        p = None
        for candidate in reversed(self.scans):
            age = (self.get_clock().now()-Time.from_msg(candidate.header.stamp)).nanoseconds/1e9
            if not -.05 <= age < .8:
                continue
            try:
                p = self.tf_pose(frame, candidate.header.frame_id, Time.from_msg(candidate.header.stamp))
                scan = candidate
                break
            except TransformException:
                scan_error = '스캔 측정 시각의 TF 대기'
        if scan is not None:
            try:
                scan_error = None
                indices = np.arange(0, len(scan.ranges), max(1, math.ceil(len(scan.ranges)/1200)))
                ranges = np.asarray(scan.ranges)[indices]
                valid = np.isfinite(ranges) & (ranges>=scan.range_min) & (ranges<=scan.range_max)
                angles = p[2]+scan.angle_min+indices[valid]*scan.angle_increment
                scan_points = np.column_stack((p[0]+ranges[valid]*np.cos(angles), p[1]+ranges[valid]*np.sin(angles))).round(4).tolist()
            except TransformException:
                scan_error = '스캔 측정 시각의 TF 대기'
        paths = {}
        for key in ('plan', 'local_plan'):
            path = self.messages.get(key)
            if path and self.age(key) < 5:
                try:
                    p = self.tf_pose(frame, path.header.frame_id, Time.from_msg(path.header.stamp))
                    c, s = math.cos(p[2]), math.sin(p[2])
                    paths[key] = [[p[0]+c*x.pose.position.x-s*x.pose.position.y,
                                   p[1]+s*x.pose.position.x+c*x.pose.position.y] for x in path.poses[::max(1,len(path.poses)//1000)]]
                except TransformException:
                    pass
        velocities = {}
        for key in ('nav_velocity', 'drive_velocity', 'manual_velocity'):
            msg = self.messages.get(key)
            velocities[key] = [msg.linear.x, msg.angular.z] if msg and self.age(key)<.5 else None
        now = self.get_clock().now().nanoseconds / 1e9
        joints = {key: dict(position=value['position'], velocity=value['velocity'], age=now-value['stamp'])
                  for key, value in self.joints.items()}
        feedback = self.messages.get('hardware_feedback')
        feedback_age = self.age('hardware_feedback')
        hardware = {'fresh': False, 'feedback_age': {}}
        if feedback and feedback_age is not None and -.05 <= feedback_age < .5:
            for name, values in zip(feedback.joint_names, feedback.interface_values):
                fields = dict(zip(values.interface_names, values.values))
                age = fields.get('feedback_age', math.inf)
                hardware['feedback_age'][name] = age
                if name in joints:
                    joints[name]['feedback_age'] = age
            hardware['fresh'] = all(math.isfinite(hardware['feedback_age'].get(name, math.inf)) and
                                    0 <= hardware['feedback_age'][name] < .2
                                    for name in ('left_wheel_joint', 'right_wheel_joint'))
        wheel_control = {}
        message = self.messages.get('wheel_control')
        if message and self.age('wheel_control') < .5:
            for name, values in zip(message.joint_names, message.interface_values):
                wheel_control[name] = dict(zip(values.interface_names, values.values))
        state = dict(instance_id=self.instance_id, joints=joints, wheel_control=wheel_control, hardware=hardware, connected=True, mode=self.mode, frame=frame, robot=robot,
                     map=self.map_info if frame=='map' else None, map_available=self.map_info is not None, scan=scan_points, scan_error=scan_error, paths=paths,
                     sensors=sensors, values=self.values.copy(), velocities=velocities,
                     localization=self.local_pose.status.copy(),
                     auto_alignment=self.auto_alignment.snapshot(),
                     readiness=self.readiness(), goal=self.selected_goal,
                     goal_name=self.selected_goal_name, goal_kind=self.selected_goal_kind, destinations=self.goal_store.list(map_key(self.map_signature)),
                     goal_revision=self.goal_revision,
                     control_owner=self.owner, lease_remaining=max(0, self.lease_until-time.monotonic()))
        # Never send invalid JSON if a sensor supplies a nonfinite scalar.
        with self.lock:
            self.snapshot = sanitize(state)
            self.snapshot_time = time.monotonic()

    def stop(self):
        self.mode_pub.publish(Int32(data=0))
        self.owner = None
        self.lease_until = 0

    def process_commands(self):
        self.local_pose.tick()
        for _ in range(min(8, self.commands.qsize())):
            data, future = self.commands.get_nowait()
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = self.command(data)
            except Exception as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)
        self.auto_alignment.tick()

    def command(self, data):
        action = data.get('action')
        client = data.get('client')
        if action not in ('stop', 'enable', 'heartbeat', 'goal', 'initial_pose','save_destination','delete_destination','named_goal','relative_goal'):
            raise ValueError('Unknown command')
        if not isinstance(client, str) or not 8 <= len(client) <= 80:
            raise ValueError('Invalid browser session')
        if action == 'stop':
            self.stop()
            return {'ok': True, 'message': '목표 취소·AUTO 정지를 요청했습니다'}
        if self.mode != 'navigation':
            raise ValueError('주행 세션에서만 사용할 수 있습니다')
        if action=='save_destination':
            x,y,a=pose_values(data);free_cell(self.map_message,x,y)
            goal=self.goal_store.save(map_key(self.map_signature),data.get('name'),[x,y,a],data.get('id'))
            return {'ok':True,'message':'목표 위치를 저장했습니다','destination':goal}
        if action=='delete_destination':
            self.goal_store.delete(map_key(self.map_signature),data.get('id'))
            return {'ok':True,'message':'목표 위치를 삭제했습니다'}
        if action == 'heartbeat':
            if self.owner != client:
                raise ValueError('이 브라우저에 주행 제어권이 없습니다')
            self.lease_until = time.monotonic()+10
            return {'ok': True}
        if self.owner and self.owner != client:
            raise ValueError('다른 브라우저가 주행을 제어 중입니다')
        if action == 'initial_pose':
            if self.values.get('active'):
                raise ValueError('목표를 취소한 뒤 초기 위치를 지정하세요')
            x, y, a = pose_values(data)
            manual=self.messages.get('manual_velocity')
            if self.values.get('control')==0 and manual and max(abs(manual.linear.x),abs(manual.angular.z))>.01:
                raise ValueError('스틱을 중립에 놓고 초기 위치를 적용하세요')
            self.local_pose.start([x,y,a])
            self.stop()
            return {'ok': True, 'message': '주변 위치·방향 탐색을 시작했습니다'}
        problems = self.readiness()
        if problems:
            raise ValueError(' / '.join(problems))
        if action == 'enable':
            self.owner, self.lease_until = client, time.monotonic()+10
            self.mode_pub.publish(Int32(data=1))
            return {'ok': True, 'message': '주행 활성화 요청'}
        if self.owner != client or not self.values.get('enabled'):
            raise ValueError('먼저 주행을 활성화하세요')
        goal_name=None;goal_kind='destination'
        if action=='named_goal':
            destination=self.goal_store.get(map_key(self.map_signature),data.get('id'))
            data=destination;goal_name=destination['name']
        if action=='relative_goal':
            distance=forward_distance(data.get('distance_m'))
            retry=json.loads(self.values.get('retry','{}'))
            if self.values.get('active') or retry.get('state')=='waiting':
                raise ValueError('Stop the current trip before requesting a relative move.')
            odom=self.messages.get('odom')
            if odom is None or abs(odom.twist.twist.linear.x)>.04 or abs(odom.twist.twist.angular.z)>.1:
                raise ValueError('Wait for Dori to stop before requesting a relative move.')
            x,y,a=forward_goal(self.tf_pose('map','base_link'),distance)
            goal_name=f'{distance:g} m forward';goal_kind='relative'
        else:x, y, a = pose_values(data)
        free_cell(self.map_message, x, y)
        msg = PoseStamped()
        msg.header.frame_id = 'map'
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.pose.position.x, msg.pose.position.y = x, y
        msg.pose.orientation.z, msg.pose.orientation.w = math.sin(a/2), math.cos(a/2)
        self.last_goal_request=time.monotonic()
        (self.relative_goal_pub if action=='relative_goal' else self.goal_pub).publish(msg)
        self.selected_goal = [x, y, a]
        self.selected_goal_name=goal_name;self.selected_goal_kind=goal_kind
        result={'ok': True, 'message': '목표 전달 — 승인 상태를 확인하세요','goal_revision':self.goal_revision}
        if action=='relative_goal':result.update(reply=forward_reply(distance),target=[x,y,a])
        return result


def sanitize(value):
    """A bad scalar must not freeze every sensor in the viewer."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(item) for item in value]
    return value

"""Read-only ROS startup checks. No goals, actuator commands or lifecycle changes."""
from concurrent.futures import ThreadPoolExecutor
import json
import math
import time
import urllib.request

import rclpy
from rclpy.action import ActionClient
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from rclpy.time import Time
from control_msgs.msg import DynamicJointState
from controller_manager_msgs.srv import ListControllers, ListHardwareComponents
from lifecycle_msgs.srv import GetState
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Image, Imu, JointState, LaserScan
from std_msgs.msg import String
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener
from dori_msgs.action import LLMQuery, Speak, NavigateNamed
from .readiness import StartupReadiness

NAVIGATION_NODES = ("controller_server", "planner_server", "behavior_server", "bt_navigator", "velocity_smoother")
CONTROLLERS = {"joint_state_broadcaster", "left_bldc_drive_controller", "right_bldc_drive_controller"}


def component(problems):
    return {"state": "starting" if problems else "ready",
            "detail": "; ".join(problems) if problems else "Ready"}


def check_http(endpoints):
    problems = []
    for label, url in endpoints:
        try:
            with urllib.request.urlopen(url, timeout=.5) as response:
                if response.status != 200:
                    problems.append(label + " HTTP unavailable")
                elif label == "map viewer":
                    state = json.load(response)
                    if (not isinstance(state, dict) or state.get("mode") != "navigation"
                            or not isinstance(state.get("server_age"), (int, float))
                            or not 0 <= state["server_age"] <= 5):
                        problems.append("map viewer ROS state unavailable")
                else:
                    response.read(128)
        except (OSError, ValueError):
            problems.append(label + " HTTP unavailable")
    return problems


class ReadinessMonitor(Node):
    def __init__(self):
        super().__init__("bringup_readiness")
        settings = {"startup_timeout": 120.0, "enable_hri": True, "enable_dashboard": True,
                    "enable_stt": False, "visitor_mode": True, "enable_rear_camera": False}
        for key, default in settings.items():
            settings[key] = self.declare_parameter(key, default).value
        self.settings = settings
        self.gate = StartupReadiness(settings["startup_timeout"], time.monotonic())
        self.buffer = Buffer()
        self.listener = TransformListener(self.buffer, self)
        self.samples = {}
        self.limits = {}
        self.queries = {}
        self.results = {}
        self.ns = self.get_namespace().rstrip("/")
        self.failure = None
        self.last_log = None
        self.log_at = 0.0
        self.status = self.create_publisher(String, "bringup/status", QoSProfile(
            depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        for name, topic, typ, limit in (
            ("lidar", "/scan", LaserScan, 1.0),
            ("imu", "/imu/data_raw", Imu, 1.0),
            ("odometry", "/odom", Odometry, 1.0),
            ("wheels", "/joint_states", JointState, 1.0),
            ("can_feedback", "/dynamic_joint_states", DynamicJointState, 1.0),
            ("servos", "/dxl_joint_states", JointState, 1.0),
            ("front_color", self.ns + "/camera/front/color/image_raw", Image, 2.0),
            ("front_depth", self.ns + "/camera/front/depth/image_raw", Image, 2.0),
            ("persons", self.ns + "/hri/persons", String, 5.0),
        ):
            self.subscribe(name, topic, typ, limit)
        if settings["enable_rear_camera"]:
            self.subscribe("rear_color", self.ns + "/camera/rear/color/image_raw", Image, 2.0)
            self.subscribe("rear_depth", self.ns + "/camera/rear/depth/image_raw", Image, 2.0)
        for name, service, typ in (
            ("controllers", "/controller_manager/list_controllers", ListControllers),
            ("hardware", "/controller_manager/list_hardware_components", ListHardwareComponents),
            *((name, "/" + name + "/get_state", GetState)
              for name in ("map_server", "amcl", *NAVIGATION_NODES)),
        ):
            self.add_query(name, service, typ)
        self.actions = {}
        self.hri_services = []
        if settings["enable_hri"]:
            for name, typ in (("llm/query", LLMQuery), ("tts/speak", Speak), ("nav/navigate_named", NavigateNamed)):
                self.actions[name] = ActionClient(self, typ, self.ns + "/" + name)
            names = ["llm/reset", "tts/remote_reset", "bt/clear_session"]
            if settings["enable_stt"]:
                names.append("stt/reset")
            self.hri_services = [(name, self.create_client(Trigger, self.ns + "/" + name)) for name in names]
            if settings["visitor_mode"]:
                self.add_query("visitor", self.ns + "/bt/visitor_ready", Trigger)
        self.endpoints = [("map viewer", "http://127.0.0.1:8080/api/state")]
        if settings["enable_dashboard"]:
            self.endpoints += [("dashboard", "http://127.0.0.1:3000/"),
                               ("display", "http://127.0.0.1:3001/display"),
                               ("visitor app", "http://127.0.0.1:3100/")]
        self.http_pool = ThreadPoolExecutor(max_workers=1)
        self.http_future = None
        self.http_result = None
        self.http_at = 0.0
        self.timer = self.create_timer(.5, self.tick)

    def subscribe(self, name, topic, typ, limit):
        self.limits[name] = limit
        self.create_subscription(typ, topic, lambda msg: self.receive(name, msg), qos_profile_sensor_data)

    def receive(self, name, msg):
        now = time.monotonic()
        if hasattr(msg, "header"):
            age = (self.get_clock().now() - Time.from_msg(msg.header.stamp)).nanoseconds / 1e9
            if not -.1 <= age <= self.limits[name]:
                return
        if name == "lidar" and not any(math.isfinite(x) and msg.range_min <= x <= msg.range_max for x in msg.ranges):
            return
        if name == "imu" and not all(math.isfinite(v) for v in (
                msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z,
                msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z)):
            return
        if name == "odometry":
            pose = msg.pose.pose
            if (msg.header.frame_id != "odom" or msg.child_frame_id != "base_link"
                    or not all(math.isfinite(v) for v in (
                        pose.position.x, pose.position.y, pose.position.z,
                        pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w))):
                return
        if isinstance(msg, Image) and (not msg.width or not msg.height or not msg.data):
            return
        if name == "persons":
            try:
                data = json.loads(msg.data)
                if not isinstance(data, dict) or not isinstance(data.get("detections"), list):
                    return
            except ValueError:
                return
        if name in ("wheels", "servos"):
            expected = ("left_wheel_joint", "right_wheel_joint") if name == "wheels" else ("motor_3_joint", "motor_5_joint")
            for joint, position in zip(msg.name, msg.position):
                if joint in expected and math.isfinite(position):
                    self.samples[joint] = now
            if any(now - self.samples.get(joint, -math.inf) > self.limits[name] for joint in expected):
                return
        if name == "can_feedback":
            try:
                for joint in ("left_wheel_joint", "right_wheel_joint"):
                    values = msg.interface_values[msg.joint_names.index(joint)]
                    age = values.values[values.interface_names.index("feedback_age")]
                    if not math.isfinite(age) or not 0 <= age <= .2:
                        return
            except (ValueError, IndexError):
                return
        self.samples[name] = now

    def add_query(self, name, service, typ):
        self.queries[name] = {"client": self.create_client(typ, service), "type": typ,
                              "future": None, "sent": -math.inf}

    def poll(self, now):
        for name, query in self.queries.items():
            future = query["future"]
            if future is not None:
                if future.done():
                    try:
                        result = future.result()
                        if result is not None:
                            self.results[name] = (now, result)
                    except Exception:
                        self.results.pop(name, None)
                    query["future"] = None
                elif now - query["sent"] >= 3:
                    query["client"].remove_pending_request(future)
                    future.cancel()
                    query["future"] = None
            if query["future"] is None and now - query["sent"] >= 1 and query["client"].service_is_ready():
                query["future"] = query["client"].call_async(query["type"].Request())
                query["sent"] = now
        if self.http_future is not None and self.http_future.done():
            self.http_result = self.http_future.result()
            self.http_at = now
            self.http_future = None
        if self.http_future is None and now - self.http_at >= 2:
            self.http_future = self.http_pool.submit(check_http, self.endpoints)

    def result(self, name, now):
        timestamp, result = self.results.get(name, (-math.inf, None))
        return result if now - timestamp <= 5 else None

    def fresh_transform(self, parent, child):
        try:
            transform = self.buffer.lookup_transform(parent, child, Time())
            age = (self.get_clock().now() - Time.from_msg(transform.header.stamp)).nanoseconds / 1e9
            return -1.5 <= age <= 2
        except TransformException:
            return False

    def snapshot(self, now):
        missing = lambda names: [name + " data missing/stale" for name in names
                                 if now - self.samples.get(name, -math.inf) > self.limits[name]]
        components = {"sensors": component(missing(("lidar", "imu", "wheels", "servos", "can_feedback")))}
        odometry = missing(("odometry",))
        if not self.fresh_transform("odom", "base_link"):
            odometry.append("odom -> base_link TF missing/stale")
        components["odometry"] = component(odometry)
        perception = ["front_color", "front_depth", "persons"]
        if self.settings["enable_rear_camera"]:
            perception += ["rear_color", "rear_depth"]
        components["perception"] = component(missing(perception))
        controllers = self.result("controllers", now)
        states = {c.name: c.state for c in controllers.controller} if controllers else {}
        problems = [name + " is not active" for name in sorted(CONTROLLERS) if states.get(name) != "active"]
        hardware = self.result("hardware", now)
        if not hardware or not any(c.name == "CubeMarsSystem" and c.state.id == 3 for c in hardware.component):
            problems.append("CubeMarsSystem hardware is not active")
        components["controllers"] = component(problems)
        active = lambda name: self.result(name, now) is not None and self.result(name, now).current_state.id == 3
        components["localization"] = component([name + " is not active" for name in ("map_server", "amcl") if not active(name)])
        components["navigation_services"] = component([name + " state service unavailable" for name in NAVIGATION_NODES if self.result(name, now) is None])
        hri = [name + " action unavailable" for name, client in self.actions.items() if not client.server_is_ready()]
        hri += [name + " service unavailable" for name, client in self.hri_services if not client.service_is_ready()]
        if self.settings["enable_hri"] and self.settings["visitor_mode"]:
            visitor = self.result("visitor", now)
            if not visitor or not visitor.success:
                hri.append("BT visitor profile is not ready")
        components["hri"] = component(hri)
        components["apps"] = component(self.http_result if self.http_result is not None and now - self.http_at <= 5 else ["HTTP services not ready"])
        return self.gate.update(now, components, localized=self.fresh_transform("map", "base_link"),
                                navigation_ready=all(active(name) for name in NAVIGATION_NODES))

    def tick(self):
        now = time.monotonic()
        self.poll(now)
        report = self.snapshot(now)
        self.status.publish(String(data=json.dumps(report, ensure_ascii=False)))
        summary = " | ".join(f"{name}={item['state']} ({item['detail']})"
                             for name, item in report["components"].items())
        if summary != self.last_log or now - self.log_at >= 15:
            self.get_logger().info("Robot readiness: " + summary)
            self.last_log, self.log_at = summary, now
        if report["errors"]:
            self.failure = "; ".join(report["errors"])
            self.get_logger().error("Robot startup failed: " + self.failure)
            self.timer.cancel()


def main():
    rclpy.init()
    node = ReadinessMonitor()
    try:
        while rclpy.ok() and node.failure is None:
            rclpy.spin_once(node, timeout_sec=.5)
        return 1 if node.failure else 0
    except (KeyboardInterrupt, ExternalShutdownException):
        return 0
    finally:
        node.http_pool.shutdown(wait=True, cancel_futures=True)
        node.destroy_node()
        rclpy.try_shutdown()

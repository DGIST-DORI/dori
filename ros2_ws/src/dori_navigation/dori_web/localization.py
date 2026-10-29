"""Asynchronous coarse initial pose -> scan-map search -> stationary AMCL update."""

import math
import time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from geometry_msgs.msg import PoseWithCovarianceStamped
from std_srvs.srv import Trigger, Empty
from rclpy.time import Time
from rclpy.qos import qos_profile_sensor_data
from .geometry import yaw
from .map_matcher import MapMatcher


def base_scan_points(node, scan):
    tf = node.buffer.lookup_transform(
        "base_link", scan.header.frame_id, Time.from_msg(scan.header.stamp)
    )
    p = tf.transform.translation
    a = yaw(tf.transform.rotation)
    ranges = np.asarray(scan.ranges)
    angle = scan.angle_min + np.arange(len(ranges)) * scan.angle_increment
    valid = (
        np.isfinite(ranges)
        & (ranges > max(0.3, scan.range_min))
        & (ranges < min(12.0, scan.range_max))
    )
    return np.column_stack(
        (
            ranges[valid] * np.cos(angle[valid] + a) + p.x,
            ranges[valid] * np.sin(angle[valid] + a) + p.y,
        )
    )


class LocalPoseSearch:
    def __init__(self, node):
        self.node = node
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.status = {"state": "idle", "message": ""}
        self.task = None
        self.stage = "idle"
        self.reset = node.create_client(Trigger, "/lidar_odometry/reset_reference")
        self.nomotion = node.create_client(Empty, "/request_nomotion_update")
        self.amcl = None
        self.pending = None
        self.last_request = 0.0
        self.result = None
        node.create_subscription(
            PoseWithCovarianceStamped,
            "/amcl_pose",
            self.receive_amcl,
            qos_profile_sensor_data,
        )

    def receive_amcl(self, msg):
        self.amcl = msg

    def close(self):
        self.worker.shutdown(wait=False, cancel_futures=True)

    def stationary(self):
        n = self.node
        manual = n.messages.get("manual_velocity")
        if (
            n.values.get("control") == 0
            and manual
            and max(abs(manual.linear.x), abs(manual.angular.z)) > 0.01
        ):
            return False
        return all(
            name in n.joints
            and abs(math.remainder(n.joints[name]["position"] - position, 8 * math.pi))
            < 0.15
            for name, position in self.wheels.items()
        )

    def start(self, pose):
        if self.stage not in ("idle", "ready", "failed"):
            raise ValueError("주변 위치를 탐색 중입니다")
        if self.pending is not None:
            self.pending.cancel()
            self.pending = None
        n = self.node
        scan = n.messages.get("scan")
        grid = n.map_message
        if (
            scan is None
            or n.age("scan") is None
            or not 0 <= n.age("scan") < 0.8
            or grid is None
        ):
            raise ValueError("지도와 최신 LiDAR가 필요합니다")
        points = base_scan_points(n, scan)
        data = (
            np.asarray(grid.data, dtype=np.int16)
            .reshape(grid.info.height, grid.info.width)
            .copy()
        )
        origin = [
            grid.info.origin.position.x,
            grid.info.origin.position.y,
            yaw(grid.info.origin.orientation),
        ]

        def search():
            return MapMatcher(data, grid.info.resolution, origin).search(points, pose)

        self.task = self.worker.submit(search)
        self.stage = "searching"
        self.started = time.monotonic()
        self.wheels = {
            name: item["position"]
            for name, item in n.joints.items()
            if name in ("left_wheel_joint", "right_wheel_joint")
        }
        self.map_version = n.map_version
        self.status = {
            "state": self.stage,
            "message": "선택한 위치 주변 1.5m에서 위치·방향을 찾는 중",
        }

    def fail(self, message):
        self.stage = "failed"
        self.status = {"state": "failed", "message": message}

    def tick(self):
        n = self.node
        now = time.monotonic()
        if self.stage in ("idle", "ready", "failed"):
            return
        if now - self.started > 30:
            self.fail("위치 탐색 시간이 초과됐습니다")
            return
        if not self.stationary():
            self.fail("위치 탐색 중 로봇이 움직였습니다. 정지 후 다시 적용하세요")
            return
        if self.stage == "searching" and self.task.done():
            try:
                self.result = self.task.result()
            except Exception as e:
                self.fail(str(e))
                return
            if n.map_version != self.map_version:
                self.fail("지도가 변경됐습니다. 초기 위치를 다시 적용하세요")
                return
            self.stage = "resetting"
            self.status = {
                "state": self.stage,
                "message": "지도와 일치하는 위치를 찾았습니다. LiDAR 기준을 연결하는 중",
                **self.result,
            }
        if self.stage == "resetting":
            if self.pending is None:
                if not self.reset.service_is_ready():
                    return
                self.reset_stamp = n.get_clock().now().nanoseconds / 1e9
                self.pending = self.reset.call_async(Trigger.Request())
                return
            if not self.pending.done():
                return
            try:
                response = self.pending.result()
            except Exception as exc:
                self.pending = None
                self.fail("LiDAR 기준 초기화 실패: " + str(exc))
                return
            self.pending = None
            if not response.success:
                self.fail(response.message)
                return
            self.stage = "waiting_odom"
        if self.stage == "waiting_odom":
            odom = n.messages.get("odom")
            if (
                odom is None
                or Time.from_msg(odom.header.stamp).nanoseconds / 1e9 < self.reset_stamp
                or n.age("odom") > 0.5
            ):
                return
            x, y, a = self.result["pose"]
            msg = PoseWithCovarianceStamped()
            msg.header.frame_id = "map"
            msg.header.stamp = n.get_clock().now().to_msg()
            msg.pose.pose.position.x = x
            msg.pose.pose.position.y = y
            msg.pose.pose.orientation.z = math.sin(a / 2)
            msg.pose.pose.orientation.w = math.cos(a / 2)
            msg.pose.covariance[0] = msg.pose.covariance[7] = 0.15**2
            msg.pose.covariance[35] = (
                math.radians(10 if self.result["ambiguous"] else 5) ** 2
            )
            n.initial_pub.publish(msg)
            self.initial_stamp = n.get_clock().now().nanoseconds / 1e9
            self.stage = "refining"
            self.refine_started = now
            self.amcl = None
            self.updates = 0
            self.status = {
                "state": "refining",
                "message": "정지 상태에서 지도 위치를 정밀 보정하는 중",
                **self.result,
            }
        if self.stage == "refining":
            if self.pending is not None and self.pending.done():
                try:
                    self.pending.result()
                    self.updates += 1
                except Exception as exc:
                    self.pending = None
                    self.fail("지도 보정 실패: " + str(exc))
                    return
                self.pending = None
            if (
                self.pending is None
                and now - self.last_request > 0.4
                and self.nomotion.service_is_ready()
            ):
                self.pending = self.nomotion.call_async(Empty.Request())
                self.last_request = now
            fresh = (
                self.amcl is not None
                and Time.from_msg(self.amcl.header.stamp).nanoseconds / 1e9
                > self.initial_stamp
            )
            if (
                now - self.refine_started > 3
                and fresh
                and self.updates >= 3
                and n.age("odom") is not None
                and n.age("odom") < 0.5
            ):
                label = "주변 위치 탐색·지도 정합 완료"
                if self.result["ambiguous"]:
                    label += " · 비슷한 후보가 있어 대략 지정한 방향을 참고했습니다"
                self.stage = "ready"
                self.status = {"state": "ready", "message": label, **self.result}

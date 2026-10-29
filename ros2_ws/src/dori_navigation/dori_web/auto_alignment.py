"""Periodic, bounded AMCL correction while the robot is idle.

Never commands motion or resets LiDAR odometry. Manual localization takes
priority; a search result is discarded if motion, map or pose changes.
"""

from concurrent.futures import ThreadPoolExecutor
import json
import math
import time
import numpy as np
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.time import Time
from std_msgs.msg import String
from std_srvs.srv import Empty
from .geometry import yaw
from .localization import base_scan_points
from .map_matcher import MapMatcher


def difference(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1]), abs(
        math.remainder(a[2] - b[2], 2 * math.pi)
    )


def alignment_candidate(matcher, scans, initial):
    """Require agreement and improved fit in each of three separate scans."""
    results = [matcher.refine(points, initial) for points in scans]
    poses = np.asarray([r["pose"] for r in results])
    center = np.median(poses, axis=0)
    center[2] = math.atan2(np.sin(poses[:, 2]).mean(), np.cos(poses[:, 2]).mean())
    distances = [difference(p, center) for p in poses]
    score = min(r["score"] for r in results)
    fraction = min(r["matched_fraction"] for r in results)
    improvement = min(r["score"] - r["current_score"] for r in results)
    translation, angle = difference(center, initial)
    result = dict(
        pose=center.tolist(),
        score=score,
        matched_fraction=fraction,
        improvement=improvement,
        translation_m=translation,
        rotation_deg=math.degrees(angle),
    )
    if (
        any(r["ambiguous"] for r in results)
        or max(d[0] for d in distances) > 0.08
        or max(d[1] for d in distances) > math.radians(3)
    ):
        return dict(
            result,
            decision="uncertain",
            message="자동 정합 보류 · 여러 스캔의 후보가 불확실합니다",
        )
    if score < 0.65 or fraction < 0.75:
        return dict(
            result,
            decision="uncertain",
            message="자동 정합 보류 · 지도와 라이다의 일치도가 낮습니다",
        )
    if translation > 0.30 or angle > math.radians(8):
        return dict(
            result,
            decision="manual_required",
            message="자동 보정 범위를 넘었습니다 · 초기 위치를 확인하세요",
        )
    if translation < 0.04 and angle < math.radians(1):
        return dict(
            result,
            decision="aligned",
            message="자동 점검 · 현재 위치의 지도 정합이 양호합니다",
        )
    if improvement < 0.035:
        return dict(
            result,
            decision="aligned",
            message="자동 점검 · 유의미한 개선이 없어 현재 위치를 유지합니다",
        )
    # Verify the consensus pose itself, not just each scan's optimum.
    for points in scans:
        sample = points[:: max(1, math.ceil(len(points) / 180))]
        scores, fractions = matcher.scores(np.asarray([initial, center]), sample)
        if scores[1] < 0.65 or fractions[1] < 0.75 or scores[1] - scores[0] < 0.035:
            return dict(
                result,
                decision="uncertain",
                message="자동 정합 보류 · 공통 후보를 확인하지 못했습니다",
            )
    return dict(
        result,
        decision="correct",
        message="여러 스캔에서 일치하는 작은 위치 보정을 찾았습니다",
    )


class PeriodicAlignment:
    def __init__(self, node):
        self.node = node
        self.enabled = node.declare_parameter("auto_alignment.enabled", True).value
        self.period = float(
            node.declare_parameter("auto_alignment.period_s", 30.0).value
        )
        if not math.isfinite(self.period) or self.period < 5:
            raise ValueError("auto_alignment.period_s must be >= 5")
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.task = None
        self.reference = None
        self.next_check = time.monotonic() + self.period
        self.still_since = None
        self.checked = 0
        self.applied = 0
        self.last_applied = None
        self.hold_until = 0.0
        self.last_result = None
        self.last_checked = None
        self.defer_reason = "정지 확인 중"
        self.awaiting = None
        self.status = {
            "state": "waiting",
            "message": f"자동 정합 · 정지 상태에서 {self.period:g}초 주기로 점검",
        }
        self.nomotion = node.create_client(Empty, "/request_nomotion_update")
        self.pending = None
        self.pending_since = 0.0
        self.publisher = node.create_publisher(
            String, "/localization/auto_alignment", 5
        )
        self.manual_generation = 0
        node.create_subscription(
            PoseWithCovarianceStamped, "/initialpose", self.initial_pose_received, 10
        )
        self.own_stamp = None
        node.create_timer(
            1.0,
            lambda: self.publisher.publish(
                String(data=json.dumps(self.snapshot(), allow_nan=False))
            ),
        )

    def close(self):
        self.worker.shutdown(wait=False, cancel_futures=True)

    def initial_pose_received(self, msg):
        if Time.from_msg(msg.header.stamp).nanoseconds == self.own_stamp:
            return
        self.manual_generation += 1
        self.next_check = time.monotonic() + self.period
        self.awaiting = None
        self.hold_until = 0.0
        self.reference = None
        self.still_since = None
        self.status = {
            "state": "waiting",
            "message": "수동 위치 적용 후 다음 자동 점검을 기다립니다",
        }

    @property
    def busy(self):
        return time.monotonic() < self.hold_until

    def snapshot(self):
        return dict(
            self.status,
            enabled=self.enabled,
            checks=self.checked,
            corrections=self.applied,
            next_check_seconds=max(0.0, self.next_check - time.monotonic()),
            last_check=self.last_result,
            last_check_age=(
                None
                if self.last_checked is None
                else time.monotonic() - self.last_checked
            ),
            last_correction_age=(
                None
                if self.last_applied is None
                else time.monotonic() - self.last_applied
            ),
        )

    def defer(self, reason):
        self.defer_reason = reason
        return None

    def idle_pose(self):
        n = self.node
        if n.mode != "navigation":
            return self.defer("주행 모드 대기")
        if n.local_pose.stage not in ("idle", "ready"):
            return self.defer("수동 위치 적용 중")
        if n.values.get("action") not in (0, 1):
            return self.defer("로봇 운용 상태 확인 필요")
        if n.values.get("active") or time.monotonic() - n.last_goal_request < 2:
            return self.defer("목표 주행 중")
        if n.nav_lifecycle.problems():
            return self.defer("위치 추정·주행 노드 준비 대기")
        if json.loads(n.values.get("retry", "{}")).get("state") == "waiting":
            return self.defer("목표 재시도 대기")
        for name in ("scan", "odom"):
            age = n.age(name)
            if age is None or not -0.05 <= age < 0.5:
                return self.defer(name + " 수신 지연")
        odom = n.messages["odom"].twist.twist
        if not all(math.isfinite(v) for v in (odom.linear.x, odom.angular.z)):
            return self.defer("오도메트리 속도 확인 필요")
        # Differentiating scan noise produced +/-0.05 m/s with fixed encoders.
        # Establish stillness from one second of pose AND wheel displacement
        # below, instead of resetting that window on each noisy velocity sample.
        for name in ("manual_velocity", "drive_velocity", "nav_velocity"):
            command = n.messages.get(name)
            if (
                command is not None
                and n.age(name) < 0.5
                and max(abs(command.linear.x), abs(command.angular.z)) > 0.01
            ):
                return self.defer("이동 명령 실행 중")
        try:
            tf = n.buffer.lookup_transform("map", "odom", Time())
            age = (
                n.get_clock().now() - Time.from_msg(tf.header.stamp)
            ).nanoseconds / 1e9
            if not -1.1 <= age < 1.5:
                return self.defer("지도 좌표 변환 수신 지연")
            return n.tf_pose("map", "base_link")
        except Exception:
            return self.defer("지도 좌표 변환 대기")

    def stationary(self, pose):
        n = self.node
        now = n.get_clock().now().nanoseconds / 1e9
        wheels = {
            name: n.joints.get(name)
            for name in ("left_wheel_joint", "right_wheel_joint")
        }
        if any(
            item is None or not 0 <= now - item["stamp"] < 0.5
            for item in wheels.values()
        ):
            self.defer_reason = "바퀴 위치 피드백 대기"
            return False
        if self.reference is None:
            self.reference = (
                pose,
                {name: item["position"] for name, item in wheels.items()},
            )
            return True
        before, positions = self.reference
        distance, angle = difference(pose, before)
        stationary = (
            distance < 0.025
            and angle < math.radians(1)
            and all(
                abs(math.remainder(wheels[name]["position"] - position, 8 * math.pi))
                < 0.08
                for name, position in positions.items()
            )
        )
        if not stationary:
            self.defer_reason = "차체·바퀴 움직임 감지"
        return stationary

    def tick(self):
        n = self.node
        now = time.monotonic()
        if not self.enabled:
            return
        if self.pending is not None and self.pending.done():
            try:
                self.pending.result()
            except Exception:
                pass
            self.pending = None
        elif self.pending is not None and now - self.pending_since > 2:
            self.nomotion.remove_pending_request(self.pending)
            self.pending.cancel()
            self.pending = None
        if self.awaiting is not None:
            expected = self.awaiting
            amcl = n.local_pose.amcl
            fresh = (
                amcl is not None
                and amcl.header.frame_id == "map"
                and Time.from_msg(amcl.header.stamp).nanoseconds > self.own_stamp
            )
            if fresh:
                p = amcl.pose.pose
                error = difference(
                    [p.position.x, p.position.y, yaw(p.orientation)], expected
                )
                try:
                    tf_error = difference(n.tf_pose("map", "base_link"), expected)
                except Exception:
                    tf_error = (math.inf, math.inf)
                if (
                    error[0] < 0.06
                    and error[1] < math.radians(2)
                    and tf_error[0] < 0.06
                    and tf_error[1] < math.radians(2)
                ):
                    self.applied += 1
                    self.last_applied = now
                    self.awaiting = None
                    self.hold_until = 0.0
                    self.status.update(
                        state="corrected",
                        message=f"자동 지도 보정 확인 · {self.status['translation_m']*100:.0f}cm / {self.status['rotation_deg']:.1f}°",
                    )
                    return
            if now >= self.hold_until:
                self.awaiting = None
                self.status.update(
                    state="unconfirmed",
                    message="자동 보정의 AMCL 반영을 확인하지 못했습니다 · 위치를 확인하세요",
                )
            elif (
                self.pending is None
                and now - self.pending_since > 0.4
                and self.nomotion.service_is_ready()
            ):
                self.pending = self.nomotion.call_async(Empty.Request())
                self.pending_since = now
            return
        pose = self.idle_pose()
        if pose is None or not self.stationary(pose):
            self.reference = None
            self.still_since = None
            if self.task is not None:
                self.task.cancel()
                self.task = None
            if now >= self.next_check:
                self.status = {
                    "state": "deferred",
                    "message": "자동 정합 대기 · " + self.defer_reason,
                }
            return
        if self.still_since is None:
            self.still_since = now
        if self.task is not None:
            if not self.task.done():
                return
            task = self.task
            self.task = None
            if (
                n.map_version != self.map_version
                or self.manual_generation != self.search_generation
                or difference(pose, self.search_pose)[0] > 0.025
                or difference(pose, self.search_pose)[1] > math.radians(1)
            ):
                self.next_check = now + self.period
                return
            self.checked += 1
            self.next_check = now + self.period
            try:
                result = task.result()
            except Exception as exc:
                self.status = {
                    "state": "uncertain",
                    "message": "자동 정합 보류 · " + str(exc),
                }
                return
            self.last_result = result.copy()
            self.last_checked = now
            self.status = dict(result, state=result["decision"])
            if result["decision"] == "correct":
                x, y, a = result["pose"]
                msg = PoseWithCovarianceStamped()
                msg.header.frame_id = "map"
                msg.header.stamp = n.get_clock().now().to_msg()
                msg.pose.pose.position.x = x
                msg.pose.pose.position.y = y
                msg.pose.pose.orientation.z = math.sin(a / 2)
                msg.pose.pose.orientation.w = math.cos(a / 2)
                msg.pose.covariance[0] = msg.pose.covariance[7] = 0.06**2
                msg.pose.covariance[35] = math.radians(3) ** 2
                self.own_stamp = Time.from_msg(msg.header.stamp).nanoseconds
                n.initial_pub.publish(msg)
                self.awaiting = result["pose"]
                self.hold_until = now + 3.0
                self.reference = None
                self.still_since = None
                self.status.update(
                    state="correcting",
                    message="자동 지도 보정 · AMCL 반영을 확인하는 중",
                )
            if (
                result["decision"] in ("correct", "aligned")
                and self.pending is None
                and self.nomotion.service_is_ready()
            ):
                self.pending = self.nomotion.call_async(Empty.Request())
                self.pending_since = now
        elif (
            now >= self.next_check
            and now - self.still_since >= 1.0
            and n.map_message is not None
        ):
            scans = list(n.scans)[-5::2]
            if len(scans) < 3:
                return
            stamps = [Time.from_msg(scan.header.stamp).nanoseconds for scan in scans]
            if (
                len(set(stamps)) != 3
                or (n.get_clock().now().nanoseconds - min(stamps)) / 1e9 > 0.8
            ):
                return
            try:
                points = [base_scan_points(n, scan) for scan in scans]
            except Exception:
                return
            grid = n.map_message
            info = grid.info
            data = (
                np.asarray(grid.data, dtype=np.int16)
                .reshape(info.height, info.width)
                .copy()
            )
            origin = [
                info.origin.position.x,
                info.origin.position.y,
                yaw(info.origin.orientation),
            ]
            self.search_pose = list(pose)
            self.map_version = n.map_version
            self.search_generation = self.manual_generation
            self.task = self.worker.submit(
                lambda: alignment_candidate(
                    MapMatcher(data, info.resolution, origin), points, pose
                )
            )
            self.status = {
                "state": "checking",
                "message": "자동 정합 · 현재 위치 주변의 라이다 스캔 3개를 대조 중",
            }

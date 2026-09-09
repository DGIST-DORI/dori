#!/usr/bin/env python3
"""Measure real C1 input throughput and the scan-to-Nav2 pipeline."""
from __future__ import annotations

import argparse
import math
import statistics
import time

import rclpy
from geometry_msgs.msg import PoseWithCovarianceStamped
from nav_msgs.msg import OccupancyGrid, Odometry, Path
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan


class PipelineMonitor(Node):
    def __init__(self) -> None:
        super().__init__("scan_pipeline_monitor")
        self.started = time.monotonic()
        self.raw_times: list[float] = []
        self.scan_times: list[float] = []
        self.scan_ages_ms: list[float] = []
        self.beam_counts: list[int] = []
        self.valid_ratios: list[float] = []
        self.downstream = {"odom": 0, "amcl_pose": 0, "plan": 0,
                           "local_costmap": 0, "global_costmap": 0}

        self.create_subscription(LaserScan, "/scan_raw", self._raw, qos_profile_sensor_data)
        self.create_subscription(LaserScan, "/scan", self._scan, qos_profile_sensor_data)
        self.create_subscription(Odometry, "/odom", self._count("odom"), qos_profile_sensor_data)
        self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose",
                                 self._count("amcl_pose"), 10)
        self.create_subscription(Path, "/plan", self._count("plan"), 10)
        self.create_subscription(OccupancyGrid, "/local_costmap/costmap",
                                 self._count("local_costmap"), 10)
        self.create_subscription(OccupancyGrid, "/global_costmap/costmap",
                                 self._count("global_costmap"), 10)

    def _count(self, name: str):
        def callback(_message) -> None:
            self.downstream[name] += 1
        return callback

    def _raw(self, _message: LaserScan) -> None:
        self.raw_times.append(time.monotonic())

    def _scan(self, message: LaserScan) -> None:
        now_mono = time.monotonic()
        self.scan_times.append(now_mono)
        stamp_ns = message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec
        now_ns = self.get_clock().now().nanoseconds
        self.scan_ages_ms.append((now_ns - stamp_ns) / 1_000_000.0)
        self.beam_counts.append(len(message.ranges))
        valid = sum(
            1 for value in message.ranges
            if math.isfinite(value) and message.range_min <= value <= message.range_max
        )
        self.valid_ratios.append(valid / len(message.ranges) if message.ranges else 0.0)

    @staticmethod
    def rate(times: list[float], duration: float) -> float:
        return len(times) / duration if duration > 0.0 else 0.0


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument("--min-hz", type=float, default=5.0)
    parser.add_argument("--min-pass-ratio", type=float, default=0.95)
    parser.add_argument("--max-p95-age-ms", type=float, default=250.0)
    args = parser.parse_args()

    rclpy.init()
    node = PipelineMonitor()
    print(f"Measuring real scan pipeline for {args.duration:.0f}s ...", flush=True)
    deadline = time.monotonic() + args.duration
    next_report = time.monotonic() + 5.0
    last_raw = last_scan = 0
    while rclpy.ok() and time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
        if time.monotonic() >= next_report:
            raw_delta = len(node.raw_times) - last_raw
            scan_delta = len(node.scan_times) - last_scan
            print(f"  5s window: scan_raw={raw_delta / 5.0:.2f} Hz, "
                  f"scan={scan_delta / 5.0:.2f} Hz", flush=True)
            last_raw, last_scan = len(node.raw_times), len(node.scan_times)
            next_report += 5.0

    elapsed = max(0.001, time.monotonic() - node.started)
    raw_hz = node.rate(node.raw_times, elapsed)
    scan_hz = node.rate(node.scan_times, elapsed)
    pass_ratio = len(node.scan_times) / len(node.raw_times) if node.raw_times else 0.0
    age_p50 = statistics.median(node.scan_ages_ms) if node.scan_ages_ms else float("nan")
    age_p95 = percentile(node.scan_ages_ms, 0.95)
    beams = statistics.median(node.beam_counts) if node.beam_counts else 0
    valid = statistics.mean(node.valid_ratios) * 100.0 if node.valid_ratios else 0.0

    print("\nC1 input and processing result")
    print(f"  /scan_raw: {len(node.raw_times)} frames, {raw_hz:.2f} Hz")
    print(f"  /scan:     {len(node.scan_times)} frames, {scan_hz:.2f} Hz")
    print(f"  raw->scan delivery: {pass_ratio * 100.0:.1f}%")
    print(f"  scan age: median={age_p50:.1f} ms, p95={age_p95:.1f} ms")
    print(f"  beams/frame median={beams}, valid-range mean={valid:.1f}%")
    print("  downstream messages: " + ", ".join(
        f"{name}={count}" for name, count in node.downstream.items()))

    failures = []
    if raw_hz < args.min_hz:
        failures.append(f"raw input {raw_hz:.2f} Hz < {args.min_hz:.2f} Hz")
    if pass_ratio < args.min_pass_ratio:
        failures.append(f"raw->scan {pass_ratio * 100:.1f}% < {args.min_pass_ratio * 100:.1f}%")
    if not math.isfinite(age_p95) or age_p95 > args.max_p95_age_ms:
        failures.append(f"scan p95 age {age_p95:.1f} ms > {args.max_p95_age_ms:.1f} ms")
    if not node.beam_counts or beams == 0:
        failures.append("scan has no range samples")

    if failures:
        print("RESULT: FAIL — " + "; ".join(failures))
        result = 1
    else:
        print("RESULT: PASS — real C1 frames are arriving and keeping up with the scan pipeline")
        result = 0

    node.destroy_node()
    rclpy.shutdown()
    raise SystemExit(result)


if __name__ == "__main__":
    main()

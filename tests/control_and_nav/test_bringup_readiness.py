"""Startup waits for actual readiness; initial pose never consumes a startup deadline."""
from unittest.mock import Mock

import pytest
from sensor_msgs.msg import Image, LaserScan
from std_msgs.msg import String
from dori_bringup.readiness import StartupReadiness
from dori_bringup.readiness_monitor import ReadinessMonitor, component


def test_initial_pose_is_normal_wait_even_after_startup_timeout():
    gate = StartupReadiness(10, 0)
    components = {"sensors": component([]), "perception": component([])}
    report = gate.update(1, components, localized=False, navigation_ready=False)
    assert report["state"] == "waiting_initial_pose"
    report = gate.update(1000, components, localized=False, navigation_ready=False)
    assert not report["errors"]
    assert report["state"] == "waiting_initial_pose"
    report = gate.update(1001, components, localized=True, navigation_ready=False)
    assert report["state"] == "starting"
    report = gate.update(1002, components, localized=True, navigation_ready=True)
    assert report["state"] == "ready"


def test_missing_camera_fails_startup_even_without_initial_pose():
    gate = StartupReadiness(10, 0)
    report = gate.update(10, {"perception": component(["front_color missing"])},
                         localized=False, navigation_ready=False)
    assert report["state"] == "failed"
    assert report["errors"] == ["perception: front_color missing"]
    assert report["components"]["navigation"]["state"] == "waiting_initial_pose"


def test_navigation_timeout_starts_at_first_localization_and_cannot_be_reset():
    gate = StartupReadiness(10, 0)
    gate.update(1, {}, localized=False, navigation_ready=False)
    gate.update(100, {}, localized=True, navigation_ready=False)
    report = gate.update(111, {}, localized=False, navigation_ready=False)
    assert report["state"] == "failed"
    assert "activation timed out" in report["errors"][0]


def test_lost_data_after_startup_is_reported_without_reusing_startup_deadline():
    gate = StartupReadiness(10, 0)
    gate.update(1, {"perception": component([])}, localized=True, navigation_ready=True)
    report = gate.update(100, {"perception": component(["camera data stale"])},
                         localized=True, navigation_ready=True)
    assert report["state"] == "not_ready"
    assert not report["errors"]


@pytest.mark.parametrize("timeout", [0, -1, 601, float("inf"), float("nan")])
def test_invalid_timeout_cannot_disable_required_checks(timeout):
    with pytest.raises(ValueError):
        StartupReadiness(timeout, 0)


def receiver():
    node = Mock()
    node.samples = {}
    node.limits = {"front_color": 2, "lidar": 1, "persons": 5}
    return node


def test_empty_camera_and_invalid_scan_do_not_count_as_ready():
    node = receiver()
    # Use a real rclpy Time to exercise timestamp comparisons too.
    from rclpy.time import Time
    from rclpy.clock import ClockType
    node.get_clock.return_value.now.return_value = Time(seconds=100, clock_type=ClockType.ROS_TIME)
    image = Image()
    image.header.stamp.sec = 100
    ReadinessMonitor.receive(node, "front_color", image)
    assert not node.samples
    image.width = image.height = 1
    image.data = [1]
    ReadinessMonitor.receive(node, "front_color", image)
    assert "front_color" in node.samples
    scan = LaserScan()
    scan.header.stamp.sec = 100
    scan.range_min, scan.range_max = .1, 10.0
    scan.ranges = [float("inf")]
    ReadinessMonitor.receive(node, "lidar", scan)
    assert "lidar" not in node.samples
    scan.ranges = [1.0]
    scan.header.stamp.sec = 90
    ReadinessMonitor.receive(node, "lidar", scan)
    assert "lidar" not in node.samples


def test_empty_detection_result_confirms_inference_without_requiring_a_person():
    node = receiver()
    ReadinessMonitor.receive(node, "persons", String(data='{"detections": []}'))
    assert "persons" in node.samples


def test_failed_report_is_published_before_monitor_exits():
    node = Mock()
    node.snapshot.return_value = {"errors": ["perception: missing frames"], "components": {}}
    node.last_log, node.log_at = None, 0
    ReadinessMonitor.tick(node)
    assert node.failure == "perception: missing frames"
    node.status.publish.assert_called_once()
    node.timer.cancel.assert_called_once()

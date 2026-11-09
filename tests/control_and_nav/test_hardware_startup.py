"""Device checks use filesystem metadata only; never open physical devices."""
import importlib.util
import os
from pathlib import Path
import pty

import pytest
from launch import LaunchContext
from launch.actions import DeclareLaunchArgument

from dori_hardware import startup_checks as checks

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def devices(tmp_path):
    interface = tmp_path / "can1"
    interface.mkdir()
    (interface / "type").write_text("280")
    # CAN operstate may be UNKNOWN; the UP flag, not operstate, is authoritative.
    (interface / "flags").write_text("0x41")
    descriptors = [pty.openpty() for _ in range(3)]
    ports = {label: os.ttyname(pair[1]) for label, pair in zip(("Dynamixel", "IMU", "LiDAR"), descriptors)}
    yield tmp_path, ports
    for pair in descriptors:
        for fd in pair:
            os.close(fd)


def test_ready_devices_need_no_port_open_or_process(devices, monkeypatch):
    root, ports = devices
    monkeypatch.setattr(os, "open", lambda *a, **k: pytest.fail("Device was opened"))
    checks.validate_devices("can1", ports, net_root=root)


def test_reports_can_and_all_missing_devices_together(tmp_path):
    with pytest.raises(RuntimeError) as error:
        checks.validate_devices("can1", {"Dynamixel": str(tmp_path / "missing-dxl"),
                                        "IMU": str(tmp_path / "missing-imu")}, net_root=tmp_path)
    for expected in ("no robot nodes were started", "CAN can1", "Dynamixel", "IMU"):
        assert expected in str(error.value)


def test_rejects_aliases_of_same_device(devices):
    root, ports = devices
    alias = root / "slamtec_c1"
    alias.symlink_to(ports["Dynamixel"])
    ports["LiDAR"] = str(alias)
    with pytest.raises(RuntimeError, match="LiDAR and Dynamixel share"):
        checks.validate_devices("can1", ports, net_root=root)


@pytest.mark.parametrize("filename,value,message", [("type", "1", "not a CAN"), ("flags", "0x40", "DOWN")])
def test_rejects_wrong_interface_or_down_can(devices, filename, value, message):
    root, ports = devices
    (root / "can1" / filename).write_text(value)
    with pytest.raises(RuntimeError, match=message):
        checks.validate_devices("can1", ports, net_root=root)


def test_rejects_regular_file_and_permission_denied(devices, monkeypatch):
    root, ports = devices
    regular = root / "not-a-port"
    regular.touch()
    ports["LiDAR"] = str(regular)
    monkeypatch.setattr(os, "access", lambda *args: False)
    with pytest.raises(RuntimeError) as error:
        checks.validate_devices("can1", ports, net_root=root)
    assert "not a serial character device" in str(error.value)
    assert "no read/write permission" in str(error.value)


def test_hardware_checks_run_before_constructing_includes(monkeypatch):
    path = ROOT / "ros2_ws/src/dori_bringup/launch/hardware.launch.py"
    spec = importlib.util.spec_from_file_location("hardware_checks_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = LaunchContext()
    context.launch_configurations["map"] = str(ROOT / "maps/live_navigation_20261023_1938.yaml")
    for action in module.generate_launch_description().entities:
        if isinstance(action, DeclareLaunchArgument):
            action.execute(context)
    def unavailable(*args, **kwargs):
        raise RuntimeError("devices unavailable")
    monkeypatch.setattr(module, "validate_devices", unavailable)
    monkeypatch.setattr(module, "include", lambda *args: pytest.fail("Created hardware include before validation"))
    monkeypatch.setattr(module, "Node", lambda *args, **kw: pytest.fail("Created node before validation"))
    with pytest.raises(RuntimeError, match="devices unavailable"):
        module.setup(context)


def test_can_wait_succeeds_when_service_finishes(devices, monkeypatch):
    root, ports = devices
    (root / "can1/flags").write_text("0x40")
    clock = [0.0]
    def advance(seconds):
        clock[0] += seconds
        if clock[0] >= .3:
            (root / "can1/flags").write_text("0x41")
    monkeypatch.setattr(checks.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(checks.time, "sleep", advance)
    checks.validate_devices("can1", ports, net_root=root, can_wait_timeout=1)
    assert .3 <= clock[0] < 1


def test_can_wait_is_bounded_and_reports_service_failure(devices, monkeypatch):
    root, ports = devices
    (root / "can1/flags").write_text("0x40")
    clock = [0.0]
    monkeypatch.setattr(checks.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(checks.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(checks, "can_service_status", lambda: "ActiveState=failed; Result=exit-code")
    with pytest.raises(RuntimeError, match="ActiveState=failed"):
        checks.validate_devices("can1", ports, net_root=root, can_wait_timeout=.5)
    assert clock[0] == .5


@pytest.mark.parametrize("timeout", [-1, float("nan"), float("inf"), 31])
def test_invalid_can_timeout_is_rejected(devices, timeout):
    root, ports = devices
    with pytest.raises(ValueError, match="can_wait_timeout"):
        checks.validate_devices("can1", ports, net_root=root, can_wait_timeout=timeout)

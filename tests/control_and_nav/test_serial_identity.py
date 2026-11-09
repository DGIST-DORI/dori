"""Read-only discovery against PTYs; no physical devices or ROS nodes."""
from contextlib import contextmanager
import os
import pty
import select
import termios
import threading
from types import SimpleNamespace

import pytest

from dori_hardware import serial_identity as identity


def test_protocol_crc_matches_robotis_documented_ping():
    assert identity.crc16(bytes.fromhex("fffffd0001030001")) == 0x4e19
    assert identity.crc16(bytes.fromhex("fffffd000107005500060426")) == 0x5d65


@contextmanager
def servo_bus(monkeypatch, *, mode="ok"):
    master, slave = pty.openpty()
    port = os.ttyname(slave)
    original = termios.tcgetattr(slave)
    # Retain a test-only descriptor to inspect restoration after close. Real
    # ownership detection is checked separately, with no such retained fd.
    monkeypatch.setattr(identity.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=1))
    received = []
    finished = threading.Event()

    def emulate():
        data = bytearray()
        while not finished.is_set():
            if not select.select([master], [], [], .02)[0]:
                continue
            data.extend(os.read(master, 256))
            while len(data) >= 10:
                request = bytes(data[:10])
                del data[:10]
                received.append(request)
                motor_id = request[4]
                if mode == "silent":
                    continue
                model = identity.EXPECTED_MODELS[motor_id] if mode != "wrong-model" else 999
                error = 4 if mode == "status-error" else 0
                reply = bytes.fromhex("fffffd00") + bytes((motor_id, 7, 0, 0x55, error))
                reply += model.to_bytes(2, "little") + b"\x26"
                reply += identity.crc16(reply).to_bytes(2, "little")
                if mode == "bad-crc":
                    reply = reply[:-1] + bytes((reply[-1] ^ 1,))
                # Fragmented status and an echoed PING must not be mistaken
                # for a valid status response.
                os.write(master, b"noise" + request + reply[:5])
                os.write(master, reply[5:])

    thread = threading.Thread(target=emulate)
    thread.start()
    try:
        yield port, received
        assert termios.tcgetattr(slave) == original
        # TIOCEXCL must be cleared, including on a failed discovery.
        fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        os.close(fd)
    finally:
        finished.set()
        thread.join(timeout=1)
        os.close(master)
        os.close(slave)


def test_discovery_only_sends_unicast_ping_and_restores_port(monkeypatch):
    with servo_bus(monkeypatch) as (port, requests):
        assert identity.probe_dynamixel(port, baudrate=115200) == {1: 1140, 3: 1040}
    assert [packet[4] for packet in requests] == [1, 3]
    for packet in requests:
        assert packet[:4] == bytes.fromhex("fffffd00")
        assert packet[5:8] == b"\x03\x00\x01"  # Length 3, PING; no parameters.
        assert identity.crc16(packet[:-2]) == int.from_bytes(packet[-2:], "little")


@pytest.mark.parametrize("mode,match", [
    ("silent", "No valid"), ("bad-crc", "No valid"),
    ("wrong-model", "Unexpected"), ("status-error", "status error"),
])
def test_failed_probe_restores_port_and_rejects_bus(monkeypatch, mode, match):
    with servo_bus(monkeypatch, mode=mode) as (port, requests):
        with pytest.raises(RuntimeError, match=match):
            identity.probe_dynamixel(port, timeout=.05)
        assert requests
        assert all(packet[7] == 1 for packet in requests)


def test_busy_port_is_not_opened_or_changed(monkeypatch):
    master, slave = pty.openpty()
    try:
        original = termios.tcgetattr(slave)
        monkeypatch.setattr(identity.os, "open", lambda *a, **kw: pytest.fail("Opened busy port"))
        with pytest.raises(RuntimeError, match="busy"):
            identity.probe_dynamixel(os.ttyname(slave))
        assert termios.tcgetattr(slave) == original
    finally:
        os.close(master)
        os.close(slave)


def candidate(root, name, target):
    path = root / name
    path.symlink_to(target)
    return str(path)


def test_auto_accepts_cp210x_excludes_sensors_can_and_deduplicates(tmp_path, monkeypatch):
    dxl = candidate(tmp_path, "usb-Silicon_Labs_CP2102N-servo", "/dev/ttyUSB1")
    candidate(tmp_path, "usb-servo-alias", "/dev/ttyUSB1")
    lidar = candidate(tmp_path, "usb-Silicon_Labs_CP2102N-lidar", "/dev/ttyUSB0")
    imu = candidate(tmp_path, "usb-Arduino-imu", "/dev/ttyACM1")
    candidate(tmp_path, "usb-CANable2-adapter", "/dev/ttyACM0")
    calls = []
    monkeypatch.setattr(identity, "probe_dynamixel", lambda p, **kw: calls.append((p, kw)))
    assert identity.resolve_dxl_port("auto", excluded_ports=[lidar, imu],
                                     baudrate=115200, by_id_dir=tmp_path) == dxl
    assert calls == [(dxl, {"baudrate": 115200})]


def test_explicit_port_does_not_require_vendor_or_probe(monkeypatch):
    monkeypatch.setattr(identity, "probe_dynamixel", lambda *a, **kw: pytest.fail("Probed explicit port"))
    assert identity.resolve_dxl_port("/dev/my_dynamixel") == "/dev/my_dynamixel"


def test_no_candidate_has_actionable_neutral_error(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "probe_dynamixel", lambda *a, **kw: pytest.fail("Probed excluded device"))
    lidar = candidate(tmp_path, "usb-CP2102N-lidar", "/dev/ttyUSB0")
    with pytest.raises(RuntimeError, match="No unassigned USB serial ports") as exc:
        identity.resolve_dxl_port("auto", excluded_ports=[lidar], by_id_dir=tmp_path)
    assert "real_dxl_port" in str(exc.value)
    assert "FTDI" not in str(exc.value)


def test_multiple_buses_need_explicit_selection(tmp_path, monkeypatch):
    candidate(tmp_path, "usb-adapter-1", "/dev/ttyUSB1")
    candidate(tmp_path, "usb-adapter-2", "/dev/ttyUSB2")
    monkeypatch.setattr(identity, "probe_dynamixel", lambda *a, **kw: {1: 1140, 3: 1040})
    with pytest.raises(RuntimeError, match="Multiple Dynamixel buses"):
        identity.resolve_dxl_port("auto", by_id_dir=tmp_path)


def test_candidate_failure_does_not_hide_valid_bus(tmp_path, monkeypatch):
    bad = candidate(tmp_path, "usb-adapter-1", "/dev/ttyUSB1")
    good = candidate(tmp_path, "usb-adapter-2", "/dev/ttyUSB2")
    def probe(port, **kwargs):
        if port == bad:
            raise RuntimeError("No response")
        return {1: 1140, 3: 1040}
    monkeypatch.setattr(identity, "probe_dynamixel", probe)
    assert identity.resolve_dxl_port("auto", by_id_dir=tmp_path) == good

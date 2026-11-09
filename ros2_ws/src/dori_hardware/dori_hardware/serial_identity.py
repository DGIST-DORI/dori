"""Identify a Dynamixel bus using Protocol 2 PING only (no register writes)."""

import fcntl
import os
from pathlib import Path
import select
import subprocess
import termios
import time

EXPECTED_MODELS = {1: 1140, 3: 1040}
HEADER = b"\xff\xff\xfd\x00"


def crc16(data):
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ (0x8005 if crc & 0x8000 else 0)) & 0xffff
    return crc


def _ping(fd, motor_id, timeout):
    packet = HEADER + bytes((motor_id, 3, 0, 1))
    packet += crc16(packet).to_bytes(2, "little")
    if os.write(fd, packet) != len(packet):
        raise OSError("Incomplete Dynamixel PING transmission")
    deadline = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < deadline:
        if not select.select([fd], [], [], max(0, deadline - time.monotonic()))[0]:
            break
        chunk = os.read(fd, 256)
        if not chunk:
            break
        data.extend(chunk)
        while len(data) >= 7:
            start = data.find(HEADER)
            if start < 0:
                del data[:-3]
                break
            del data[:start]
            if len(data) < 7:
                break
            size = int.from_bytes(data[5:7], "little") + 7
            # A PING status is 14 bytes; allow byte stuffing and ignore noise.
            if not 10 <= size <= 32:
                del data[0]
                continue
            if len(data) < size:
                break
            reply = bytes(data[:size])
            del data[:size]
            if reply[4] != motor_id or crc16(reply[:-2]) != int.from_bytes(reply[-2:], "little"):
                continue
            body = reply[7:-2].replace(b"\xff\xff\xfd\xfd", b"\xff\xff\xfd")
            if len(body) == 5 and body[0] == 0x55:
                if body[1]:
                    raise RuntimeError(f"Dynamixel ID {motor_id} reports status error {body[1]:#x}")
                return int.from_bytes(body[2:4], "little")
    raise RuntimeError(f"No valid Dynamixel PING response from ID {motor_id}")


def probe_dynamixel(port, baudrate=57600, timeout=0.25):
    """Query IDs 1/3 without torque, goals, baud changes on the servos, or DTR/RTS toggles.

    Serial host settings are restored even on errors. Refuse occupied devices
    before changing settings; TIOCEXCL also prevents new opens during the query.
    """
    speed = getattr(termios, f"B{int(baudrate)}", None)
    if speed is None or int(baudrate) <= 0:
        raise ValueError(f"Unsupported Dynamixel discovery baudrate: {baudrate}")
    # Ubuntu's fuser does not accept '--'; an absolute path cannot be an option.
    owners = subprocess.run(["/usr/bin/fuser", str(Path(port).resolve())],
                            capture_output=True, timeout=2)
    if owners.returncode != 1:
        raise RuntimeError(f"Port is busy or its ownership could not be checked: {port}")
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    saved = None
    exclusive = False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.ioctl(fd, termios.TIOCEXCL)
        exclusive = True
        saved = termios.tcgetattr(fd)
        attrs = termios.tcgetattr(fd)
        attrs[:6] = [0, 0, termios.CS8 | termios.CREAD | termios.CLOCAL, 0, speed, speed]
        attrs[6][termios.VMIN] = attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        termios.tcflush(fd, termios.TCIFLUSH)
        models = {motor_id: _ping(fd, motor_id, timeout) for motor_id in EXPECTED_MODELS}
        if models != EXPECTED_MODELS:
            raise RuntimeError(f"Unexpected Dynamixel models: {models}; expected {EXPECTED_MODELS}")
        return models
    finally:
        try:
            if saved is not None:
                termios.tcsetattr(fd, termios.TCSANOW, saved)
        finally:
            try:
                if exclusive:
                    fcntl.ioctl(fd, termios.TIOCNXCL)
            finally:
                os.close(fd)


def resolve_dxl_port(port, *, excluded_ports=(), baudrate=57600,
                     by_id_dir=Path("/dev/serial/by-id")):
    """Explicit paths are vendor-neutral; auto requires one responding DORI bus.

    Use stable USB identities, never a ttyUSB index or a USB chip vendor as
    evidence of a device's role. CANable, configured sensors and aliases of
    those devices must never receive Dynamixel discovery packets.
    """
    if port != "auto":
        if not port:
            raise ValueError("dxl_port must be 'auto' or a serial device path")
        return str(port)
    excluded = {Path(p).resolve() for p in (*excluded_ports, "/dev/dori_canable")}
    candidates = []
    seen = set()
    skipped = []
    for path in sorted(by_id_dir.glob("*")):
        target = path.resolve()
        if target in excluded or "CANable" in path.name:
            skipped.append(path.name)
        elif target not in seen:
            candidates.append(path)
        seen.add(target)
    matches, failures = [], []
    for path in candidates:
        try:
            probe_dynamixel(str(path), baudrate=int(baudrate))
            matches.append(str(path))
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            failures.append(f"{path}: {exc}")
    if len(matches) == 1:
        print(f"Dynamixel identified at {matches[0]} ({baudrate} baud; IDs 1/3)", flush=True)
        return matches[0]
    if len(matches) > 1:
        raise RuntimeError("Multiple Dynamixel buses found; set dxl_port explicitly: " + ", ".join(matches))
    raise RuntimeError(
        f"No DORI Dynamixel bus found at {baudrate} baud (expected ID 1/model 1140, ID 3/model 1040). "
        "Check adapter connection, servo power and baudrate; set dxl_port/dxl_baudrate "
        "(real_dxl_port/real_dxl_baudrate in bringup) for a manual selection. "
        "No specific USB chip manufacturer is required. "
        + ("Probe results: " + "; ".join(failures) if failures else "No unassigned USB serial ports.")
        + (" Excluded sensor/CAN ports: " + ", ".join(skipped) if skipped else "")
    )

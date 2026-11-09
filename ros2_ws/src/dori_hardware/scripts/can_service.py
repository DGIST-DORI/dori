#!/usr/bin/python3
"""Managed by DORI CAN setup. Own one foreground slcand, without any ROS nodes."""

import fcntl
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import sys
import threading
import time

CONFIG = Path("/etc/dori/can.json")
NET_ROOT = Path("/sys/class/net")


class ConfigurationError(RuntimeError):
    """Do not retry conflicts or invalid settings automatically."""


def validate_config(config):
    if not isinstance(config, dict) or not all(
        isinstance(config.get(key), str)
        for key in ("managed_by", "device", "interface", "vendor_id", "product_id", "serial")
    ):
        raise ConfigurationError("CAN configuration must contain string device/interface/USB identity fields")
    if config.get("managed_by") != "dori-can":
        raise ConfigurationError("Not a DORI CAN configuration")
    if not re.fullmatch(r"can[0-9]{1,3}", config.get("interface", "")):
        raise ConfigurationError("Expected an interface name such as can1")
    for key in ("vendor_id", "product_id"):
        if not re.fullmatch(r"[0-9a-f]{4}", config.get(key, "")):
            raise ConfigurationError(f"Invalid USB {key}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", config.get("serial", "")):
        raise ConfigurationError("Missing/invalid unique USB serial")
    device = Path(config.get("device", ""))
    if device.parent != Path("/dev/serial/by-id") or "CANable2" not in device.name:
        raise ConfigurationError("Expected the CANable2 /dev/serial/by-id path")
    return config


def device_properties(device):
    result = subprocess.run(
        ["/usr/bin/udevadm", "info", "--query=property", "--name", str(device)],
        check=True, capture_output=True, text=True, timeout=3,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)


def device_users(device, proc_root=Path("/proc")):
    """Find open descriptors, including an slcand launched outside this service."""
    target = Path(device).stat().st_rdev
    users = set()
    for process in proc_root.glob("[0-9]*"):
        if int(process.name) == os.getpid():
            continue
        try:
            for fd in (process / "fd").iterdir():
                try:
                    info = fd.stat()
                    if stat.S_ISCHR(info.st_mode) and info.st_rdev == target:
                        users.add(int(process.name))
                        break
                except (FileNotFoundError, ProcessLookupError):
                    continue
        except (FileNotFoundError, ProcessLookupError):
            continue
    return sorted(users)


def notify(message):
    address = os.environ.get("NOTIFY_SOCKET")
    if not address:
        return
    if address.startswith("@"):
        address = "\0" + address[1:]
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as channel:
        channel.sendto(message.encode(), address)


def interface_up(interface):
    try:
        return (int((NET_ROOT / interface / "type").read_text()) == 280 and
                bool(int((NET_ROOT / interface / "flags").read_text(), 16) & 1))
    except (OSError, ValueError):
        return False


def supervise(config, stopping):
    validate_config(config)
    device, interface = Path(config["device"]), config["interface"]
    if not stat.S_ISCHR(device.stat().st_mode):
        raise ConfigurationError(f"Not a serial character device: {device}")
    properties = device_properties(device)
    for expected, actual in (("vendor_id", "ID_VENDOR_ID"), ("product_id", "ID_MODEL_ID"),
                             ("serial", "ID_SERIAL_SHORT")):
        if properties.get(actual) != config[expected]:
            raise ConfigurationError(f"USB identity mismatch for {device}: {actual}")
    if (NET_ROOT / interface).exists():
        raise ConfigurationError(
            f"{interface} already exists outside dori-can.service; stop its owner before setup. "
            "The existing interface was not changed."
        )
    users = device_users(device)
    if users:
        raise ConfigurationError(f"CANable is already open by PID(s) {users}; no second slcand was started")
    subprocess.run(["/usr/sbin/modprobe", "slcan"], check=True, timeout=5)
    if stopping.is_set():
        return
    print(f"Preparing {interface} from {device} (CAN 1 Mbit/s, UART 3000000)", flush=True)
    child = subprocess.Popen([
        "/usr/bin/slcand", "-F", "-o", "-c", "-s8", "-t", "hw", "-S", "3000000",
        str(device), interface,
    ])
    try:
        deadline = time.monotonic() + 10
        while not (NET_ROOT / interface).exists():
            if child.poll() is not None:
                raise RuntimeError(f"slcand exited before {interface} appeared (code {child.returncode})")
            if time.monotonic() >= deadline:
                raise RuntimeError(f"Timed out waiting for slcand to create {interface}")
            if stopping.wait(.1):
                return
        if stopping.is_set():
            return
        if child.poll() is not None:
            raise RuntimeError(f"slcand exited during setup (code {child.returncode})")
        subprocess.run(["/usr/sbin/ip", "link", "set", "dev", interface, "up"], check=True, timeout=3)
        if not interface_up(interface):
            raise RuntimeError(f"{interface} did not become UP")
        notify(f"READY=1\nSTATUS={interface} UP; CANable {config['serial']}")
        print(f"{interface} UP; no motor commands or ROS nodes were started", flush=True)
        while not stopping.wait(.2):
            if child.poll() is not None or not interface_up(interface):
                raise RuntimeError(f"Lost {interface}/slcand; restarting the CAN connection")
    finally:
        # Only stop our child. Closing its SLCAN line discipline removes the
        # interface; never bring down or kill an independently owned CAN setup.
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=2)


def main():
    stopping = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopping.set())
    try:
        config = validate_config(json.loads(CONFIG.read_text()))
        with open("/run/dori-can/lock", "w") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ConfigurationError("Another DORI CAN service already owns the setup lock") from None
            supervise(config, stopping)
    except (ConfigurationError, ValueError) as error:
        print(f"CAN configuration error: {error}", file=sys.stderr, flush=True)
        return 78
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"CAN setup failed: {error}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

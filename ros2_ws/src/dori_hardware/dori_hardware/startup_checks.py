"""Read-only device checks, before launching any physical robot processes."""

import math
import os
from pathlib import Path
import stat
import subprocess
import time

CAN_INTERFACE = "can1"
DXL_PORT = "/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTAU591Z-if00-port0"
IMU_PORT = "/dev/serial/by-id/usb-Arduino_Nano_33_BLE_B9CD51D670B512DB-if00"
LIDAR_PORT = "/dev/slamtec_c1"
CAN_WAIT_TIMEOUT = "10.0"


def can_error(can_interface, net_root):
    interface = net_root / can_interface
    try:
        if int((interface / "type").read_text()) != 280:  # ARPHRD_CAN
            return f"{can_interface} is not a CAN interface"
        if not int((interface / "flags").read_text(), 16) & 1:  # IFF_UP
            return f"CAN {can_interface} is DOWN"
    except (OSError, ValueError) as exc:
        return f"CAN {can_interface} is unavailable ({exc})"
    return None


def can_service_status():
    """Diagnostics only: never start services or request privileges in launch."""
    try:
        result = subprocess.run([
            "/usr/bin/systemctl", "show", "dori-can.service", "--property=LoadState",
            "--property=ActiveState", "--property=SubState", "--property=Result",
        ], capture_output=True, text=True, timeout=2)
        if result.returncode == 0:
            return "; ".join(result.stdout.splitlines())
    except (OSError, subprocess.SubprocessError):
        pass
    return "service status unavailable"


def validate_devices(can_interface, serial_ports, *, net_root=Path("/sys/class/net"), can_wait_timeout=0.0):
    """Collect setup errors without opening ports, sending packets or running sudo."""
    errors = []
    timeout = float(can_wait_timeout)
    if not math.isfinite(timeout) or not 0 <= timeout <= 30:
        raise ValueError("can_wait_timeout must be finite and between 0 and 30 seconds")
    if not can_interface or Path(can_interface).name != can_interface:
        errors.append(f"Invalid CAN interface: {can_interface!r}")
    else:
        deadline = time.monotonic() + timeout
        error = can_error(can_interface, net_root)
        if error and timeout:
            print(f"Waiting up to {timeout:g}s for CAN {can_interface} to become UP...", flush=True)
        while error and time.monotonic() < deadline:
            time.sleep(min(.1, max(0, deadline - time.monotonic())))
            error = can_error(can_interface, net_root)
        if error:
            errors.append(f"{error} after waiting {timeout:g}s; dori-can.service: {can_service_status()}")

    devices = {}
    for label, port in serial_ports.items():
        path = Path(port)
        try:
            info = path.stat()
            if not stat.S_ISCHR(info.st_mode):
                errors.append(f"{label}: {port} is not a serial character device")
                continue
            if not os.access(path, os.R_OK | os.W_OK):
                errors.append(f"{label}: no read/write permission for {port}; check dialout/udev permissions")
            if info.st_rdev in devices:
                errors.append(f"{label} and {devices[info.st_rdev]} share {path.resolve()}; use separate ports")
            devices[info.st_rdev] = label
        except OSError as exc:
            errors.append(f"{label}: {port} is unavailable ({exc}); check the USB connection and device path")
    if errors:
        raise RuntimeError(
            "Hardware startup checks failed; no robot nodes were started:\n- "
            + "\n- ".join(errors)
            + "\nCAN: install dori_hardware/scripts/install_can_service.py once with sudo; "
            "then check systemctl status dori-can.service and journalctl -u dori-can.service -b."
            + "\nSee docs/user/DORI-AMM.md TASK 20-30-00."
        )

#!/usr/bin/python3
"""Install CANable USB activation once, or render files for review without root."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from can_service import device_properties, validate_config

PACKAGE = Path(__file__).resolve().parents[1]
SYSTEM_ROOT = Path("/")


def configuration(device=None, interface="can1"):
    if device is None:
        devices = sorted(Path("/dev/serial/by-id").glob("*CANable2*-if00"))
        if len(devices) != 1:
            raise RuntimeError("Connect one CANable2, or select its exact by-id path with --device")
        device = devices[0]
    device = Path(device).absolute()  # Preserve stable by-id name, not ttyACM enumeration.
    properties = device_properties(device)
    return validate_config({
        "managed_by": "dori-can",
        "device": str(device),
        "interface": interface,
        "vendor_id": properties.get("ID_VENDOR_ID", ""),
        "product_id": properties.get("ID_MODEL_ID", ""),
        "serial": properties.get("ID_SERIAL_SHORT", ""),
    })


def files(config):
    validate_config(config)
    # Match the selected USB identity, even if ttyACM numbering changes.
    rule = (
        '# Managed by DORI CAN setup.\n'
        'ACTION=="add|change", SUBSYSTEM=="tty", '
        f'ENV{{ID_VENDOR_ID}}=="{config["vendor_id"]}", '
        f'ENV{{ID_MODEL_ID}}=="{config["product_id"]}", '
        f'ENV{{ID_SERIAL_SHORT}}=="{config["serial"]}", '
        'ENV{ID_USB_INTERFACE_NUM}=="00", '
        'SYMLINK+="dori_canable", TAG+="systemd", '
        'ENV{ID_MM_DEVICE_IGNORE}="1", ENV{ID_MM_PORT_IGNORE}="1", '
        'ENV{SYSTEMD_ALIAS}+="/dev/dori_canable", '
        'ENV{SYSTEMD_WANTS}+="dori-can.service"\n'
    )
    return {
        "etc/dori/can.json": json.dumps(config, indent=2) + "\n",
        "etc/udev/rules.d/99-dori-can.rules": rule,
        "etc/systemd/system/dori-can.service": (PACKAGE / "systemd/dori-can.service").read_text(),
        "usr/local/libexec/dori-can": (PACKAGE / "scripts/can_service.py").read_text(),
    }


def write_files(contents, destination):
    for relative, content in contents.items():
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = 0o755 if relative.startswith("usr/") else 0o644
        with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, delete=False) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        try:
            temporary_path.chmod(mode)
            temporary_path.replace(target)
        finally:
            temporary_path.unlink(missing_ok=True)


def install(contents, config):
    if os.geteuid() != 0:
        raise RuntimeError("One-time installation requires sudo; --output-dir renders files without root")
    for program in ("slcand", "ip", "modprobe", "udevadm", "systemctl"):
        if shutil.which(program) is None:
            raise RuntimeError(f"Missing {program}; install can-utils, iproute2, kmod, udev and systemd")
    # Never replace an unrelated service/config or silently retarget a live one.
    for relative, content in contents.items():
        target = SYSTEM_ROOT / relative
        if target.exists():
            existing = target.read_text()
            marker = '"managed_by": "dori-can"' if relative.endswith(".json") else "Managed by DORI CAN setup."
            if marker not in existing:
                raise RuntimeError(f"Refusing to replace unmanaged file: {target}")
            if existing != content:
                active = subprocess.run(["/usr/bin/systemctl", "is-active", "--quiet", "dori-can.service"]).returncode == 0
                if active:
                    raise RuntimeError("Stop the robot and dori-can.service before updating its active configuration")
    write_files(contents, SYSTEM_ROOT)
    subprocess.run(["/usr/bin/systemctl", "daemon-reload"], check=True, timeout=10)
    subprocess.run(["/usr/bin/udevadm", "control", "--reload-rules"], check=True, timeout=5)
    tty = Path(config["device"]).resolve().name
    subprocess.run(["/usr/bin/udevadm", "trigger", "--action=change", "--subsystem-match=tty",
                    f"--sysname-match={tty}"], check=True, timeout=5)
    subprocess.run(["/usr/bin/udevadm", "settle", "--timeout=5"], check=True, timeout=6)
    # SYSTEMD_WANTS only starts on first activation; explicitly start a device
    # that was already connected when the new rule was installed. Start is
    # idempotent and does not restart a working service.
    subprocess.run(["/usr/bin/systemctl", "start", "dori-can.service"], check=True, timeout=25)
    subprocess.run(["/usr/bin/systemctl", "--no-pager", "status", "dori-can.service"], check=True, timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", help="Exact CANable2 /dev/serial/by-id path; default: the only connected CANable2")
    parser.add_argument("--interface", default="can1")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--output-dir", type=Path, help="Render installation files here without changing the system")
    mode.add_argument("--dry-run", action="store_true", help="Show device identity and installation paths only")
    args = parser.parse_args()
    try:
        config = configuration(args.device, args.interface)
        contents = files(config)
        print(f"CANable {config['serial']} -> {config['interface']}: {config['device']}", flush=True)
        if args.dry_run:
            print("\n".join("/" + name for name in contents))
        elif args.output_dir:
            write_files(contents, args.output_dir)
            print(f"Rendered files under {args.output_dir}; no system/device changes")
        else:
            install(contents, config)
            print("Installed. This CANable will prepare CAN automatically at boot and on reconnect.")
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"CAN installation failed: {error}\nInspect: journalctl -u dori-can.service -b --no-pager", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

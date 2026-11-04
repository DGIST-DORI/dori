#!/usr/bin/env python3
"""Inspect CubeMars feedback without transmitting CAN motor commands.

Protocol reference: AK Series Module Driver Manual V1.0.18, sections 5.2.1/5.3.
https://www.cubemars.com/data/cms/202605/ak-series-driver-manual-v1-0-18-for-ak-2-0-robotic-actuator.pdf
The MIT ranges below apply to AK45-36, not the existing wheel motors.
Silence is inconclusive: a disabled MIT motor need not publish feedback.
Direct CANable serial access only configures/opens/closes the adapter channel.
"""

import argparse
import collections
import json
import math
from pathlib import Path
import socket
import struct
import time


CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_EFF_MASK = 0x1FFFFFFF
FRAME = struct.Struct("=IB3x8s")


def decode_feedback(can_id, data, motor_id):
    """Return recognized feedback only; ignore commands, boot and error frames."""
    if can_id & (CAN_RTR_FLAG | CAN_ERR_FLAG):
        return None
    extended = bool(can_id & CAN_EFF_FLAG)
    arbitration_id = can_id & CAN_EFF_MASK
    if len(data) != 8:
        return None
    if extended:
        # 0x09 is bootloader traffic; 0x2C is a startup announcement.
        # Neither is a position sample. Only 0x29 is servo state feedback.
        if arbitration_id != (0x29 << 8) | motor_id:
            return None
        position, speed, current, temperature, error = struct.unpack(">hhhbB", data)
        if abs(position) > 32000 or abs(speed) > 32000 or abs(current) > 6000:
            return None
        return dict(mode="servo", position_deg=position / 10.0,
                    speed_erpm=speed * 10.0, current_a=current / 100.0,
                    temperature_c=temperature, error=error)
    if arbitration_id != motor_id or data[0] != motor_id:
        return None
    position = (data[1] << 8) | data[2]
    velocity = (data[3] << 4) | (data[4] >> 4)
    torque = ((data[4] & 15) << 8) | data[5]
    return dict(mode="mit", position_deg=math.degrees(position * 25.0 / 65535 - 12.5),
                velocity_rad_s=velocity * 12.0 / 4095 - 6.0,
                torque_nm=torque * 68.0 / 4095 - 34.0,
                # MIT uses an unsigned offset byte; Servo above uses int8 °C.
                temperature_c=data[6] - 40, temperature_raw=data[6], error=data[7])


def summarize(samples):
    counts = collections.Counter(sample["mode"] for sample in samples)
    mode = next(iter(counts)) if len(counts) == 1 and len(samples) >= 3 else "unknown"
    result = {"mode": mode, "samples_by_mode": dict(counts), "transmitted_frames": 0}
    if mode == "unknown":
        result["reason"] = "No consistent repeated feedback; silence does not identify MIT mode."
        return result
    positions = [sample["position_deg"] for sample in samples]
    result.update(last_feedback=samples[-1], position_span_deg=max(positions) - min(positions),
                  faults=sorted({sample["error"] for sample in samples if sample["error"]}))
    # Report observations only. Do not silently overwrite an A reference on startup.
    return result


def inspect(interface, motor_id, seconds):
    samples = []
    raw_frames = []
    with socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW) as bus:
        bus.bind((interface,))
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            bus.settimeout(max(0.001, deadline - time.monotonic()))
            try:
                frame, _, flags, _ = bus.recvmsg(FRAME.size)
            except socket.timeout:
                break
            # CAN_RAW sockets also see packets sent by other local programs.
            # These are not evidence from the motor itself.
            if flags & socket.MSG_DONTROUTE or len(frame) != FRAME.size:
                continue
            can_id, length, payload = FRAME.unpack(frame)
            sample = decode_feedback(can_id, payload[:length], motor_id)
            if sample is not None:
                samples.append(sample)
                if len(raw_frames) < 20:
                    raw_frames.append({"can_id": hex(can_id), "data": payload[:length].hex()})
    report = summarize(samples)
    report.update(interface=interface, motor_id=motor_id, model="AK45-36",
                  raw_feedback=raw_frames, captured_at_unix=time.time())
    return report


def decode_slcan(line):
    """Decode classical CANable SLCAN frames (optional trailing timestamp)."""
    if not line or line[0:1] not in (b"t", b"T"):
        return None
    extended = line[0:1] == b"T"
    width = 8 if extended else 3
    try:
        arbitration_id = int(line[1:1 + width], 16)
        length = int(line[1 + width:2 + width], 16)
        if length > 8 or arbitration_id > (CAN_EFF_MASK if extended else 0x7FF):
            return None
        if len(line) not in (2 + width + length * 2, 6 + width + length * 2):
            return None
        data = bytes.fromhex(line[2 + width:2 + width + length * 2].decode("ascii"))
        return arbitration_id | (CAN_EFF_FLAG if extended else 0), data
    except (ValueError, UnicodeError):
        return None


def inspect_serial(port, motor_id, seconds):
    import serial

    device = Path(port).resolve()
    sys_device = (Path("/sys/class/tty") / device.name / "device").resolve()
    recognized = False
    for ancestor in [sys_device, *sys_device.parents]:
        if (ancestor / "idVendor").exists() and (ancestor / "idProduct").exists():
            recognized = ((ancestor / "idVendor").read_text().strip(),
                          (ancestor / "idProduct").read_text().strip()) == ("16d0", "117e")
            break
    if not recognized:
        raise OSError("Serial inspection requires a verified CANable2 (USB 16d0:117e)")
    samples = []
    raw_frames = []
    identifiers = collections.Counter()
    with serial.Serial(str(device), baudrate=3000000, timeout=0.2, write_timeout=1,
                       rtscts=True, exclusive=True) as bus:
        try:
            # Adapter commands only: close, 1 Mbit/s, open with CAN ACKs.
            # No t/T/r/R command (CAN transmission) is ever sent.
            bus.write(b"C\rS8\rO\r")
            bus.flush()
            deadline = time.monotonic() + seconds
            pending = bytearray()
            while time.monotonic() < deadline:
                pending.extend(bus.read(min(max(bus.in_waiting, 1), 4096)))
                while b"\r" in pending:
                    line, _, remaining = pending.partition(b"\r")
                    pending = bytearray(remaining)
                    frame = decode_slcan(line)
                    if frame is None:
                        continue
                    can_id, payload = frame
                    identifiers[hex(can_id)] += 1
                    sample = decode_feedback(can_id, payload, motor_id)
                    if sample is not None:
                        samples.append(sample)
                        if len(raw_frames) < 20:
                            raw_frames.append({"can_id": hex(can_id), "data": payload.hex()})
                if len(pending) > 4096:
                    pending.clear()
        finally:
            bus.write(b"C\r")
            bus.flush()
    report = summarize(samples)
    report.update(serial_port=str(device), motor_id=motor_id, model="AK45-36",
                  raw_feedback=raw_frames, received_identifiers=dict(identifiers),
                  captured_at_unix=time.time())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    connection = parser.add_mutually_exclusive_group()
    connection.add_argument("--interface", default="can1")
    connection.add_argument("--serial", help="CANable2 serial path; adapter channel set to 1 Mbit/s")
    parser.add_argument("--motor-id", type=int, default=4)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.motor_id <= 255 or not math.isfinite(args.seconds) or not 0 < args.seconds <= 60:
        parser.error("motor-id must be 1..255 and seconds must be in (0, 60]")
    try:
        report = (inspect_serial(args.serial, args.motor_id, args.seconds) if args.serial else
                  inspect(args.interface, args.motor_id, args.seconds))
    except OSError as error:
        report = {"mode": "unknown", "interface": args.interface, "motor_id": args.motor_id,
                  "transmitted_frames": 0, "reason": str(error)}
    encoded = json.dumps(report, indent=2)
    print(encoded)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return 0 if report["mode"] != "unknown" else 2


if __name__ == "__main__":
    raise SystemExit(main())

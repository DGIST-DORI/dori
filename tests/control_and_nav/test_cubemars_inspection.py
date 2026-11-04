"""Ensure passive mode detection cannot mistake boot/command frames for state."""

import importlib.util
from pathlib import Path
import struct


SOURCE = Path(__file__).resolve().parents[2] / "tools/drive/inspect_cubemars.py"
SPEC = importlib.util.spec_from_file_location("inspect_cubemars", SOURCE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_servo_state_and_signed_position():
    data = struct.pack(">hhhbB", -1800, 25, -120, 30, 0)
    sample = module.decode_feedback(module.CAN_EFF_FLAG | 0x2904, data, 4)
    assert sample["mode"] == "servo"
    assert sample["position_deg"] == -180
    assert sample["speed_erpm"] == 250
    assert sample["current_a"] == -1.2
    assert sample["temperature_c"] == 30  # Servo has no MIT offset.
    assert module.decode_feedback(module.CAN_EFF_FLAG | 0x2903, data, 4) is None
    for function in (0x09, 0x2C, 0x04, 0x06):
        assert module.decode_feedback(module.CAN_EFF_FLAG | (function << 8) | 4, data, 4) is None


def test_mit_uses_ak45_36_ranges_and_requires_motor_id():
    sample = module.decode_feedback(4, bytes([4, 255, 255, 255, 255, 255, 30, 0]), 4)
    assert sample["mode"] == "mit"
    assert sample["velocity_rad_s"] == 6
    assert sample["torque_nm"] == 34
    assert module.decode_feedback(4, bytes([3, 255, 255, 255, 255, 255, 30, 0]), 4) is None
    assert module.decode_feedback(4, b"\xff" * 7 + b"\xfc", 4) is None


def test_mit_temperature_is_unsigned_byte_minus_40():
    for raw, celsius in ((0, -40), (80, 40), (200, 160), (255, 215)):
        sample = module.decode_feedback(4, bytes([4, 127, 255, 127, 247, 255, raw, 0]), 4)
        assert sample["temperature_c"] == celsius


def test_reject_short_remote_and_error_frames():
    data = bytes([4, 127, 255, 127, 247, 255, 30, 0])
    assert module.decode_feedback(4, data[:6], 4) is None
    assert module.decode_feedback(4 | module.CAN_RTR_FLAG, data, 4) is None
    assert module.decode_feedback(4 | module.CAN_ERR_FLAG, data, 4) is None


def test_silence_insufficient_or_conflicting_evidence_stays_unknown():
    servo = module.decode_feedback(module.CAN_EFF_FLAG | 0x2904, b"\0" * 8, 4)
    mit = module.decode_feedback(4, bytes([4, 127, 255, 127, 247, 255, 30, 0]), 4)
    for samples in ([], [servo], [servo, servo], [servo] * 3 + [mit]):
        assert module.summarize(samples)["mode"] == "unknown"
    assert module.summarize([servo] * 3)["mode"] == "servo"
    assert module.summarize([mit] * 3)["mode"] == "mit"


def test_faulted_motor_is_reported_without_claiming_ready():
    sample = module.decode_feedback(module.CAN_EFF_FLAG | 0x2904,
                                    struct.pack(">hhhbB", 123, 0, 0, 30, 5), 4)
    report = module.summarize([sample] * 3)
    assert report["faults"] == [5]
    assert report["position_span_deg"] == 0
    assert report["transmitted_frames"] == 0


def test_serial_frames_require_valid_ids_lengths_and_data():
    assert module.decode_slcan(b"T0000290480000000000001e00") == (
        module.CAN_EFF_FLAG | 0x2904, bytes.fromhex("0000000000001e00"))
    assert module.decode_slcan(b"t0048047fff7ff7ff1e00") == (
        4, bytes.fromhex("047fff7ff7ff1e00"))
    for frame in (b"", b"F00", b"r0040", b"t0049", b"t0048ff", b"tfff0", b"t0041zz"):
        assert module.decode_slcan(frame) is None

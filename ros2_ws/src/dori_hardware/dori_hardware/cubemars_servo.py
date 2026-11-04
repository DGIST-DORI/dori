"""CubeMars Servo CAN codec, in output-shaft units (AK manual V1.0.18 §5)."""

from dataclasses import dataclass
import math
import struct

EFF = 0x80000000
RTR = 0x40000000
ERR = 0x20000000
FRAME = struct.Struct("=IB3x8s")


@dataclass(frozen=True)
class ServoState:
    position_deg: float
    velocity_rad_s: float
    current_a: float
    temperature_c: int
    error: int


class ServoProtocol:
    def __init__(self, motor_id=4, pole_pairs=14, gear_ratio=36.0):
        if not isinstance(motor_id, int) or not 1 <= motor_id <= 255:
            raise ValueError("CAN motor ID must be 1..255")
        if not math.isfinite(gear_ratio) or gear_ratio <= 0 or pole_pairs <= 0:
            raise ValueError("Gear ratio and pole pairs must be positive")
        self.motor_id = motor_id
        self.electrical_ratio = pole_pairs * gear_ratio

    def feedback(self, can_id, data):
        if can_id != EFF | (0x29 << 8) | self.motor_id or len(data) != 8:
            return None
        position, speed, current, temperature, error = struct.unpack(">hhhbB", data)
        if abs(position) > 32000 or abs(speed) > 32000 or abs(current) > 6000:
            return None
        return ServoState(position / 10.0,
                          speed * 10.0 * 2 * math.pi / (60 * self.electrical_ratio),
                          current / 100.0, temperature, error)

    def position(self, degrees, speed_deg_s, accel_deg_s2):
        if not all(math.isfinite(v) for v in (degrees, speed_deg_s, accel_deg_s2)):
            raise ValueError("Position, speed and acceleration must be finite")
        if abs(degrees) > 3200 or speed_deg_s <= 0 or accel_deg_s2 <= 0:
            raise ValueError("Goal outside feedback range, or nonpositive motion limits")
        # Position is output degrees * 10000. Speed/acceleration are electrical
        # RPM(/s) divided by 10. The gearbox is applied to speed, NOT position.
        speed = round(speed_deg_s * self.electrical_ratio / 60.0)
        accel = round(accel_deg_s2 * self.electrical_ratio / 60.0)
        if not 1 <= speed <= 32767 or not 1 <= accel <= 32767:
            raise ValueError("Speed or acceleration cannot be represented by the protocol")
        return FRAME.pack(EFF | (6 << 8) | self.motor_id, 8,
                          struct.pack(">ihh", round(degrees * 10000), speed, accel))

    def stop(self):
        # Zero-speed Servo command; no origin reset, mode switch or MIT enable.
        return FRAME.pack(EFF | (3 << 8) | self.motor_id, 4, b"\0" * 8)


class Motor4Guard:
    """State/feedback/heartbeat gate, independently testable without a CAN bus."""

    def __init__(self, minimum, maximum, feedback_timeout=0.25, command_timeout=0.35):
        if not all(math.isfinite(v) for v in (minimum, maximum, feedback_timeout, command_timeout)):
            raise ValueError("Guard limits must be finite")
        if minimum >= maximum or feedback_timeout <= 0 or command_timeout <= 0:
            raise ValueError("Invalid guard limits")
        self.minimum, self.maximum = minimum, maximum
        self.feedback_timeout, self.command_timeout = feedback_timeout, command_timeout
        self.action_state = None
        self.state = None
        self.feedback_at = None
        self.command_at = None
        self.owned = False
        self.faulted = False

    def ready(self, now):
        return (not self.faulted and self.action_state == 2 and self.state is not None and
                self.state.error == 0 and self.feedback_at is not None and
                0 <= now - self.feedback_at <= self.feedback_timeout and
                self.minimum <= self.state.position_deg <= self.maximum)

    def accept(self, target, now):
        if not self.ready(now) or not math.isfinite(target) or not self.minimum <= target <= self.maximum:
            return False
        self.command_at = now
        return True

    def needs_stop(self, now):
        return self.owned and (not self.ready(now) or self.command_at is None or
                               not 0 <= now - self.command_at <= self.command_timeout)

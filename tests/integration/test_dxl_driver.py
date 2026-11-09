"""Run the installed DXL driver against a Protocol 2.0 pseudo-terminal.

No hardware: ROS_DOMAIN_ID=97 ROS_LOCALHOST_ONLY=1 python -m pytest <this file>
The only serial path passed to the binary is a newly allocated /dev/pts device.
"""
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("ROS_DOMAIN_ID") != "97" or os.environ.get("ROS_LOCALHOST_ONLY") != "1",
    reason="Requires isolated ROS domain 97 on localhost",
)
ROOT = Path(__file__).resolve().parents[2]
BINARY = ROOT / "ros2_ws/install/dori_hardware/lib/dori_hardware/dxl_driver_node"


def crc(data):
    value = 0
    for byte in data:
        value ^= byte << 8
        for _ in range(8):
            value = ((value << 1) ^ (0x8005 if value & 0x8000 else 0)) & 0xFFFF
    return value.to_bytes(2, "little")


class ServoBus:
    def __init__(self):
        self.master, self.slave = pty.openpty()
        self.path = os.ttyname(self.slave)
        self.registers = {1: bytearray(200), 3: bytearray(200)}
        for id_, model in ((1, 1140), (3, 1040)):
            self.put(id_, 0, model, 2)
            self.put(id_, 11, 3, 1)
            self.put(id_, 132, -4096 if id_ == 1 else 2048, 4)
        self.writes = []
        self.requests = []
        self.drop = set()
        self.packet_errors = set()
        self.stopped = threading.Event()
        self.error = None
        self.worker = threading.Thread(target=self.run, daemon=True)

    def put(self, id_, address, value, size):
        self.registers[id_][address:address + size] = (value & ((1 << (8 * size)) - 1)).to_bytes(size, "little")

    def run(self):
        buffer = bytearray()
        try:
            while not self.stopped.is_set():
                if not select.select([self.master], [], [], .02)[0]:
                    continue
                buffer.extend(os.read(self.master, 4096))
                while len(buffer) >= 7:
                    assert buffer[:4] == b"\xff\xff\xfd\x00", buffer
                    size = int.from_bytes(buffer[5:7], "little") + 7
                    if len(buffer) < size:
                        break
                    frame = bytes(buffer[:size])
                    del buffer[:size]
                    assert crc(frame[:-2]) == frame[-2:]
                    id_ = frame[4]
                    body = frame[7:-2].replace(b"\xff\xff\xfd\xfd", b"\xff\xff\xfd")
                    instruction = body[0]
                    address = int.from_bytes(body[1:3], "little")
                    self.requests.append((id_, instruction, address))
                    assert id_ in (1, 3), "Driver addressed a retired or broadcast ID"
                    key = (id_, instruction, address)
                    if key in self.drop:
                        continue
                    error = 4 if key in self.packet_errors else 0
                    if instruction == 2:  # READ
                        length = int.from_bytes(body[3:5], "little")
                        data = self.registers[id_][address:address + length]
                    elif instruction == 3:  # WRITE
                        data = b""
                        if not error:
                            self.registers[id_][address:address + len(body[3:])] = body[3:]
                            self.writes.append((id_, address, int.from_bytes(body[3:], "little")))
                    else:
                        raise AssertionError(f"Unexpected instruction {instruction}")
                    status = (b"\x55" + bytes([error]) + data).replace(b"\xff\xff\xfd", b"\xff\xff\xfd\xfd")
                    packet = b"\xff\xff\xfd\x00" + bytes([id_]) + (len(status) + 2).to_bytes(2, "little") + status
                    os.write(self.master, packet + crc(packet))
        except BaseException as exc:
            self.error = exc

    def close(self):
        self.stopped.set()
        self.worker.join(timeout=2)
        os.close(self.master)
        os.close(self.slave)
        assert self.error is None, self.error


@pytest.fixture
def driver(tmp_path):
    processes = []
    buses = []
    logs = []

    def start(configure=lambda bus: None):
        bus = ServoBus()
        configure(bus)
        buses.append(bus)
        bus.worker.start()
        path = tmp_path / f"driver-{len(buses)}.log"
        log = path.open("w")
        logs.append(log)
        process = subprocess.Popen([str(BINARY), "--ros-args", "-p", f"device_name:={bus.path}"], stdout=log, stderr=log)
        processes.append(process)
        return bus, process, path

    yield start
    for process in processes:
        if process.poll() is None:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    for bus in buses:
        bus.close()
    for log in logs:
        log.close()


def test_position_errors_stops_and_startup_profiles(driver):
    import rclpy
    from rclpy.context import Context
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import QoSProfile, DurabilityPolicy
    from std_msgs.msg import Int32
    from dynamixel_sdk_custom_interfaces.msg import SetPosition
    from dynamixel_sdk_custom_interfaces.srv import GetPosition

    bus, process, log = driver()
    context = Context()
    rclpy.init(context=context)
    node = rclpy.create_node("dxl_test_client", context=context)
    executor = SingleThreadedExecutor(context=context)
    executor.add_node(node)
    client = node.create_client(GetPosition, "/get_position")
    state = node.create_publisher(Int32, "/system/action_state", QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
    command = node.create_publisher(SetPosition, "/set_position", 20)
    stop = node.create_publisher(SetPosition, "/stop_position", 20)

    def until(condition, timeout=8):
        deadline = time.monotonic() + timeout
        while not condition():
            assert process.poll() is None, log.read_text()
            assert bus.error is None, bus.error
            assert time.monotonic() < deadline, log.read_text()
            executor.spin_once(timeout_sec=.02)

    def read_position(id_):
        future = client.call_async(GetPosition.Request(id=id_))
        until(future.done)
        return future.result().position

    def settle():
        deadline = time.monotonic() + .2
        while time.monotonic() < deadline:
            executor.spin_once(timeout_sec=.02)

    try:
        until(lambda: client.service_is_ready() and all(pub.get_subscription_count() for pub in (state, command, stop)))
        for id_, mode, acceleration, velocity, position in ((1, 4, 5, 15, 0xFFFFF000), (3, 3, 400, 500, 2048)):
            assert bus.registers[id_][11] == mode
            assert (id_, 108, acceleration) in bus.writes
            assert (id_, 112, velocity) in bus.writes
            assert bus.writes.index((id_, 116, position)) < bus.writes.index((id_, 64, 1))
        assert (3, 80, 250) in bus.writes and (3, 84, 1500) in bus.writes
        assert read_position(1) == -4096
        assert read_position(3) == 2048
        assert read_position(2) == -(2**31)
        bus.drop.add((1, 2, 132))
        assert read_position(1) == -(2**31)
        bus.drop.clear()
        bus.packet_errors.add((3, 2, 132))
        assert read_position(3) == -(2**31)
        bus.packet_errors.clear()

        before = len(bus.writes)
        command.publish(SetPosition(id=1, position=-100))
        settle()
        assert len(bus.writes) == before, "No movement before supervisor state"
        state.publish(Int32(data=0))
        settle()
        command.publish(SetPosition(id=1, position=-100))
        until(lambda: (1, 116, 2**32 - 100) in bus.writes)
        before = len(bus.writes)
        command.publish(SetPosition(id=2, position=100))
        command.publish(SetPosition(id=3, position=-1))
        settle()
        assert len(bus.writes) == before

        stop.publish(SetPosition(id=1))
        until(lambda: (1, 116, 0xFFFFF000) in bus.writes[before:])
        before = len(bus.writes)
        state.publish(Int32(data=4))
        until(lambda: len(bus.writes) >= before + 2)
        before = len(bus.writes)
        command.publish(SetPosition(id=1, position=100))
        settle()
        assert len(bus.writes) == before

        state.publish(Int32(data=0))
        settle()
        bus.drop.add((1, 2, 132))
        stop.publish(SetPosition(id=1))
        until(lambda: (1, 64, 0) in bus.writes[before:])
        bus.drop.clear()
        before = len(bus.writes)
        command.publish(SetPosition(id=3, position=2000))
        settle()
        assert len(bus.writes) == before, "Hold failure must latch a fault"
        process.send_signal(signal.SIGINT)
        assert process.wait(timeout=5) == 0, log.read_text()
        assert (3, 64, 0) in bus.writes[before:]
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.try_shutdown(context=context)


@pytest.mark.parametrize("problem", ["wrong_model", "missing_servo", "wrong_profile", "setup_error"])
def test_initialization_fails_without_enabling_unknown_hardware(driver, problem):
    def configure(bus):
        if problem == "wrong_model":
            bus.put(3, 0, 999, 2)
        elif problem == "missing_servo":
            bus.drop.add((3, 2, 0))
        elif problem == "wrong_profile":
            bus.put(1, 10, 4, 1)
        else:
            bus.packet_errors.add((1, 3, 108))
    bus, process, log = driver(configure)
    assert process.wait(timeout=8) == 1, log.read_text()
    if problem == "setup_error":
        assert not any(address == 64 and value == 1 for _, address, value in bus.writes)
        assert (1, 64, 0) in bus.writes and (3, 64, 0) in bus.writes
    else:
        assert not bus.writes, "Identification failures must not modify servo registers"

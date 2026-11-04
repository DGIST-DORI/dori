"""No hardware: verify CAN goal refresh and the controller-loss stop."""
import os
from unittest.mock import Mock, patch

import rclpy
from std_msgs.msg import Float64, Int32
from dori_hardware.cubemars_servo import FRAME, ServoState
from dori_hardware.motor4_servo_node import Motor4ServoNode


def main():
    assert os.environ.get("ROS_DOMAIN_ID") == "87"
    bus = Mock()
    bus.send.side_effect = lambda frame: len(frame)
    bus.recvmsg.side_effect = BlockingIOError
    now = [10.0]
    rclpy.init()
    with patch("dori_hardware.motor4_servo_node.socket.socket", return_value=bus):
        node = Motor4ServoNode()
    try:
        assert bus.send.call_count == 0, "Startup must be receive-only"
        with patch("dori_hardware.motor4_servo_node.time.monotonic", side_effect=lambda: now[0]):
            node.guard.state = ServoState(-90.0, 0.0, 0.0, 64, 0)
            node.guard.feedback_at = now[0]
            node.action(Int32(data=2))
            for tick in (10.0, 10.1, 10.2):
                now[0] = tick
                node.guard.feedback_at = tick
                node.command(Float64(data=0.0))
            frames = [call.args[0] for call in bus.send.call_args_list]
            assert len(frames) == 3 and len(set(frames)) == 1, "Unchanged goals must refresh CAN"
            now[0] = 10.6
            node.guard.feedback_at = now[0]  # Motor alive, but controller stopped.
            node.poll()
            assert not node.guard.owned and node.guard.faulted
            assert FRAME.unpack(bus.send.call_args.args[0])[0] == 0x80000304
            calls = bus.send.call_count
            node.command(Float64(data=0.0))
            assert bus.send.call_count == calls, "Faulted bridge must not resume motion"
        print("PASS: receive-only startup, repeated goals refresh CAN, lost heartbeat stops, fault latches")
    finally:
        node.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()

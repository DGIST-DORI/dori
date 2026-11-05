"""Read-only hardware telemetry and supervisor-mediated posture commands."""

import math
import time
import uuid

from fastapi import HTTPException
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool, Float64, Int32
from dori_msgs.msg import CommandFeedback, SystemError


JOINTS = (
    ("left_wheel_joint", "왼쪽 바퀴 · M1", "/joint_states"),
    ("right_wheel_joint", "오른쪽 바퀴 · M2", "/joint_states"),
    ("motor_3_joint", "몸체 서보 · M3", "/dxl_joint_states"),
    ("motor_4_joint", "변형 서보 · M4", "/motor4/joint_states"),
    ("motor_5_joint", "서보 · M5", "/dxl_joint_states"),
)
FEEDBACK_TIMEOUT = 0.5


def finite(value):
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else None


class HardwareControlMixin:
    def _init_hardware_control(self):
        self._hardware_joints = {}
        self._hardware_values = {}
        self._hardware_feedback = {}
        self._stop_latched = False
        self._move_owner = None
        self._control_epoch = uuid.uuid4().hex
        # One runtime authority, shared by every dashboard. Never restore motion permission on restart.
        self._live_control_enabled = False
        self.pub_resume = self.create_publisher(Bool, "/emergency_go", 10)
        self.pub_transform = self.create_publisher(Int32, "/manual/transform_cmd", 10)
        for topic in dict.fromkeys(row[2] for row in JOINTS):
            self.create_subscription(JointState, topic,
                                     lambda msg, source=topic: self._record_joints(source, msg),
                                     qos_profile_sensor_data)
        for topic, kind in (("body/pitch", Float64), ("body/pitch_rate", Float64),
                            ("body/stabilization_torque", Float64),
                            ("system/transform_pose", Int32), ("transform/status", Int32)):
            self.create_subscription(kind, "/" + topic,
                                     lambda msg, key=topic: self._record_value(key, msg), 10)
        for topic in ("drive/command_feedback", "transform/command_feedback"):
            self.create_subscription(CommandFeedback, "/" + topic,
                                     lambda msg, key=topic: self._record_feedback(key, msg), 10)
        self.create_subscription(SystemError, "/system/error", self._record_error, 10)

    def _record_joints(self, source, msg):
        now = time.monotonic()
        expected = {name for name, _, topic in JOINTS if topic == source}
        with self._control_lock:
            for index, name in enumerate(msg.name):
                if name not in expected:
                    continue
                def at(values):
                    return finite(values[index]) if index < len(values) else None
                self._hardware_joints[name] = {
                    "position": at(msg.position), "velocity": at(msg.velocity),
                    "effort": at(msg.effort), "received": now,
                }

    def _record_value(self, key, msg):
        with self._control_lock:
            self._hardware_values[key] = {"value": finite(msg.data), "received": time.monotonic()}

    def _record_feedback(self, key, msg):
        with self._control_lock:
            self._hardware_feedback[key] = {
                "accepted": msg.accepted, "code": msg.code, "message": msg.message,
                "received": time.monotonic(),
            }

    def _record_error(self, msg):
        with self._control_lock:
            self._hardware_feedback["system/error"] = {
                "accepted": False, "code": msg.error_code,
                "message": msg.description, "source": msg.source_node,
                "received": time.monotonic(),
            }

    def hardware_state(self):
        with self._control_lock:
            now = time.monotonic()
            def snapshot(value):
                result = {key: val for key, val in value.items() if key != "received"}
                result["age"] = max(0.0, now - value["received"]) if value else None
                return result
            supervisor = bool(self.pub_mode.get_subscription_count()
                              and self.pub_stop.get_subscription_count()
                              and self.count_publishers("/system/control_mode")
                              and self.count_publishers("/system/action_state")
                              and self._mode is not None and self._action_state is not None)
            joints = [{"name": name, "label": label, "topic": topic,
                       **snapshot(self._hardware_joints.get(name, {}))}
                      for name, label, topic in JOINTS]
            for joint in joints:
                joint["fresh"] = (joint["age"] is not None and joint["age"] < FEEDBACK_TIMEOUT
                                  and joint.get("position") is not None)
            return {
                "live_enabled": self._live_control_enabled,
                "executor": "bridge" if self._live_control_enabled else "dry-run",
                "supervisor_available": supervisor,
                "mode": self._mode, "action_state": self._action_state,
                "stop_latched": self._stop_latched,
                "control_epoch": self._control_epoch,
                "move_owner": self._move_owner,
                "manual_input_conflict": self.count_publishers("/manual/cmd_vel") > 1,
                "transform_available": bool(self.pub_transform.get_subscription_count()
                                            and self.count_subscribers("/transform/request")),
                "joints": joints,
                "values": {key: snapshot(value) for key, value in self._hardware_values.items()},
                "feedback": {key: snapshot(value) for key, value in self._hardware_feedback.items()},
            }

    def execute_control(self, action, params):
        """Serialize permission changes with commands, on the same lock as the watchdog."""
        with self._control_lock:
            disabling = action == "set_live_control" and not params["enabled"]
            epoch = params.get("control_epoch")
            if action != "stop" and not disabling:
                if ((epoch is not None and epoch != self._control_epoch)
                        or (epoch is None and (self._live_control_enabled or action == "set_live_control"))):
                    raise HTTPException(409, "Control state changed; refresh before commanding motion")
            if action == "set_live_control":
                enabled = params["enabled"]
                changed = enabled != self._live_control_enabled
                if enabled and changed:
                    state = self.hardware_state()
                    if not state["supervisor_available"]:
                        raise HTTPException(503, "로봇 제어기가 연결되지 않았습니다.")
                    if state["manual_input_conflict"]:
                        raise HTTPException(409, "조이스틱 또는 키보드 입력이 활성화되어 있습니다. 해당 입력을 종료한 뒤 실제 제어를 켜세요.")
                if changed:
                    # Invalidate old simulated/live requests and latch a stop before changing permission.
                    self.request_stop()
                    self._live_control_enabled = enabled
                elif not enabled:
                    # An already-off request still cancels an enable request delayed in transit.
                    self._control_epoch = uuid.uuid4().hex
                return {"executed": changed, "changed": changed,
                        "executor": "bridge" if enabled else "dry-run",
                        "control_state": self.hardware_state()}
            if not self._live_control_enabled:
                if action == "stop":
                    self._control_epoch = uuid.uuid4().hex
                return {"executed": False, "executor": "dry-run", "detail": "Validated only; live control is off"}
            self.control_action(action, params)
            return {"executed": True, "executor": "bridge", "detail": "Published through supervisor"}

    def hardware_action(self, action, params):
        # Called under BridgeNode's control lock. Commands never bypass the supervisor.
        state = self.hardware_state()
        if not state["supervisor_available"]:
            raise HTTPException(503, "Supervisor is unavailable")
        if state["manual_input_conflict"]:
            raise HTTPException(409, "Another manual input publisher is active")
        if action == "resume":
            if self._action_state not in (3, 4, 5) and not self._stop_latched:
                raise HTTPException(409, "Robot is not stopped or paused")
            if not self.pub_resume.get_subscription_count():
                raise HTTPException(503, "Supervisor resume is unavailable")
            self._move_command = None
            self._move_deadline = 0.0
            self.pub_resume.publish(Bool(data=True))
            self._stop_latched = False
            # Wait for a supervisor state message before enabling new motion.
            self._action_state = None
            return
        if (self._stop_latched or self._mode != 0 or self._action_state not in (0, 1)
                or self._move_command is not None):
            raise HTTPException(409, "Stop manual driving and select MANUAL before transforming")
        if not state["transform_available"]:
            raise HTTPException(503, "Transform controller is unavailable")
        if not all(joint["fresh"] for joint in state["joints"][:4]):
            raise HTTPException(409, "Fresh feedback from motors 1–4 is required")
        self.pub_transform.publish(Int32(data={"A": 1, "B": 2}[params["pose"]]))
        self._action_state = 2

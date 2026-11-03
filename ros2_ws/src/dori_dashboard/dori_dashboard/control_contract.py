"""Dashboard commands use the supervisor's normalized manual input contract."""

import math

from fastapi import HTTPException

CONTROL_MODES = {"manual": 0, "auto": 1}
CONTROL_ACTIONS = frozenset({"move", "stop", "set_mode"})
MOVE_TIMEOUT = 0.5


def validate_control(body: dict) -> tuple[str, dict]:
    action = body.get("action")
    params = body.get("params", {})
    if not isinstance(action, str) or action.strip().lower() not in CONTROL_ACTIONS:
        raise HTTPException(400, f"action must be one of: {sorted(CONTROL_ACTIONS)}")
    action = action.strip().lower()
    if not isinstance(params, dict):
        raise HTTPException(400, "params must be an object")
    validated = {}
    if action == "move":
        # These are normalized joystick inputs, NOT m/s or rad/s. The robot
        # cannot translate sideways. Validate again at the internal boundary.
        for field, limit in (("linear_x", 0.8), ("linear_y", 0.0), ("angular_z", 1.0)):
            value = params.get(field, 0.0)
            if type(value) not in (int, float):
                raise HTTPException(400, f"{field} must be a finite number")
            try:
                value = float(value)
            except (ValueError, OverflowError):
                raise HTTPException(400, f"{field} must be a finite number") from None
            if not math.isfinite(value) or not -limit <= value <= limit:
                raise HTTPException(400, f"{field} must be finite and in [{-limit}, {limit}]")
            validated[field] = value
    elif action == "set_mode":
        mode = params.get("mode")
        if not isinstance(mode, str) or mode.strip().lower() not in CONTROL_MODES:
            raise HTTPException(400, f"mode must be one of: {sorted(CONTROL_MODES)}")
        validated["mode"] = mode.strip().lower()
    return action, validated

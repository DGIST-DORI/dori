"""Startup must not repeat requests whose outcome is unknown."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from controller_manager_msgs.srv import LoadController
from dori_hardware.controller_startup import ACTIVE, STANDBY, call_once, initialize_controllers


def test_slow_response_does_not_resubmit_load(monkeypatch):
    node = Mock()
    future = node.create_client.return_value.call_async.return_value
    future.done.return_value = False
    spin = Mock()
    monkeypatch.setattr("rclpy.spin_until_future_complete", spin)
    with pytest.raises(RuntimeError, match="outcome unknown, no retry sent"):
        call_once(node, LoadController, "/controller_manager/load_controller",
                  LoadController.Request(name="joint_state_broadcaster"), 60)
    node.create_client.return_value.call_async.assert_called_once()
    assert spin.call_args.kwargs["timeout_sec"] == 60
    node.destroy_client.assert_called_once()


@pytest.mark.parametrize("failed_controller", [None, "left_bldc_drive_controller", "bldc_position_controller"])
def test_initialization_is_serial_and_keeps_standby_controllers_inactive(failed_controller):
    states, requests = {}, []
    def call(service, endpoint, request):
        requests.append((endpoint, getattr(request, "name", None)))
        if endpoint == "list_controllers":
            return SimpleNamespace(controller=[SimpleNamespace(name=n, state=s) for n, s in states.items()])
        if endpoint == "load_controller":
            if request.name == failed_controller:
                return SimpleNamespace(ok=False)
            assert request.name not in states
            states[request.name] = "unconfigured"
        elif endpoint == "configure_controller":
            assert states[request.name] == "unconfigured"
            states[request.name] = "inactive"
        elif endpoint == "switch_controller":
            assert set(request.activate_controllers) == set(ACTIVE)
            assert request.strictness == request.STRICT
            assert not request.activate_asap
            assert all(states[n] == "inactive" for n in ACTIVE)
            states.update(dict.fromkeys(ACTIVE, "active"))
        return SimpleNamespace(ok=True)
    if failed_controller:
        with pytest.raises(RuntimeError, match=failed_controller):
            initialize_controllers(call)
        assert requests[-1] == ("load_controller", failed_controller)
    else:
        initialize_controllers(call)
        assert states == {**dict.fromkeys(ACTIVE, "active"), **dict.fromkeys(STANDBY, "inactive")}
        assert len(requests) == len(set(requests)) + 1  # Only read-only list is repeated.

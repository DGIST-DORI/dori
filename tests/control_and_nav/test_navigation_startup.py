import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from geometry_msgs.msg import TransformStamped
from tf2_ros import TransformException

path = Path(__file__).resolve().parents[2] / 'ros2_ws/src/dori_navigation/scripts/navigation_startup.py'
spec = importlib.util.spec_from_file_location('navigation_startup_under_test', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def gate():
    node = Mock()
    node.future = None
    transform = TransformStamped()
    transform.header.stamp.sec = 100
    node.buffer.lookup_transform.return_value = transform
    node.get_clock.return_value.now.return_value.nanoseconds = 101_000_000_000
    node.client.service_is_ready.return_value = True
    node.client.call_async.return_value.done.return_value = False
    return node


def test_no_initial_pose_does_not_start_nav2(gate):
    gate.buffer.lookup_transform.side_effect = TransformException('map frame absent')
    module.NavigationStartup.tick(gate)
    gate.client.call_async.assert_not_called()


@pytest.mark.parametrize('age', [3, -2])
def test_stale_or_invalid_localization_does_not_start_nav2(gate, age):
    gate.get_clock.return_value.now.return_value.nanoseconds = (100 + age) * 1_000_000_000
    module.NavigationStartup.tick(gate)
    gate.client.call_async.assert_not_called()


def test_fresh_localization_starts_once_and_waits_for_success(gate):
    module.NavigationStartup.tick(gate)
    module.NavigationStartup.tick(gate)
    gate.client.call_async.assert_called_once()
    request = gate.client.call_async.call_args.args[0]
    assert request.command == request.STARTUP
    gate.timer.cancel.assert_not_called()
    gate.future.done.return_value = True
    gate.future.result.return_value = SimpleNamespace(success=True)
    module.NavigationStartup.tick(gate)
    gate.timer.cancel.assert_called_once()


def test_failed_startup_is_not_silently_accepted(gate):
    module.NavigationStartup.tick(gate)
    gate.future.done.return_value = True
    gate.future.result.return_value = SimpleNamespace(success=False)
    with pytest.raises(RuntimeError, match='startup failed'):
        module.NavigationStartup.tick(gate)
    gate.timer.cancel.assert_not_called()

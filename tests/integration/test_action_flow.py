"""Real ROS action transport; the backend substitutes only the Nav2 action server."""
import math
import os
import threading
import time

import pytest
import rclpy
from action_msgs.msg import GoalStatus
from dori_msgs.action import Navigate
from dori_navigation.nav2_adapter import Nav2Adapter
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient, ActionServer, CancelResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import QoSProfile, DurabilityPolicy
from std_msgs.msg import Bool, Int32


def wait(predicate, timeout=5):
    end = time.monotonic()+timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('Timed out waiting for ROS condition')


def resolved(future, timeout=5):
    wait(future.done, timeout)
    return future.result()


class Backend(Node):
    def __init__(self):
        super().__init__('test_nav2_backend')
        self.delay = 0.
        self.finish = False
        self.cancel_seen = False
        self.accepted = 0
        self.active = 0
        self.max_active = 0
        self.refuse_cancel = False
        self.server = ActionServer(self, NavigateToPose, '/dori/internal/navigate_to_pose',
            execute_callback=self.execute, goal_callback=self.goal,
            cancel_callback=lambda _: CancelResponse.REJECT if self.refuse_cancel else CancelResponse.ACCEPT,
            callback_group=ReentrantCallbackGroup())

    def goal(self, _):
        from rclpy.action import GoalResponse
        time.sleep(self.delay)
        return GoalResponse.ACCEPT

    def execute(self, handle):
        self.accepted += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            end = time.monotonic()+10
            while rclpy.ok() and time.monotonic()<end:
                if handle.is_cancel_requested:
                    self.cancel_seen = True
                    handle.canceled()
                    return NavigateToPose.Result()
                f = NavigateToPose.Feedback()
                f.current_pose = handle.request.pose
                f.current_pose.header.stamp = self.get_clock().now().to_msg()
                f.distance_remaining = .1
                handle.publish_feedback(f)
                if self.finish:
                    handle.succeed()
                    return NavigateToPose.Result()
                time.sleep(.02)
            handle.abort()
            return NavigateToPose.Result()
        finally:
            self.active -= 1


@pytest.fixture
def graph():
    assert os.getenv('ROS_DOMAIN_ID') == '96' and os.getenv('ROS_LOCALHOST_ONLY') == '1'
    rclpy.init()
    backend, adapter, probe = Backend(), Nav2Adapter(), Node('test_action_probe')
    executor = MultiThreadedExecutor(num_threads=8)
    for node in (backend, adapter, probe):
        executor.add_node(node)
    worker = threading.Thread(target=executor.spin)
    worker.start()
    client = ActionClient(probe, Navigate, '/dori/nav/navigate_to')
    assert client.wait_for_server(timeout_sec=5)
    mode = probe.create_publisher(Int32, '/NAVIGATION_MODE', 10)
    hardware = probe.create_publisher(Int32, '/system/action_state', QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
    estop = probe.create_publisher(Bool, '/emergency_stop', 10)
    wait(lambda: mode.get_subscription_count() > 0 and hardware.get_subscription_count() > 0)
    hardware.publish(Int32(data=1))
    wait(lambda: not adapter._inhibited)
    def arm():
        mode.publish(Int32(data=1))
        wait(lambda: adapter._enabled)
    yield backend, adapter, client, mode, estop, arm
    backend.finish = True
    mode.publish(Int32(data=0))
    wait(lambda: not adapter._busy and backend.active == 0, 8)
    executor.shutdown(timeout_sec=3)
    worker.join(timeout=3)
    for node in (probe, adapter, backend):
        node.destroy_node()
    rclpy.shutdown()


def goal(x=1.):
    request = Navigate.Goal()
    request.destination = PoseStamped()
    request.destination.header.frame_id = 'map'
    request.destination.pose.position.x = float(x)
    request.destination.pose.orientation.w = 1.
    return request


def test_disarmed_invalid_and_inhibited_goals_are_rejected(graph):
    backend, adapter, client, _, _, arm = graph
    assert not resolved(client.send_goal_async(goal())).accepted
    arm()
    for request in (goal(math.nan), goal(math.inf)):
        assert not resolved(client.send_goal_async(request)).accepted
    request = goal(); request.destination.pose.orientation.w = 0.
    assert not resolved(client.send_goal_async(request)).accepted
    adapter._hardware(Int32(data=4))
    assert not resolved(client.send_goal_async(goal())).accepted
    assert backend.accepted == 0


def test_success_and_concurrent_goal_reservation(graph):
    backend, adapter, client, _, _, arm = graph
    arm()
    a, b = client.send_goal_async(goal()), client.send_goal_async(goal(2))
    handles = [resolved(a), resolved(b)]
    assert sum(h.accepted for h in handles) == 1
    accepted = next(h for h in handles if h.accepted)
    wait(lambda: backend.active == 1)
    backend.finish = True
    result = resolved(accepted.get_result_async())
    assert result.status == GoalStatus.STATUS_SUCCEEDED and result.result.code == 0
    assert backend.max_active == 1
    wait(lambda: not adapter._busy)


def test_cancel_before_backend_acceptance_cancels_late_goal(graph):
    backend, adapter, client, _, _, arm = graph
    backend.delay = .5
    arm()
    handle = resolved(client.send_goal_async(goal()))
    assert handle.accepted
    assert resolved(handle.cancel_goal_async()).goals_canceling
    result = resolved(handle.get_result_async())
    assert result.status == GoalStatus.STATUS_CANCELED
    assert result.result.code == Navigate.Result.CANCELED
    wait(lambda: backend.cancel_seen and backend.active == 0)
    assert not adapter._busy


def test_estop_cancels_backend_and_disarms(graph):
    backend, adapter, client, _, estop, arm = graph
    arm()
    handle = resolved(client.send_goal_async(goal()))
    wait(lambda: backend.active == 1)
    estop.publish(Bool(data=True))
    result = resolved(handle.get_result_async())
    assert result.result.code == Navigate.Result.CANCELED
    assert backend.cancel_seen
    assert not adapter._enabled
    assert not resolved(client.send_goal_async(goal())).accepted


def test_accept_timeout_cancels_orphan_and_latches_fault(graph):
    backend, adapter, client, _, _, arm = graph
    adapter.set_parameters([Parameter('accept_timeout', value=.1)])
    backend.delay = .5
    arm()
    handle = resolved(client.send_goal_async(goal()))
    result = resolved(handle.get_result_async())
    assert result.result.code == Navigate.Result.INVALID_STATE
    assert adapter._fault
    wait(lambda: backend.cancel_seen)
    assert not resolved(client.send_goal_async(goal())).accepted


def test_refused_cancel_times_out_and_stays_disarmed(graph):
    backend, adapter, client, _, _, arm = graph
    adapter.set_parameters([Parameter('cancel_timeout', value=.2)])
    backend.refuse_cancel = True
    arm()
    handle = resolved(client.send_goal_async(goal()))
    wait(lambda: backend.active == 1)
    resolved(handle.cancel_goal_async())
    result = resolved(handle.get_result_async())
    assert result.result.code == Navigate.Result.INVALID_STATE
    assert adapter._fault and not adapter._enabled
    assert not resolved(client.send_goal_async(goal())).accepted

"""Initialize DORI controllers serially, without retrying state-changing calls."""

from launch.actions import EmitEvent, LogInfo, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch_ros.actions import Node

ACTIVE = ("joint_state_broadcaster", "left_bldc_drive_controller", "right_bldc_drive_controller")
STANDBY = ("left_bldc_effort_controller", "right_bldc_effort_controller", "bldc_position_controller")


def controller_startup_actions(manager="/controller_manager"):
    spawner = Node(package="dori_hardware", executable="controller_spawner",
                   arguments=["--controller-manager", manager], output="screen")

    def finished(event, context):
        if context.is_shutdown:
            return []
        if event.returncode != 0:
            return [EmitEvent(event=Shutdown(reason="Controller initialization failed"))]
        return [LogInfo(msg="DORI controllers ready: drive active; effort/position inactive")]

    return [RegisterEventHandler(OnProcessExit(target_action=spawner, on_exit=finished)), spawner]


def initialize_controllers(call):
    from controller_manager_msgs.srv import (
        ConfigureController, ListControllers, LoadController, SwitchController,
    )
    expected = {**dict.fromkeys(ACTIVE, "active"), **dict.fromkeys(STANDBY, "inactive")}
    current = {c.name: c.state for c in call(ListControllers, "list_controllers",
                                            ListControllers.Request()).controller}
    if all(current.get(name) == state for name, state in expected.items()):
        return
    if current.keys() & expected.keys():
        raise RuntimeError("DORI controllers already exist in unexpected states; restart the robot session")

    def load_configure(names):
        for name in names:
            for service, endpoint in ((LoadController, "load_controller"),
                                      (ConfigureController, "configure_controller")):
                if not call(service, endpoint, service.Request(name=name)).ok:
                    raise RuntimeError(f"{endpoint} failed for {name}")

    load_configure(ACTIVE)
    request = SwitchController.Request()
    request.activate_controllers = list(ACTIVE)
    request.strictness = SwitchController.Request.STRICT
    request.activate_asap = False
    request.timeout.sec = 30
    if not call(SwitchController, "switch_controller", request).ok:
        raise RuntimeError("Failed to activate the drive controller group")
    load_configure(STANDBY)
    actual = {c.name: c.state for c in call(ListControllers, "list_controllers",
                                          ListControllers.Request()).controller}
    if any(actual.get(name) != state for name, state in expected.items()):
        raise RuntimeError(f"Unexpected controller states after initialization: {actual}")


def call_once(node, service, endpoint, request, timeout):
    import rclpy
    client = node.create_client(service, endpoint)
    try:
        if not client.wait_for_service(timeout_sec=timeout):
            raise RuntimeError(f"Controller service unavailable: {endpoint}")
        future = client.call_async(request)
        rclpy.spin_until_future_complete(node, future, timeout_sec=timeout)
        if not future.done():
            raise RuntimeError(f"{endpoint} timed out after {timeout:g}s; outcome unknown, no retry sent")
        return future.result()
    finally:
        node.destroy_client(client)


def main():
    import argparse
    import rclpy
    from rclpy.executors import ExternalShutdownException

    parser = argparse.ArgumentParser()
    parser.add_argument("--controller-manager", default="/controller_manager")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(rclpy.utilities.remove_ros_args()[1:])
    if not 1 <= args.timeout <= 120:
        parser.error("--timeout must be between 1 and 120 seconds")
    rclpy.init()
    node = rclpy.create_node("controller_spawner")
    try:
        def call(service, name, request):
            endpoint = args.controller_manager.rstrip("/") + "/" + name
            node.get_logger().info(f"Initializing controllers: {name}")
            return call_once(node, service, endpoint, request, args.timeout)
        initialize_controllers(call)
        return 0
    except (KeyboardInterrupt, ExternalShutdownException):
        return 1
    except RuntimeError as exc:
        if rclpy.ok():
            node.get_logger().error(str(exc))
        return 1
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


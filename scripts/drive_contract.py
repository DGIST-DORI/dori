"""Read-only checks of the live SI -> TTA -> joystick -> motor command route."""
import math
from pathlib import Path

import yaml
from rcl_interfaces.srv import GetParameters

ROOT = Path(__file__).resolve().parents[1]
ROUTES = {
    '/nav/cmd_vel_raw': (['behavior_server', 'controller_server'], 'velocity_smoother'),
    '/nav/cmd_vel': (['velocity_smoother'], 'nav_drive_bridge'),
    '/auto/cmd_vel': (['nav_drive_bridge'], 'mode_manager_node'),
    '/drive/cmd_vel': (['mode_manager_node'], 'drive_controller_node'),
}


def check_drive_contract(node, wait_future, *, check_routes=True):
    """Caller must spin node while wait_future waits; does not publish commands."""
    errors = []
    report = {'parameters': {}, 'routes': {}}
    geometry = yaml.safe_load((ROOT/'ros2_ws/src/dori_drive/config/kinematics.yaml').read_text())['/**']['ros__parameters']
    calibration = yaml.safe_load((ROOT/'ros2_ws/src/dori_navigation/config/motion_interpreter.yaml').read_text())['nav_drive_bridge']['ros__parameters']
    for name, expected in (('drive_controller_node', geometry), ('nav_drive_bridge', geometry | calibration)):
        client = node.create_client(GetParameters, '/'+name+'/get_parameters')
        try:
            if not client.wait_for_service(timeout_sec=1):
                errors.append(name+': parameter service missing'); continue
            request = GetParameters.Request(names=list(expected))
            future = client.call_async(request)
            wait_future(future, 2)
            if not future.done() or future.result() is None:
                client.remove_pending_request(future)
                errors.append(name+': parameter query timed out'); continue
            values = future.result().values
            if len(values) != len(expected):
                errors.append(name+': incomplete parameters'); continue
            actual = report['parameters'][name] = {}
            for (key, value), result in zip(expected.items(), values):
                actual[key] = result.bool_value if result.type == 1 else result.double_value if result.type == 3 else None
                matches = (result.type == 1 and result.bool_value == value) if isinstance(value, bool) else (
                    result.type == 3 and math.isclose(result.double_value, value, rel_tol=1e-8))
                if not matches: errors.append(name+': calibration mismatch: '+key)
        finally:
            node.destroy_client(client)
    if check_routes:
        names = [(name, namespace) for name, namespace in node.get_node_names_and_namespaces()]
        for owner in {name for owners, _ in ROUTES.values() for name in owners}:
            if names.count((owner, '/')) != 1:
                errors.append(owner+': expected exactly one command node')
        for topic, (owners, consumer) in ROUTES.items():
            pubs = node.get_publishers_info_by_topic(topic)
            subs = node.get_subscriptions_info_by_topic(topic)
            report['routes'][topic] = {'publishers': sorted(p.node_name for p in pubs),
                                     'subscribers': sorted(p.node_name for p in subs)}
            # Humble behavior plugins each create their own Twist publisher;
            # BackUp and Wait legitimately share one behavior_server identity.
            actual_owners = sorted(set(p.node_name for p in pubs)) if topic == '/nav/cmd_vel_raw' else sorted(p.node_name for p in pubs)
            if actual_owners != owners or any(
                    p.topic_type != 'geometry_msgs/msg/Twist' or p.node_namespace != '/' for p in pubs):
                errors.append(topic+': publisher/units route mismatch')
            if not any(p.node_name == consumer and p.node_namespace == '/' and
                       p.topic_type == 'geometry_msgs/msg/Twist' for p in subs):
                errors.append(topic+': expected consumer missing: '+consumer)
        for topic in ('/cmd_vel', '/cmd_vel_mux/input/teleop'):
            if node.get_publishers_info_by_topic(topic) or node.get_subscriptions_info_by_topic(topic):
                errors.append(topic+': unexpected legacy drive route')
        for topic in ('/nav/cmd_vel_raw', '/nav/cmd_vel'):
            if any(p.node_name in ('drive_controller_node', 'mode_manager_node')
                   for p in node.get_subscriptions_info_by_topic(topic)):
                errors.append(topic+': SI command bypasses motion interpreter')
    report['ok'] = not errors
    report['errors'] = errors
    return report

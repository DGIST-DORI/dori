"""Asynchronous readiness for the Nav2 servers that accept and execute a goal."""
import time
from lifecycle_msgs.srv import GetState


class LifecycleReadiness:
    def __init__(self, node):
        self.clients = {name: node.create_client(GetState, '/'+name+'/get_state')
                        for name in ('amcl', 'bt_navigator', 'controller_server', 'planner_server', 'behavior_server', 'velocity_smoother')}
        self.pending = {}
        self.states = {}

    def poll(self):
        now = time.monotonic()
        for name, client in self.clients.items():
            pending = self.pending.get(name)
            if pending:
                future, started = pending
                if not future.done() and now-started < 2:
                    continue
                self.pending.pop(name)
                if future.done():
                    try:
                        self.states[name] = (future.result().current_state.id == 3, now)
                    except Exception:
                        self.states[name] = (False, now)
                else:
                    client.remove_pending_request(future)
                    future.cancel()
                    self.states[name] = (False, now)
            if client.service_is_ready():
                self.pending[name] = (client.call_async(GetState.Request()), now)
            else:
                self.states[name] = (False, now)

    def problems(self):
        now = time.monotonic()
        waiting = [name for name in self.clients
                   if not self.states.get(name, (False, 0))[0]
                   or now-self.states.get(name, (False, 0))[1] > 4]
        return ['Nav2 시작 대기: '+', '.join(waiting)] if waiting else []

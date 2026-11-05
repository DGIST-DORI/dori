"""Shutdown recovery using isolated processes and real sockets, without ROS/hardware."""

import importlib.util
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("stop_dori", ROOT / "scripts/stop_dori.py")
stop_dori = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stop_dori
SPEC.loader.exec_module(stop_dori)


def process(pid, command, *, ppid=1, cwd=ROOT, env=None, started=1):
    return stop_dori.Process(pid, ppid, started, tuple(command), str(cwd), env or {})


def test_legacy_launch_tree_and_orphans_are_scoped_to_checkout():
    processes = [
        process(10, ["python3", "/opt/ros/humble/bin/ros2", "launch", "dori_bringup", "bringup.launch.py"]),
        process(11, ["/opt/ros/humble/lib/rosapi/rosapi_node"], ppid=10),
        process(12, ["python3", str(ROOT / "ros2_ws/install/dori_dashboard/share/dori_dashboard/scripts/backend_api.py")]),
        process(13, ["python3", "/opt/ros/humble/lib/rosbridge_server/rosbridge_websocket", "--ros-args", "-r", "__ns:=/dori"]),
        process(14, ["python3", "/opt/ros/humble/lib/rosbridge_server/rosbridge_websocket", "--ros-args", "-r", "__ns:=/other"]),
        process(15, ["python3", "/opt/ros/humble/bin/ros2", "launch", "dori_bringup", "bringup.launch.py"], cwd="/tmp/other"),
        process(16, ["bash", "-c", f"python3 {ROOT}/ros2_ws/install/backend_api.py"]),
        process(17, ["python3", "-c", "pass", str(ROOT / "ros2_ws/install/backend_api.py")]),
    ]
    selected = stop_dori.select_processes({p.pid: p for p in processes}, ROOT, own_pid=999)
    assert set(selected) == {10, 11, 12, 13}


def test_marker_finds_detached_children_but_excludes_other_checkouts_and_callers():
    marker = {stop_dori.SESSION_KEY: str(ROOT)}
    processes = [
        process(10, ["sleep", "60"], cwd="/tmp", env=marker),
        process(11, ["sleep", "60"], ppid=10, cwd="/tmp"),
        process(12, ["python3", str(ROOT / "ros2_ws/install/backend_api.py")],
                env={stop_dori.SESSION_KEY: "/tmp/other"}),
        process(20, ["bash"], env=marker),
        process(21, ["python3", str(ROOT / "scripts/stop_dori.py")], ppid=20, env=marker),
    ]
    selected = stop_dori.select_processes({p.pid: p for p in processes}, ROOT, own_pid=21)
    assert set(selected) == {10, 11}


@pytest.mark.parametrize("env", [
    {"DORI_WS": "/tmp/other"},
    {"DORI_ROOT": "/tmp/other"},
    {"AMENT_PREFIX_PATH": f"/tmp/other/ros2_ws/install/dori_bringup:{ROOT}/ros2_ws/install/dori_bringup"},
])
def test_other_workspace_takes_precedence_over_working_directory(env):
    launcher = process(10, ["ros2", "launch", "dori_bringup", "bringup.launch.py"], env=env)
    assert not stop_dori.belongs(launcher, ROOT)


def test_path_containment_respects_parent_directory_components():
    assert not stop_dori.within(str(ROOT / "ros2_ws/install/../../../../other/server"), ROOT)


def test_remembered_children_survive_reparenting_without_matching_reused_pid():
    child = process(10, ["sleep", "60"], cwd="/tmp", started=100)
    reused = process(11, ["sleep", "60"], cwd="/tmp", started=200)
    selected = stop_dori.select_processes({10: child, 11: reused}, ROOT,
                                         remembered={(10, 100), (11, 199)}, own_pid=999)
    assert set(selected) == {10}


def test_pid_reuse_between_discovery_and_signal_is_not_killed(monkeypatch):
    target = process(10, ["sleep"], started=100)
    monkeypatch.setattr(stop_dori.os, "pidfd_open", Mock(return_value=123))
    monkeypatch.setattr(stop_dori.os, "close", Mock())
    monkeypatch.setattr(stop_dori, "read_process", lambda pid: process(pid, ["sleep"], started=101))
    send = Mock()
    monkeypatch.setattr(stop_dori.signal, "pidfd_send_signal", send)
    stop_dori.send_signal(target, signal.SIGKILL)
    send.assert_not_called()
    stop_dori.os.close.assert_called_once_with(123)


@pytest.fixture
def start_process(tmp_path):
    children = []

    def start(script, *, marker=True, args=()):
        env = dict(os.environ)
        for key in (stop_dori.SESSION_KEY, "DORI_WS", "DORI_ROOT", "AMENT_PREFIX_PATH"):
            env.pop(key, None)
        if marker:
            env[stop_dori.SESSION_KEY] = str(tmp_path)
        child = subprocess.Popen([sys.executable, str(script), *args], cwd=tmp_path,
                                 env=env, start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        children.append(child)
        return child

    yield start
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5)


def wait_file(path):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists() and path.read_text():
            return path.read_text()
        time.sleep(.02)
    pytest.fail(f"Process did not become ready: {path}")


def assert_port_free(port):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


def test_graceful_shutdown_releases_port_dry_run_and_repeated_stop(tmp_path, start_process):
    script = tmp_path / "server.py"
    script.write_text('''
import signal, socket, time
from pathlib import Path
sock = socket.socket()
sock.bind(('127.0.0.1', 0))
sock.listen()
def stopped(*args):
    sock.close()
    Path('cleaned').write_text('yes')
    raise SystemExit(0)
signal.signal(signal.SIGINT, stopped)
Path('port').write_text(str(sock.getsockname()[1]))
while True: time.sleep(.05)
''')
    child = start_process(script)
    port = int(wait_file(tmp_path / "port"))
    unrelated_script = tmp_path / "unrelated.py"
    unrelated_script.write_text("import time; time.sleep(60)")
    unrelated = start_process(unrelated_script, marker=False)
    assert stop_dori.stop(tmp_path, dry_run=True) == 0
    assert child.poll() is None
    assert stop_dori.stop(tmp_path, grace=.5) == 0
    assert child.wait(timeout=2) == 0
    assert (tmp_path / "cleaned").read_text() == "yes"
    assert_port_free(port)
    assert stop_dori.stop(tmp_path, grace=.1) == 0
    assert unrelated.poll() is None


def test_launcher_stops_before_child_and_stubborn_orphan_is_killed(tmp_path, start_process):
    child_script = tmp_path / "child.py"
    child_script.write_text('''
import os, signal, socket, time
from pathlib import Path
def interrupted(*args):
    if not Path('launcher-stopped').exists():
        Path('wrong-order').write_text('child signalled before launcher stopped')
signal.signal(signal.SIGINT, interrupted)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
sock = socket.socket()
sock.bind(('127.0.0.1', 0))
sock.listen()
Path('port').write_text(str(sock.getsockname()[1]))
while True: time.sleep(.05)
''')
    launcher_script = tmp_path / "ros2"
    launcher_script.write_text('''
import signal, subprocess, sys, time
from pathlib import Path
def stopped(*args):
    Path('launcher-stopped').write_text('yes')
    raise SystemExit(0)
signal.signal(signal.SIGINT, stopped)
subprocess.Popen([sys.executable, 'child.py'])
while True: time.sleep(.05)
''')
    # No marker: discovery must remember the child when the legacy launcher exits.
    launcher = start_process(launcher_script, marker=False,
                             args=("launch", "dori_bringup", "bringup.launch.py"))
    port = int(wait_file(tmp_path / "port"))
    assert stop_dori.stop(tmp_path, grace=.15) == 0
    assert launcher.wait(timeout=2) == 0
    assert (tmp_path / "launcher-stopped").exists()
    assert not (tmp_path / "wrong-order").exists()
    assert_port_free(port)


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_grace_is_rejected(value):
    with pytest.raises(stop_dori.argparse.ArgumentTypeError):
        stop_dori.positive_seconds(value)

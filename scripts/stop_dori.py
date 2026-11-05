#!/usr/bin/env python3
"""Stop this checkout's DORI sessions, including orphaned server processes (Linux)."""

import argparse
from dataclasses import dataclass
import math
import os
from pathlib import Path
import signal
import time


ROOT = Path(__file__).resolve().parents[1]
SESSION_KEY = "DORI_SESSION_ROOT"


@dataclass(frozen=True)
class Process:
    pid: int
    ppid: int
    started: int
    argv: tuple
    cwd: str
    env: dict

    @property
    def identity(self):
        return self.pid, self.started

    @property
    def command(self):
        """Return executable/script and arguments without matching shell command text."""
        args = self.argv
        if args and Path(args[0]).name.startswith("python"):
            args = args[1:]
            while args and args[0] in ("-s", "-u", "-E", "-B", "-I"):
                args = args[1:]
        return args

    @property
    def launcher(self):
        args = self.command
        return bool(
            len(args) >= 4 and Path(args[0]).name == "ros2"
            and args[1] in ("launch", "run") and args[2].startswith("dori_")
        )

    @property
    def label(self):
        # Never print arbitrary arguments or environment values (may contain keys).
        return Path(self.command[0]).name if self.command else "process"


def read_process(pid, proc_root=Path("/proc")):
    directory = proc_root / str(pid)
    try:
        if directory.stat().st_uid != os.getuid():
            return None
        fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] in ("Z", "X"):
            return None  # Zombies no longer hold sockets or devices.
        argv = tuple(os.fsdecode(arg) for arg in (directory / "cmdline").read_bytes().split(b"\0") if arg)
        if not argv:
            return None
        env = {}
        for item in (directory / "environ").read_bytes().split(b"\0"):
            key, separator, value = item.partition(b"=")
            if separator and key in (b"DORI_SESSION_ROOT", b"DORI_WS", b"DORI_ROOT", b"AMENT_PREFIX_PATH"):
                env[os.fsdecode(key)] = os.fsdecode(value)
        return Process(int(pid), int(fields[1]), int(fields[19]), argv,
                       os.readlink(directory / "cwd"), env)
    except (OSError, ValueError, IndexError):
        return None  # Exited, or belongs to an inaccessible user/session.


def snapshot():
    processes = {}
    for directory in Path("/proc").iterdir():
        if directory.name.isdecimal():
            process = read_process(int(directory.name))
            if process is not None:
                processes[process.pid] = process
    return processes


def within(path, directory):
    return (bool(path) and Path(path).is_absolute()
            and Path(os.path.abspath(path)).is_relative_to(directory))


def belongs(process, root):
    """Prefer inherited session ownership; recognize older, unmarked launches too."""
    marker = process.env.get(SESSION_KEY)
    if marker:
        return marker == str(root)
    args = process.command
    if not args or args[0].startswith("-"):
        return False
    executable = args[0]
    if not Path(executable).is_absolute():
        executable = str(Path(process.cwd) / executable)
    if within(executable, root / "ros2_ws/install"):
        return True
    if (within(executable, root / "ros2_ws/src")
            and Path(executable).name in ("backend_api.py", "bridge_api.py", "web_viewer.py")):
        return True
    if executable in (str(root / "scripts/dori_stack.py"), str(root / "scripts/autonomy.py")):
        return True
    explicit_root = process.env.get("DORI_WS") or process.env.get("DORI_ROOT")
    if explicit_root:
        workspace = explicit_root == str(root)
    else:
        prefixes = [prefix for prefix in process.env.get("AMENT_PREFIX_PATH", "").split(":") if prefix]
        # With multiple sourced overlays, the first matching package wins.
        package_prefixes = [prefix for prefix in prefixes
                            if process.launcher and Path(prefix).name == args[2]]
        if package_prefixes:
            workspace = within(package_prefixes[0], root / "ros2_ws/install")
        else:
            workspace = within(process.cwd, root) or any(
                within(prefix, root / "ros2_ws/install") for prefix in prefixes)
    if process.launcher:
        return workspace
    # Legacy rosbridge/rosapi run outside this checkout; require both workspace
    # evidence and the dashboard's ROS namespace, not just a process name/port.
    return bool(workspace and Path(executable).name in ("rosbridge_websocket", "rosapi_node")
                and "--ros-args" in args and "__ns:=/dori" in args)


def select_processes(processes, root, remembered=(), own_pid=None):
    excluded = set()
    pid = os.getpid() if own_pid is None else own_pid
    while pid and pid not in excluded:
        excluded.add(pid)
        process = processes.get(pid)
        pid = process.ppid if process else 0
    selected = {
        p.pid: p for p in processes.values()
        if p.pid not in excluded and (p.identity in remembered or belongs(p, root))
    }
    # Discover parents before signalling: respawning launchers must stop first.
    for process in list(selected.values()):
        parent = processes.get(process.ppid)
        if (parent and parent.launcher and parent.pid not in excluded
                and parent.env.get(SESSION_KEY, str(root)) == str(root)):
            selected[parent.pid] = parent
    while True:
        children = {p.pid: p for p in processes.values()
                    if p.pid not in selected and p.pid not in excluded and p.ppid in selected}
        if not children:
            return selected
        selected.update(children)


def send_signal(process, signum):
    """Pin the process before checking its birth time, avoiding PID reuse races."""
    try:
        descriptor = os.pidfd_open(process.pid)
    except ProcessLookupError:
        return
    try:
        current = read_process(process.pid)
        if current is not None and current.identity == process.identity:
            signal.pidfd_send_signal(descriptor, signum)
    except ProcessLookupError:
        pass
    finally:
        os.close(descriptor)


def stop(root=ROOT, grace=10.0, dry_run=False):
    remembered = set()

    def remaining():
        selected = select_processes(snapshot(), root, remembered)
        remembered.update(p.identity for p in selected.values())
        return selected

    def wait(timeout):
        deadline = time.monotonic() + timeout
        while True:
            selected = remaining()
            if not selected or time.monotonic() >= deadline:
                return selected
            time.sleep(min(.1, max(0, deadline - time.monotonic())))

    def notify(processes, signum):
        for process in processes.values():
            print(f"{signal.Signals(signum).name}: PID {process.pid} ({process.label})", flush=True)
            send_signal(process, signum)

    selected = remaining()
    if not selected:
        print("실행 중인 이 작업공간의 DORI 프로세스가 없습니다.")
        return 0
    print(f"DORI 종료 대상: {root} (현재 사용자, {len(selected)}개 프로세스)", flush=True)
    for process in sorted(selected.values(), key=lambda p: p.pid):
        print(f"  PID {process.pid}, parent {process.ppid}: {process.label}", flush=True)
    if dry_run:
        print("미리보기: 종료 신호를 보내지 않았습니다.")
        return 0

    # Launch gets the first chance to run its shutdown handlers and disable respawn.
    parents = {pid: p for pid, p in selected.items() if p.ppid not in selected}
    notify(parents, signal.SIGINT)
    selected = wait(grace)
    for signum, timeout in ((signal.SIGINT, grace), (signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
        if not selected:
            break
        notify(selected, signum)
        selected = wait(timeout)
    if selected:
        print("종료되지 않은 PID: " + ", ".join(str(pid) for pid in sorted(selected)))
        return 1
    print("DORI 프로세스 종료를 확인했습니다.")
    return 0


def positive_seconds(value):
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("양의 유한한 초 단위를 지정하세요.")
    return seconds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="종료 대상만 표시")
    parser.add_argument("--grace", type=positive_seconds, default=10.0,
                        help="각 SIGINT 단계에서 정상 종료를 기다릴 초 (기본: 10)")
    args = parser.parse_args()
    # Repeated Ctrl+C must not interrupt cleanup halfway through.
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, signal.SIG_IGN)
    try:
        return stop(grace=args.grace, dry_run=args.dry_run)
    except OSError as exc:
        print(f"DORI 종료 실패: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

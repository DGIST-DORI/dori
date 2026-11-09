"""Exercise CAN service ownership and teardown without root or a CAN device."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "ros2_ws/src/dori_hardware/scripts"
spec = importlib.util.spec_from_file_location("can_service", SCRIPTS / "can_service.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)


@pytest.fixture
def config():
    return dict(managed_by="dori-can", device="/dev/serial/by-id/usb-CANable2_TEST-if00",
                interface="can1", vendor_id="16d0", product_id="117e", serial="TEST")


@pytest.fixture
def installer(monkeypatch):
    monkeypatch.setitem(sys.modules, "can_service", service)
    spec = importlib.util.spec_from_file_location("can_installer_under_test", SCRIPTS / "install_can_service.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runtime(tmp_path, monkeypatch, config):
    net = tmp_path / "net"
    net.mkdir()
    monkeypatch.setattr(service, "NET_ROOT", net)
    properties = Mock(return_value=dict(ID_VENDOR_ID="16d0", ID_MODEL_ID="117e", ID_SERIAL_SHORT="TEST"))
    monkeypatch.setattr(service, "device_properties", properties)
    users = Mock(return_value=[])
    monkeypatch.setattr(service, "device_users", users)
    original_stat = Path.stat
    monkeypatch.setattr(Path, "stat", lambda self, *a, **kw:
                        original_stat(Path("/dev/null")) if str(self) == config["device"] else original_stat(self, *a, **kw))
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if command[0].endswith("/ip"):
            (net / "can1/flags").write_text("0x41")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(service.subprocess, "run", run)
    child = Mock(returncode=None)
    child.poll.return_value = None
    def terminate():
        child.poll.return_value = 143
        for file in (net / "can1").glob("*"):
            file.unlink()
        if (net / "can1").exists():
            (net / "can1").rmdir()
    child.terminate.side_effect = terminate
    def popen(command):
        commands.append(command)
        child.poll.return_value = None
        (net / "can1").mkdir()
        (net / "can1/type").write_text("280")
        (net / "can1/flags").write_text("0x40")
        return child
    spawn = Mock(side_effect=popen)
    monkeypatch.setattr(service.subprocess, "Popen", spawn)
    notifications = []
    monkeypatch.setattr(service, "notify", notifications.append)
    stopping = Mock()
    stopping.is_set.return_value = False
    stopping.wait.return_value = True
    return SimpleNamespace(net=net, properties=properties, users=users, commands=commands,
                           child=child, spawn=spawn, notifications=notifications, stopping=stopping)


def test_can_ready_only_after_interface_up_and_child_cleaned_up(config, runtime):
    service.supervise(config, runtime.stopping)
    assert runtime.commands == [
        ["/usr/sbin/modprobe", "slcan"],
        ["/usr/bin/slcand", "-F", "-o", "-c", "-s8", "-t", "hw", "-S", "3000000", config["device"], "can1"],
        ["/usr/sbin/ip", "link", "set", "dev", "can1", "up"],
    ]
    assert runtime.notifications == ["READY=1\nSTATUS=can1 UP; CANable TEST"]
    runtime.child.terminate.assert_called_once()
    assert not (runtime.net / "can1").exists()


def test_reconnect_starts_a_new_owned_child(config, runtime):
    for _ in range(2):
        service.supervise(config, runtime.stopping)
    assert runtime.spawn.call_count == 2
    assert runtime.child.terminate.call_count == 2


@pytest.mark.parametrize("conflict", ["interface", "serial_owner", "wrong_device"])
def test_never_takes_over_existing_interface_or_device(config, runtime, conflict):
    if conflict == "interface":
        (runtime.net / "can1").mkdir()
    elif conflict == "serial_owner":
        runtime.users.return_value = [1234]
    else:
        runtime.properties.return_value["ID_SERIAL_SHORT"] = "ANOTHER"
    with pytest.raises(service.ConfigurationError):
        service.supervise(config, runtime.stopping)
    assert not runtime.commands
    runtime.spawn.assert_not_called()
    runtime.child.terminate.assert_not_called()


def test_child_exit_before_creation_is_a_clear_failure(config, runtime, monkeypatch):
    runtime.spawn.side_effect = None
    runtime.spawn.return_value = runtime.child
    runtime.child.poll.return_value = 1
    runtime.child.returncode = 1
    with pytest.raises(RuntimeError, match="slcand exited before can1"):
        service.supervise(config, runtime.stopping)
    assert not runtime.notifications
    assert not any(cmd[0].endswith("/ip") for cmd in runtime.commands)


def test_interface_up_failure_reaps_child(config, runtime, monkeypatch):
    monkeypatch.setattr(service, "interface_up", lambda *_: False)
    with pytest.raises(RuntimeError, match="did not become UP"):
        service.supervise(config, runtime.stopping)
    runtime.child.terminate.assert_called_once()
    assert not runtime.notifications


def test_startup_timeout_reaps_child(config, runtime, monkeypatch):
    runtime.spawn.side_effect = None
    runtime.spawn.return_value = runtime.child
    monkeypatch.setattr(service.time, "monotonic", Mock(side_effect=[0, 11]))
    with pytest.raises(RuntimeError, match="Timed out"):
        service.supervise(config, runtime.stopping)
    runtime.child.terminate.assert_called_once()


def test_shutdown_before_ready_never_raises_interface(config, runtime):
    runtime.stopping.is_set.side_effect = [False, True]
    service.supervise(config, runtime.stopping)
    assert not runtime.notifications
    assert not any(cmd[0].endswith("/ip") for cmd in runtime.commands)
    runtime.child.terminate.assert_called_once()


def test_link_loss_reaps_child_for_systemd_restart(config, runtime, monkeypatch):
    runtime.stopping.wait.return_value = False
    monkeypatch.setattr(service, "interface_up", Mock(side_effect=[True, False]))
    with pytest.raises(RuntimeError, match="Lost can1"):
        service.supervise(config, runtime.stopping)
    runtime.child.terminate.assert_called_once()


def test_unresponsive_child_is_killed_and_reaped(config, runtime):
    runtime.child.wait.side_effect = [subprocess.TimeoutExpired("slcand", 3), -9]
    service.supervise(config, runtime.stopping)
    runtime.child.kill.assert_called_once()
    assert runtime.child.wait.call_count == 2


def test_device_users_checks_open_file_descriptors_not_just_program_names(tmp_path):
    # Synthetic /proc entries alias a harmless character device; no serial open.
    for pid in (123, 456):
        directory = tmp_path / str(pid) / "fd"
        directory.mkdir(parents=True)
        (directory / "3").symlink_to("/dev/null" if pid == 123 else "/dev/zero")
    assert service.device_users("/dev/null", proc_root=tmp_path) == [123]


def test_notify_uses_systemd_socket(tmp_path, monkeypatch):
    path = str(tmp_path / "notify")
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as receiver:
        receiver.bind(path)
        receiver.settimeout(1)
        monkeypatch.setenv("NOTIFY_SOCKET", path)
        service.notify("READY=1\nSTATUS=can1 UP")
        assert receiver.recv(1024) == b"READY=1\nSTATUS=can1 UP"


@pytest.mark.parametrize("key,value", [("interface", "can1; reboot"), ("serial", 'bad"serial'),
                                      ("vendor_id", "*"), ("device", "/dev/ttyACM0"), ("serial", 123)])
def test_config_cannot_select_arbitrary_devices_or_inject_rules(config, key, value):
    config[key] = value
    with pytest.raises(service.ConfigurationError):
        service.validate_config(config)


def test_installer_renders_only_selected_identity_and_root_owned_runtime(installer, config, tmp_path):
    contents = installer.files(config)
    installer.write_files(contents, tmp_path)
    rule = (tmp_path / "etc/udev/rules.d/99-dori-can.rules").read_text()
    assert 'ENV{ID_SERIAL_SHORT}=="TEST"' in rule
    assert 'ENV{SYSTEMD_WANTS}+="dori-can.service"' in rule
    assert 'RUN+=' not in rule
    assert 'ttyACM0' not in rule
    unit = (tmp_path / "etc/systemd/system/dori-can.service").read_text()
    assert 'BindsTo=dev-dori_canable.device' in unit
    assert 'Type=notify' in unit
    assert 'RestartPreventExitStatus=78' in unit
    assert 'WantedBy=multi-user.target' not in unit
    assert '/usr/local/libexec/dori-can' in unit
    assert str(ROOT) not in unit
    assert json.loads((tmp_path / "etc/dori/can.json").read_text()) == config
    assert os.access(tmp_path / "usr/local/libexec/dori-can", os.X_OK)


def test_installer_keeps_stable_device_path(installer, config, monkeypatch):
    monkeypatch.setattr(installer, "device_properties", lambda *_:
                        dict(ID_VENDOR_ID="16d0", ID_MODEL_ID="117e", ID_SERIAL_SHORT="TEST"))
    assert installer.configuration(config["device"], "can1") == config


def test_system_install_requires_root_before_any_changes(installer, config, monkeypatch):
    monkeypatch.setattr(installer.os, "geteuid", lambda: 1000)
    write = Mock()
    monkeypatch.setattr(installer, "write_files", write)
    with pytest.raises(RuntimeError, match="requires sudo"):
        installer.install(installer.files(config), config)
    write.assert_not_called()


@pytest.fixture
def installation(installer, monkeypatch, tmp_path):
    monkeypatch.setattr(installer, "SYSTEM_ROOT", tmp_path)
    monkeypatch.setattr(installer.os, "geteuid", lambda: 0)
    monkeypatch.setattr(installer.shutil, "which", lambda name: "/usr/bin/" + name)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(installer.subprocess, "run", run)
    return tmp_path, calls


def test_install_and_reinstall_never_restart_working_service(installer, config, installation):
    root, calls = installation
    for _ in range(2):
        installer.install(installer.files(config), config)
    assert (root / "etc/dori/can.json").is_file()
    assert calls.count(["/usr/bin/systemctl", "start", "dori-can.service"]) == 2
    assert all("restart" not in command and "enable" not in command for command in calls)
    trigger = next(command for command in calls if "trigger" in command)
    assert trigger[-1].startswith("--sysname-match=")


def test_install_refuses_to_retarget_active_service(installer, config, installation):
    root, calls = installation
    original = installer.files(config)
    installer.write_files(original, root)
    config["serial"] = "CHANGED"
    with pytest.raises(RuntimeError, match="Stop the robot"):
        installer.install(installer.files(config), config)
    assert (root / "etc/dori/can.json").read_text() == original["etc/dori/can.json"]
    assert not any("start" in command or "daemon-reload" in command for command in calls)


def test_install_refuses_unmanaged_system_files(installer, config, installation):
    root, calls = installation
    target = root / "etc/systemd/system/dori-can.service"
    target.parent.mkdir(parents=True)
    target.write_text("Existing service owned by someone else")
    with pytest.raises(RuntimeError, match="unmanaged file"):
        installer.install(installer.files(config), config)
    assert target.read_text() == "Existing service owned by someone else"
    assert not calls

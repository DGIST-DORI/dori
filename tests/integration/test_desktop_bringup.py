"""Start the desktop visitor voice core in isolation and check the pairing barrier."""
import os
from pathlib import Path
import signal
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def test_desktop_bringup_passes_pairing_readiness(tmp_path):
    env = dict(os.environ, ROS_DOMAIN_ID="197", ROS_LOCALHOST_ONLY="1",
               ROS_LOG_DIR=str(tmp_path / "ros-logs"))
    for name in ("DORI_VISITOR_STT", "FASTRTPS_DEFAULT_PROFILES_FILE",
                 "FASTDDS_DEFAULT_PROFILES_FILE", "CYCLONEDDS_URI"):
        env.pop(name, None)
    log_path = tmp_path / "bringup.log"
    # HTTP/rosbridge listeners are covered by launch contracts; this test only
    # runs voice/BT services, on a domain separate from the physical robot.
    with log_path.open("w") as log:
        process = subprocess.Popen(
            ["ros2", "launch", "dori_bringup", "bringup.launch.py",
             "dori_mode:=desktop", "enable_dashboard:=false"],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            probe = subprocess.run([sys.executable, "-c", '''
import asyncio
import threading
import rclpy
from rclpy.executors import ExternalShutdownException
from dori_dashboard import bridge_api as bridge

async def main():
    rclpy.init(args=['--ros-args', '-r', '__ns:=/dori'])
    node = bridge.BridgeNode()
    def spin():
        try:
            rclpy.spin(node)
        except ExternalShutdownException:
            pass
    worker = threading.Thread(target=spin, daemon=True)
    worker.start()
    try:
        clients = (node.cli_visitor_ready, node.cli_llm_reset,
                   node.cli_tts_reset, node.cli_bt_clear)
        deadline = asyncio.get_running_loop().time() + 20
        while not (all(c.service_is_ready() for c in clients)
                   and node.voice.llm.server_is_ready()
                   and node.voice.tts.server_is_ready()):
            assert asyncio.get_running_loop().time() < deadline, 'Voice services did not start'
            await asyncio.sleep(.1)
        assert node.voice.provider == 'azure'
        assert not node.cli_stt_reset.service_is_ready(), 'Local microphone STT unexpectedly started'
        assert await node.prepare_visitor(), 'Desktop bringup would reject app pairing with 503'
        print('Desktop visitor mode, LLM, TTS and cleanup barriers are ready')
    finally:
        rclpy.shutdown()
        worker.join(timeout=3)
        node.destroy_node()

asyncio.run(main())
'''], env={**env, "DORI_VISITOR_STT": "azure"}, capture_output=True,
                text=True, timeout=35)
            assert process.poll() is None, log_path.read_text()
            assert probe.returncode == 0, probe.stdout + probe.stderr + log_path.read_text()
        finally:
            process.send_signal(signal.SIGINT)
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        assert process.returncode == 0, log_path.read_text()

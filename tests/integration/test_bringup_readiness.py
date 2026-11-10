"""The actual startup monitor fails with missing sensors, without launching hardware."""
import os
import subprocess


def test_monitor_reports_required_failures_and_exits_nonzero(tmp_path):
    env = dict(os.environ, ROS_DOMAIN_ID="198", ROS_LOCALHOST_ONLY="1",
               ROS_LOG_DIR=str(tmp_path / "ros-logs"))
    result = subprocess.run([
        "ros2", "run", "dori_bringup", "readiness_monitor", "--ros-args",
        "-r", "__ns:=/readiness_test", "-p", "startup_timeout:=1.0",
        "-p", "enable_hri:=false", "-p", "enable_dashboard:=false",
    ], env=env, capture_output=True, text=True, timeout=20)
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "Robot startup failed:" in output
    assert "front_color data missing/stale" in output
    assert "controllers:" in output
    assert "waiting_initial_pose" in output
    assert "activation timed out" not in output

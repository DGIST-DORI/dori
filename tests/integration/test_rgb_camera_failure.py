"""Exercise native driver startup failures without opening a physical device."""
import os
from pathlib import Path
import subprocess

import pytest
from ament_index_python.packages import get_package_prefix


@pytest.mark.parametrize('failure', ['missing_device', 'bad_calibration', 'invalid_fps'])
def test_rgb_camera_fails_nonzero_without_fake_frames(tmp_path, failure):
    executable = Path(get_package_prefix('dori_perception_camera')) / 'lib/dori_perception_camera/rgb_camera_node'
    args = [str(executable), '--ros-args', '-p', f'device:={tmp_path / "missing-device"}']
    expected = 'Cannot open USB/V4L2 camera'
    if failure == 'bad_calibration':
        calibration = tmp_path / 'invalid.yaml'
        calibration.write_text('image_width: invalid\n')
        args += ['-p', f'calibration_file:={calibration}']
        expected = 'conversion'
    if failure == 'invalid_fps':
        args += ['-p', 'fps:=0']
        expected = 'Invalid camera'
    result = subprocess.run(args, capture_output=True, text=True, timeout=15,
                            env={**os.environ, 'ROS_DOMAIN_ID': '198', 'ROS_LOCALHOST_ONLY': '1',
                                 'ROS_LOG_DIR': str(tmp_path / 'ros-logs')})
    assert result.returncode == 1, result.stdout + result.stderr
    assert expected in result.stderr

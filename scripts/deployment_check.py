#!/usr/bin/env python3
"""Offline release inspection; does not create a ROS node or enable hardware."""
import argparse
import importlib
import json
import os
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ros2_ws/src/dori_navigation/scripts'))
from navigation_contract import validate_map


def check(map_file, voice=False):
    from ament_index_python.packages import get_package_share_directory, get_package_prefix
    errors = []
    report = {'python':platform.python_version(), 'ros_distro':os.getenv('ROS_DISTRO'),
              'repository':str(ROOT), 'hardware_actuated':False}
    if sys.version_info[:2] != (3,10):
        errors.append('ROS Humble requires the Ubuntu Python 3.10 interpreter')
    if os.getenv('ROS_DISTRO') != 'humble':
        errors.append('Source scripts/env.sh (ROS Humble)')
    try:
        report['map'] = validate_map(map_file)
    except (OSError,ValueError) as exc:
        errors.append(str(exc))
    executables = [('dori_bt','dori_tree_executor'), ('dori_navigation','nav2_adapter'),
        ('dori_navigation','named_goal_adapter'), ('dori_navigation','web_viewer.py'),
        ('dori_hri','tts_node'), ('dori_llm','llm_node'), ('dori_drive','drive_controller_node')]
    for package, executable in executables:
        try:
            prefix = Path(get_package_prefix(package))
            if not prefix.is_relative_to(ROOT/'ros2_ws/install'):
                errors.append(f'{package} comes from another overlay: {prefix}')
            if not (prefix/'lib'/package/executable).is_file():
                errors.append(f'Executable missing: {package}/{executable}')
        except LookupError:
            errors.append('Package missing: '+package)
    for module in ('rclpy','dori_msgs.action','dori_msgs.msg','fastapi','uvicorn','httpx','PIL','scipy','serial','gtts'):
        try:
            importlib.import_module(module)
        except Exception as exc:
            errors.append(f'Python dependency failed: {module}: {exc}')
    for package, executable in {'rosbridge_server':'rosbridge_websocket', 'rosapi':'rosapi_node',
                                'nav2_bt_navigator':'bt_navigator', 'sllidar_ros2':'sllidar_node'}.items():
        try:
            if not (Path(get_package_prefix(package))/'lib'/package/executable).is_file():
                errors.append(f'Executable missing: {package}/{executable}')
        except LookupError:
            errors.append('Runtime package missing: '+package+' (run scripts/install_dependencies.sh)')
    try:
        web = Path(get_package_share_directory('dori_dashboard'))/'web'
        if not (web/'index.html').is_file():
            errors.append('Build web/dist before building dori_dashboard')
    except LookupError:
        errors.append('dori_dashboard is not installed')
    if voice:
        for module in ('openwakeword','faster_whisper','sounddevice'):
            try:
                importlib.import_module(module)
            except Exception as exc:
                errors.append(f'Voice dependency failed: {module}: {exc}')
        if not (ROOT/'.state/voice/whisper-small/model.bin').is_file():
            errors.append('Voice assets missing: run scripts/prepare_voice.sh')
    report['errors'] = errors
    report['ok'] = not errors
    return report


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--map',default=str(ROOT/'maps/live_navigation_20261023_1938.yaml'))
    parser.add_argument('--voice',action='store_true')
    args=parser.parse_args()
    report=check(args.map,args.voice)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env bash
set -euo pipefail

pkill -INT -f '/jetson_real_nav_smoke/launch/jetson_real_nav.launch.py' 2>/dev/null || true
pkill -INT -f '/jetson_real_nav_smoke/scripts/no_robot_workload.py' 2>/dev/null || true
pkill -INT -f '/jetson_real_nav_smoke/scripts/restamp_scan.py' 2>/dev/null || true
pkill -INT -f '/jetson_real_nav_smoke/scripts/named_goal_bridge.py' 2>/dev/null || true
# The driver is launched from its own install prefix, so its command line does
# not contain this project's path. Stop a possible orphan left by an aborted
# smoke launch before the next run starts.
pkill -INT -f 'sllidar_node' 2>/dev/null || true
sleep 2
echo "Stopped matching jetson_real_nav_smoke processes."

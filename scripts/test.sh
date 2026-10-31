#!/usr/bin/env bash
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$DORI_WS"
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-96}" ROS_LOCALHOST_ONLY=1 OPENBLAS_NUM_THREADS=1
python3 -m pytest tests/contracts tests/control_and_nav tests/integration ros2_ws/src/dori_navigation/test/test_nav2_adapter_contract.py "$@"
ctest --test-dir ros2_ws/build/cubemars_hardware --output-on-failure
ctest --test-dir ros2_ws/build/dori_control --output-on-failure

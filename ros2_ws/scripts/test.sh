#!/usr/bin/env bash
# Unit and hardware-free fault tests. Integration scenarios are opt-in.
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$ROBOT_WS"
export ROS_DOMAIN_ID=96 ROS_LOCALHOST_ONLY=1 OPENBLAS_NUM_THREADS=1
python3 -m unittest discover -s tests -p 'test_*.py'
ctest --test-dir build/cubemars_hardware --output-on-failure
ctest --test-dir build/robot_drive --output-on-failure

#!/usr/bin/env bash
# Software plant only. Isolated ROS domains; never launches physical drivers.
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$ROBOT_WS"
export ROS_LOCALHOST_ONLY=1 OPENBLAS_NUM_THREADS=1
mkdir -p log/validation
scripts/test.sh | tee log/validation/tests.log
(cd web && npm run lint && npm run build && node --test src/panels/perception/logUtils.test.js) > log/validation/web-build.log 2>&1
ROS_DOMAIN_ID=99 python3 tests/control_and_nav/integration_drive_chain.py > log/validation/drive-chain-run.log 2>&1
export ROS_DOMAIN_ID=95
run_nav() {
    local label="$1"; shift
    python3 tests/control_and_nav/integration_lidar_web.py "$@" > "log/validation/$label.log" 2>&1
    cp log/lidar_web_navigation_results.json "log/validation/$label.json"
    echo "$label PASS"
}
run_nav web-goal
run_nav relative-1m --relative-test --offline-intent --goal-x 1
run_nav hri-nav2 --hri-test --calibrated-response
run_nav retry --retry-test
run_nav reverse-recovery --reverse-recovery
run_nav blocked-rear --reverse-recovery --blocked-rear
run_nav heading-test --heading-test
run_nav motor-dynamics --motor-dynamics
python3 tests/control_and_nav/integration_lidar_web.py --auto-alignment-test > log/validation/auto-alignment-test.log 2>&1
cp log/auto_alignment_validation.json log/validation/auto-alignment-test.json
ROS_DOMAIN_ID=94 python3 -m tests.control_and_nav.integration_mapping > log/validation/mapping.log 2>&1
cp log/mapping_validation.json log/validation/mapping.json
if [[ "${1:-}" == --browser ]]; then
    ROS_DOMAIN_ID=97 python3 tests/integration/browser_dashboard.py > log/validation/dashboard-browser.log 2>&1
    python3 tests/control_and_nav/browser_voice_retry.py > log/validation/browser-retry.log 2>&1
    cp log/browser_voice_retry_validation.json log/validation/browser-retry.json
fi
echo 'Validation complete: log/validation'

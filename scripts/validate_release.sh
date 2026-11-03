#!/usr/bin/env bash
# Software plant only. Isolated ROS domains; never launches physical drivers.
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$DORI_WS"
export ROS_LOCALHOST_ONLY=1 OPENBLAS_NUM_THREADS=1
mkdir -p log/validation
scripts/test.sh | tee log/validation/tests.log
(cd web && npm run lint && npm test && npm run build) > log/validation/web-build.log 2>&1
ROS_DOMAIN_ID=94 python3 -m tests.control_and_nav.integration_mapping > log/validation/mapping.log 2>&1
cp log/mapping_validation.json log/validation/mapping.json
echo 'Validation complete: log/validation'

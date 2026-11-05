#!/usr/bin/env bash
# Recovery must work even when the ROS overlay or Python venv is broken.
set -eo pipefail
exec /usr/bin/python3 "$(dirname "${BASH_SOURCE[0]}")/stop_dori.py" "$@"

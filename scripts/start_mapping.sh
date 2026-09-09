#!/usr/bin/env bash
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
exec /usr/bin/python3 "$ROBOT_WS/scripts/robot_stack.py" mapping "$@"

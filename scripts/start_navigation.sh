#!/usr/bin/env bash
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
exec /usr/bin/python3 "$DORI_WS/scripts/dori_stack.py" navigation "$@"

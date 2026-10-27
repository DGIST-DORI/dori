#!/usr/bin/env bash
set -eo pipefail
exec "$(dirname "${BASH_SOURCE[0]}")/start_robot.sh" "$@"

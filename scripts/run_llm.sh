#!/usr/bin/env bash
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 /path/to/named_points.csv [ROS arguments]" >&2; exit 2
fi
points_file="$1"
shift
[[ -f "$points_file" ]] || { echo 'Named points CSV not found.' >&2; exit 2; }
exec /usr/bin/python3 "$ROBOT_WS/install/robot_navigation/share/robot_navigation/scripts/text_llm_named_goal.py" \
    --ros-args -p "points_file:=$points_file" "$@"

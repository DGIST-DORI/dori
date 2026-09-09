#!/usr/bin/env bash
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
[[ $# == 2 ]] || { echo '사용법: edit_points.sh 지도.yaml 목적지.csv' >&2; exit 2; }
exec /usr/bin/python3 "$ROBOT_WS/install/robot_navigation/share/robot_navigation/scripts/named_points_editor.py" --map_yaml "$1" --points_csv "$2"

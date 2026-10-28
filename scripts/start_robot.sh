#!/usr/bin/env bash
# Full HRI + calibrated real robot + dashboard. Run as the device-owning user.
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$DORI_WS"
map_file="$DORI_WS/maps/live_navigation_20261023_1938.yaml"
goals_file="$DORI_WS/maps/web_goals.json"
launch_args=()
check_only=false
check_args=(--voice)
while (($#)); do
    case "$1" in
        --map) (($# >= 2)) || { echo "--map requires a path" >&2; exit 2; }; map_file="$2"; shift 2 ;;
        --goals) (($# >= 2)) || { echo "--goals requires a path" >&2; exit 2; }; goals_file="$2"; shift 2 ;;
        --check) check_only=true; shift ;;
        --text-only) launch_args+=(enable_stt:=false tts_playback_mode:=publish_only); check_args=(); shift ;;
        --help) echo 'start_robot.sh [--map MAP.yaml] [--goals GOALS.json] [--text-only] [--check] [ROS launch argument:=value ...]'; exit 0 ;;
        enable_hri:=false|enable_stt:=false) check_args=(); launch_args+=("$1"); shift ;;
        *:=*) launch_args+=("$1"); shift ;;
        *) echo "Unknown argument: $1 (use --help)" >&2; exit 2 ;;
    esac
done
# Validate files before preparing actuators.
python3 "$DORI_WS/scripts/deployment_check.py" --map "$map_file" "${check_args[@]}"
if [[ "$check_only" == true ]]; then
    exec "$DORI_WS/scripts/run_dori_control.sh" --no-joystick --check
fi
if [[ ! -e "$goals_file" ]]; then
    if [[ "$goals_file" != "$DORI_WS/maps/web_goals.json" ]]; then
        echo "Missing goals file: $goals_file" >&2; exit 1
    fi
    cp "$DORI_WS/maps/web_goals.example.json" "$goals_file"
fi
"$DORI_WS/scripts/run_dori_control.sh" --no-joystick --prepare-only
exec ros2 launch dori_bringup real_robot.launch.py map:="$map_file" named_goals_file:="$goals_file" whisper_model:="$DORI_WS/.state/voice/whisper-small" "${launch_args[@]}"

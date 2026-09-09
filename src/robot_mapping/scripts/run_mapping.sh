#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="${XDG_RUNTIME_DIR:-/tmp}/lidar_only_slam_mapping.lock"

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "Lidar-only mapping is already running." >&2
    echo "Stop the existing run with Ctrl+C before starting another one." >&2
    exit 2
fi

set +u
source /opt/ros/humble/setup.bash
set -u

source_sllidar_overlay() {
    local setup_file
    for setup_file in \
        "${SLLIDAR_SETUP:-}" \
        "$ROOT_DIR/../sllidar_ws/install/setup.bash" \
        "$ROOT_DIR/.deps/sllidar_ws/install/setup.bash"
    do
        if [[ -n "$setup_file" && -f "$setup_file" ]]; then
            # shellcheck disable=SC1090
            set +u
            source "$setup_file"
            set -u
            return 0
        fi
    done
    return 1
}

detect_serial_port() {
    local candidate
    for candidate in \
        /dev/slamtec_c1 \
        /dev/serial/by-id/*CP210* \
        /dev/serial/by-id/*Slamtec* \
        /dev/rplidar \
        /dev/ttyUSB0
    do
        if [[ -e "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

ensure_serial_access() {
    local serial_port="$1"

    if [[ -r "$serial_port" && -w "$serial_port" ]]; then
        return 0
    fi

    echo "LiDAR serial access is required for $serial_port." >&2
    if command -v pkexec >/dev/null 2>&1 \
        && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        pkexec chmod a+rw "$serial_port"
    elif sudo -n true >/dev/null 2>&1; then
        sudo chmod a+rw "$serial_port"
    elif [[ -t 0 ]]; then
        sudo chmod a+rw "$serial_port"
    else
        echo "Run: sudo chmod a+rw $serial_port" >&2
        return 1
    fi

    [[ -r "$serial_port" && -w "$serial_port" ]]
}

topic_has_live_data() {
    local topic="$1"
    timeout 3 ros2 topic echo "$topic" --once \
        --qos-reliability best_effort >/dev/null 2>&1
}

stop_stale_sllidar_nodes() {
    local pid
    local -a stale_pids=()

    while IFS= read -r pid; do
        [[ -n "$pid" ]] || continue
        stale_pids+=("$pid")
    done < <(
        pgrep -u "$(id -u)" -f '/sllidar_node([[:space:]]|$)' || true
    )

    if [[ "${#stale_pids[@]}" -eq 0 ]]; then
        return 0
    fi

    echo "Stopping stale SLLIDAR process(es): ${stale_pids[*]}" >&2
    kill -INT "${stale_pids[@]}" 2>/dev/null || true

    for _ in {1..20}; do
        local any_alive="false"
        for pid in "${stale_pids[@]}"; do
            if kill -0 "$pid" 2>/dev/null; then
                any_alive="true"
                break
            fi
        done
        [[ "$any_alive" == "false" ]] && return 0
        sleep 0.1
    done
}

declare -a launch_args=("$@")
scan_topic="/scan"
serial_port=""
start_lidar_driver=""

for arg in "$@"; do
    case "$arg" in
        scan_topic:=*) scan_topic="${arg#scan_topic:=}" ;;
        serial_port:=*) serial_port="${arg#serial_port:=}" ;;
        start_lidar_driver:=*) start_lidar_driver="${arg#start_lidar_driver:=}" ;;
    esac
done

if [[ -z "$start_lidar_driver" ]]; then
    if topic_has_live_data "$scan_topic"; then
        start_lidar_driver="false"
        echo "Reusing live LaserScan data on $scan_topic."
    else
        start_lidar_driver="true"
        stop_stale_sllidar_nodes
    fi
    launch_args+=("start_lidar_driver:=$start_lidar_driver")
fi

if [[ "$start_lidar_driver" == "true" ]]; then
    if [[ -z "$serial_port" || "$serial_port" == "auto" ]]; then
        if ! serial_port="$(detect_serial_port)"; then
            echo "No SLAMTEC serial device found." >&2
            echo "Checked CP210x by-id paths, /dev/rplidar, and /dev/ttyUSB0." >&2
            exit 1
        fi
        launch_args+=("serial_port:=$serial_port")
    fi

    ensure_serial_access "$serial_port"

    if ! ros2 pkg prefix sllidar_ros2 >/dev/null 2>&1; then
        source_sllidar_overlay || true
    fi
    if ! ros2 pkg prefix sllidar_ros2 >/dev/null 2>&1; then
        "$ROOT_DIR/scripts/bootstrap_sllidar.sh"
        # shellcheck disable=SC1091
        set +u
        source "${SLLIDAR_DEPS_WS:-$ROOT_DIR/.deps/sllidar_ws}/install/setup.bash"
        set -u
    fi

    echo "Starting SLAMTEC C1 on $serial_port (460800 baud, Standard mode)."
fi

exec ros2 launch "$ROOT_DIR/launch/lidar_only_cartographer.launch.py" "${launch_args[@]}"

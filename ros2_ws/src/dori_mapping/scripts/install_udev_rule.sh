#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_RULE="$ROOT_DIR/config/99-slamtec-c1.rules"
TARGET_RULE="/etc/udev/rules.d/99-slamtec-c1.rules"

run_as_root() {
    if [[ "$(id -u)" -eq 0 ]]; then
        "$@"
    elif command -v pkexec >/dev/null 2>&1 \
        && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        pkexec "$@"
    else
        sudo "$@"
    fi
}

run_as_root install -m 0644 "$SOURCE_RULE" "$TARGET_RULE"
run_as_root udevadm control --reload-rules

if compgen -G "/dev/ttyUSB*" >/dev/null; then
    run_as_root udevadm trigger --subsystem-match=tty
fi

echo "Installed $TARGET_RULE"
echo "The SLAMTEC adapter will also appear as /dev/slamtec_c1 after reconnect."

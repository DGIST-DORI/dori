#!/usr/bin/env bash
# Desktop visitor voice and dashboard; phone microphone input, no hardware bringup.
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
DORI_VISITOR_MODEL="$DORI_WS/.state/voice/whisper-small"
if [[ ! -s "$DORI_VISITOR_MODEL/model.bin" ]] || ! python3 -c 'import faster_whisper' >/dev/null 2>&1; then
    echo 'Prepare visitor speech first: scripts/prepare_voice.sh --topic-only' >&2
    exit 1
fi
exec ros2 launch dori_bringup bringup.launch.py \
    dori_mode:=desktop enable_dashboard:=true \
    visitor_mode:=true stt_audio_input_mode:=topic \
    whisper_model:="$DORI_VISITOR_MODEL" "$@"

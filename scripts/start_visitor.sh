#!/usr/bin/env bash
# Desktop visitor voice and dashboard; phone microphone input, no hardware bringup.
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
export DORI_VISITOR_STT="${DORI_VISITOR_STT:-azure}"
DORI_VISITOR_MODEL="$DORI_WS/.state/voice/whisper-small"
case "$DORI_VISITOR_STT" in
    azure)
        python3 - <<'PY'
from dori_dashboard.azure_speech import AzureSpeechError, load_config
try:
    import azure.cognitiveservices.speech
    load_config()
except (ImportError, AzureSpeechError):
    raise SystemExit('Prepare Azure SDK and F0 settings in .state/voice/azure.env; see web/README.md.') from None
PY
        DORI_VISITOR_ENABLE_STT=false
        ;;
    whisper)
        if [[ ! -s "$DORI_VISITOR_MODEL/model.bin" ]] || ! python3 -c 'import faster_whisper' >/dev/null 2>&1; then
            echo 'Prepare visitor speech first: scripts/prepare_voice.sh --topic-only' >&2
            exit 1
        fi
        DORI_VISITOR_ENABLE_STT=true
        ;;
    *) echo 'DORI_VISITOR_STT must be azure or whisper' >&2; exit 1 ;;
esac
exec ros2 launch dori_bringup bringup.launch.py \
    dori_mode:=desktop enable_dashboard:=true \
    visitor_mode:=true stt_audio_input_mode:=topic enable_stt:="$DORI_VISITOR_ENABLE_STT" \
    whisper_model:="$DORI_VISITOR_MODEL" "$@"

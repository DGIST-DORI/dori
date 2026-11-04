#!/usr/bin/env bash
# Explicit network/model preparation; no import-time model downloads at robot startup.
set -eo pipefail
export PYTHONNOUSERSITE=1
DORI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
topic_only=false
case "${1:-}" in
    --topic-only) topic_only=true; shift ;;
esac
[[ $# == 0 ]] || { echo 'Usage: prepare_voice.sh [--topic-only]' >&2; exit 2; }
dependencies=('numpy==1.24.4' 'scipy==1.10.1' 'faster-whisper>=1,<2' 'google-cloud-texttospeech>=2.34,<3' 'gTTS>=2.5,<3')
if [[ "$topic_only" == false ]]; then dependencies+=('openwakeword>=0.6,<0.7'); fi
mkdir -p "$DORI_ROOT/.state/voice"
export HF_HOME="$DORI_ROOT/.state/voice/huggingface"
"$DORI_ROOT/.venv/bin/python" -m pip install -c "$DORI_ROOT/constraints-robot.txt" "${dependencies[@]}"
"$DORI_ROOT/.venv/bin/python" - "$DORI_ROOT/.state/voice/whisper-small" "$topic_only" <<'PY'
import sys
from faster_whisper.utils import download_model
if sys.argv[2] != 'true':
    import openwakeword
    openwakeword.utils.download_models(model_names=['hey_mycroft'])
download_model('small', output_dir=sys.argv[1])
print('Voice assets ready:', sys.argv[1])
PY

#!/usr/bin/env bash
# Explicit network/model preparation; no import-time model downloads at robot startup.
set -eo pipefail
export PYTHONNOUSERSITE=1
DORI_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
"$DORI_ROOT/.venv/bin/python" -m pip install -c "$DORI_ROOT/constraints-robot.txt" 'numpy==1.24.4' 'scipy==1.10.1' 'openwakeword>=0.6,<0.7' 'faster-whisper>=1,<2'
mkdir -p "$DORI_ROOT/.state/voice"
"$DORI_ROOT/.venv/bin/python" - "$DORI_ROOT/.state/voice/whisper-small" <<'PY'
import sys
import openwakeword
from faster_whisper.utils import download_model
openwakeword.utils.download_models(model_names=['hey_mycroft'])
download_model('small', output_dir=sys.argv[1])
print('Voice assets ready:', sys.argv[1])
PY

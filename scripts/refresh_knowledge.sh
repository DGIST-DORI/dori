#!/usr/bin/env bash
# Stop on collection/validation failure; never publish a partial refresh.
set -eo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$DORI_WS"
python -u tools/crawler/crawl_campus.py "$@" --output "$DORI_WS/data/campus"
incremental=()
if [[ -f "$DORI_WS/data/campus/indexed/CURRENT" ]]; then
    incremental=(--incremental)
fi
python -u ros2_ws/src/dori_llm/dori_llm/build_index.py \
    --docs "$DORI_WS/data/campus/processed" \
    --output "$DORI_WS/data/campus/indexed" \
    --evaluation "$DORI_WS/data/campus/evaluation.json" "${incremental[@]}"

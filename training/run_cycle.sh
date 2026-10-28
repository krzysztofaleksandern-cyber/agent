#!/usr/bin/env bash
# One learning cycle on the GPU box: export dataset -> train -> ollama create -> evaluate.
# Required env: API_URL (e.g. http://100.64.0.1:8080 over Tailscale), ADMIN_API_KEY
# Optional: ALIAS (coder), AGENT (codex), BASE_HF, MIN_RATING (4), EPOCHS (2)
set -euo pipefail
: "${API_URL:?set API_URL}" "${ADMIN_API_KEY:?set ADMIN_API_KEY}"
ALIAS="${ALIAS:-coder}"
AGENT="${AGENT:-codex}"
BASE_HF="${BASE_HF:-unsloth/Qwen2.5-Coder-7B-Instruct-bnb-4bit}"
MIN_RATING="${MIN_RATING:-4}"
EPOCHS="${EPOCHS:-2}"
VERSION="$(date +%Y%m%d-%H%M)"
NAME="devagent-${ALIAS}:${VERSION}"
WORK="${TRAIN_DIR:-/workspace/train}/${VERSION}"
HERE="$(cd "$(dirname "$0")" && pwd)"
AUTH=(-H "Authorization: Bearer ${ADMIN_API_KEY}")

mkdir -p "$WORK"
echo ">> dataset (agent=${AGENT}, min_rating=${MIN_RATING})"
curl -fsS "${AUTH[@]}" "${API_URL}/v1/admin/dataset?min_rating=${MIN_RATING}&agent=${AGENT}" \
  -o "$WORK/data.jsonl"
echo "   $(wc -l < "$WORK/data.jsonl") examples"

echo ">> training ${BASE_HF}"
python "$HERE/train.py" --dataset "$WORK/data.jsonl" --base "$BASE_HF" --out "$WORK" \
  --epochs "$EPOCHS"

echo ">> ollama create ${NAME}"
ollama create "$NAME" -f "$WORK/Modelfile"

echo ">> evaluating candidate"
curl -fsS "${AUTH[@]}" -H "Content-Type: application/json" -X POST \
  "${API_URL}/v1/admin/candidates" \
  -d "{\"alias\": \"${ALIAS}\", \"model\": \"${NAME}\", \"note\": \"${BASE_HF} ${VERSION}\"}"
echo

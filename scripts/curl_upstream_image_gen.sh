#!/usr/bin/env bash
set -euo pipefail

# Leave these blank on purpose. Provide values via env or edit in-place.
DEFAULT_PROJECT_ID=""
DEFAULT_ACCESS_TOKEN=""

PROJECT_ID="${PROJECT_ID:-$DEFAULT_PROJECT_ID}"
ACCESS_TOKEN="${ACCESS_TOKEN:-$DEFAULT_ACCESS_TOKEN}"

GOOGLE_API_BASE="${GOOGLE_API_BASE:-https://daily-cloudcode-pa.sandbox.googleapis.com}"
MODEL="${MODEL:-gemini-3-pro-image}"
USER_AGENT="${USER_AGENT:-antigravity/1.11.3 windows/amd64}"
SESSION_ID="${SESSION_ID:--1234567890}"
PROMPT="${1:-Draw a cute cat}"
REQUEST_ID="${REQUEST_ID:-}"
OUT="${OUT:-upstream-image-response.json}"

if [[ -z "$PROJECT_ID" ]]; then
  echo "error: PROJECT_ID is empty (export PROJECT_ID=... or edit the script)" >&2
  exit 2
fi

if [[ -z "$ACCESS_TOKEN" ]]; then
  echo "error: ACCESS_TOKEN is empty (export ACCESS_TOKEN=... or edit the script)" >&2
  exit 2
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN="python"
fi
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: python3/python not found" >&2
  exit 2
fi

tmp_body="$(mktemp -t upstream-image-body.XXXXXX.json)"
trap 'rm -f "$tmp_body"' EXIT

PROJECT_ID="$PROJECT_ID" MODEL="$MODEL" PROMPT="$PROMPT" SESSION_ID="$SESSION_ID" REQUEST_ID="$REQUEST_ID" \
  "$PYTHON_BIN" - <<'PY' >"$tmp_body"
import json
import os
import sys
import uuid

project_id = os.environ["PROJECT_ID"]
model = os.environ["MODEL"]
prompt = os.environ["PROMPT"]
session_id = os.environ.get("SESSION_ID", "").strip()
request_id = os.environ.get("REQUEST_ID", "").strip() or f"agent-debug-{uuid.uuid4()}"

payload = {
    "project": project_id,
    "requestId": request_id,
    "model": model,
    "userAgent": "antigravity",
    "requestType": "image_gen",
    "request": {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"candidateCount": 1},
    },
}

if session_id:
    payload["request"]["sessionId"] = session_id

sys.stdout.write(json.dumps(payload, ensure_ascii=False))
PY

echo "endpoint=${GOOGLE_API_BASE}/v1internal:generateContent" >&2
echo "request_body_file=$tmp_body" >&2
echo "response_file=$OUT" >&2

http_code="$(
  curl -sS --compressed \
    -H "Authorization: Bearer ${ACCESS_TOKEN}" \
    -H "Content-Type: application/json" \
    -H "User-Agent: ${USER_AGENT}" \
    "${GOOGLE_API_BASE}/v1internal:generateContent" \
    --data-binary @"$tmp_body" \
    -o "$OUT" \
    -w "%{http_code}"
)"

echo "http_status=$http_code" >&2
cat "$OUT"

echo "" >&2
echo "response_summary:" >&2
"$PYTHON_BIN" - <<'PY' "$OUT" >&2 || true
import json
import sys

path = sys.argv[1]
data = json.load(open(path, "r", encoding="utf-8"))

resp = data.get("response", {})
candidates = resp.get("candidates", []) if isinstance(resp, dict) else []
parts = (
    candidates[0].get("content", {}).get("parts", [])
    if candidates and isinstance(candidates[0], dict)
    else []
)

print("parts_count", len(parts))
for i, part in enumerate(parts):
    if not isinstance(part, dict):
        print(i, "non_dict_part", type(part).__name__)
        continue

    if "inlineData" in part:
        inline = part.get("inlineData") or {}
        b64 = inline.get("data") or ""
        mime = inline.get("mimeType")
        print(i, "inlineData", "mime", mime, "data_len", len(b64), "prefix", b64[:24])
    elif "text" in part:
        text = part.get("text") or ""
        print(i, "text_len", len(text), "prefix", text[:80].replace("\n", "\\n"))
    else:
        print(i, "keys", sorted(part.keys()))
PY

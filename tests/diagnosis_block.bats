#!/usr/bin/env bats
# tests/diagnosis_block.bats — Unit tests for Phase I diagnosis block gate (US-244)
#
# Run with: bats tests/diagnosis_block.bats
#
# Tests verify:
#   - Stream-json output WITH a diagnosis block sets _PHASE_I_DIAGNOSIS_BLOCK
#   - Stream-json output WITHOUT a diagnosis block leaves _PHASE_I_DIAGNOSIS_BLOCK empty
#   - SPIRAL_SKIP_DIAGNOSIS_CHECK=true bypasses the gate
#   - Partial diagnosis block (only some headers) is rejected
#   - Diagnosis block is stored in prd.json under _phaseI.diagnosisBlock

# ── Setup / teardown ──────────────────────────────────────────────────────────

setup() {
  export TMPDIR_DB
  TMPDIR_DB="$(mktemp -d)"

  export SPIRAL_SCRATCH_DIR="$TMPDIR_DB"
  export PRD_FILE="$TMPDIR_DB/prd.json"
  export PROGRESS_FILE="$TMPDIR_DB/progress.txt"
  export NEXT_STORY="US-TEST"
  export STORY_TITLE="Test Story"
  export ITERATION=1
  export MAX_RETRIES=3
  export SPIRAL_SKIP_DIAGNOSIS_CHECK="false"

  touch "$PROGRESS_FILE"

  # Minimal prd.json with a single test story (passes: true, simulating agent success)
  cat > "$PRD_FILE" <<'EOF'
{
  "userStories": [
    {"id": "US-TEST", "title": "Test Story", "passes": true, "_retryCount": 0}
  ]
}
EOF

  # Resolve jq binary
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Stub helpers used by the gate block
  increment_retry() {
    local sid="$1"
    local cur
    cur=$($JQ -r ".userStories[] | select(.id == \"$sid\") | ._retryCount // 0" "$PRD_FILE" | tr -d '\r')
    $JQ "(.userStories[] | select(.id == \"$sid\") | ._retryCount) = $((cur + 1))" \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
  }
  export -f increment_retry

  get_retry_count() {
    local sid="$1"
    $JQ -r ".userStories[] | select(.id == \"$sid\") | ._retryCount // 0" "$PRD_FILE" | tr -d '\r'
  }
  export -f get_retry_count

  log_ralph_event() {
    printf '%s %s\n' "$1" "${2:-}" >> "$TMPDIR_DB/events.log"
  }
  export -f log_ralph_event

  log_spiral_event() {
    printf '%s %s\n' "$1" "${2:-}" >> "$TMPDIR_DB/spiral_events.log"
  }
  export -f log_spiral_event

  append_result() {
    printf '%s\n' "$1" >> "$TMPDIR_DB/results.log"
  }
  export -f append_result

  STORIES_COMPLETED=1
  export STORIES_COMPLETED
}

teardown() {
  rm -rf "$TMPDIR_DB"
}

# ── Helper: build a stream-json file with a given text block ──────────────────

make_stream_json() {
  local text="$1"
  local outfile="$2"
  # Emit a minimal stream-json line with assistant text content
  python3 -c "
import json, sys
text = sys.argv[1]
line = json.dumps({'type': 'assistant', 'message': {'role': 'assistant', 'content': [{'type': 'text', 'text': text}]}})
print(line)
" "$text" > "$outfile"
}

# ── Helper: run the diagnosis block extraction logic (mirrors ralph.sh code) ──

extract_diagnosis() {
  local stream_file="$1"
  _PHASE_I_DIAGNOSIS_BLOCK=""
  if [[ -f "$stream_file" ]]; then
    local _DIAG_TEXT
    _DIAG_TEXT=$(python3 - "$stream_file" <<'DIAG_EXTRACTOR_EOF'
import sys, json
parts = []
try:
    with open(sys.argv[1], encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get('type') == 'assistant':
                    msg = obj.get('message', obj)
                    for block in msg.get('content', []):
                        if block.get('type') == 'text':
                            parts.append(block.get('text', ''))
            except Exception:
                pass
except Exception:
    pass
print('\n'.join(parts))
DIAG_EXTRACTOR_EOF
    2>/dev/null || true)
    if echo "$_DIAG_TEXT" | grep -q "## Current State" && \
       echo "$_DIAG_TEXT" | grep -qiE "## Problem( Identified)?$|## Problem Identified" && \
       echo "$_DIAG_TEXT" | grep -q "## Planned Changes"; then
      _PHASE_I_DIAGNOSIS_BLOCK=$(echo "$_DIAG_TEXT" | \
        awk '/## Current State/{found=1} found{print} /## Planned Changes/{p=1} p && /^##/ && !/## Planned Changes/{exit}' | \
        head -80)
    fi
  fi
  echo "$_PHASE_I_DIAGNOSIS_BLOCK"
}

# ── Tests: diagnosis block extraction ────────────────────────────────────────

@test "extraction: full diagnosis block sets _PHASE_I_DIAGNOSIS_BLOCK" {
  local stream_file="$TMPDIR_DB/stream.json"
  local text="## Current State
The code is missing X.

## Problem Identified
We need to implement X.

## Planned Changes
- Add lib/x.py
- Wire into spiral.sh"
  make_stream_json "$text" "$stream_file"

  result=$(extract_diagnosis "$stream_file")
  [ -n "$result" ]
  echo "$result" | grep -q "## Current State"
}

@test "extraction: no diagnosis headers → empty result" {
  local stream_file="$TMPDIR_DB/stream.json"
  local text="I will now implement the story. Reading prd.json..."
  make_stream_json "$text" "$stream_file"

  result=$(extract_diagnosis "$stream_file")
  [ -z "$result" ]
}

@test "extraction: partial headers (missing Planned Changes) → empty result" {
  local stream_file="$TMPDIR_DB/stream.json"
  local text="## Current State
The code does A.

## Problem Identified
Need to do B."
  make_stream_json "$text" "$stream_file"

  result=$(extract_diagnosis "$stream_file")
  [ -z "$result" ]
}

@test "extraction: partial headers (missing Current State) → empty result" {
  local stream_file="$TMPDIR_DB/stream.json"
  local text="## Problem Identified
Need to fix X.

## Planned Changes
- Edit file.py"
  make_stream_json "$text" "$stream_file"

  result=$(extract_diagnosis "$stream_file")
  [ -z "$result" ]
}

@test "extraction: non-existent stream file → empty result" {
  result=$(extract_diagnosis "$TMPDIR_DB/nonexistent.json")
  [ -z "$result" ]
}

# ── Tests: prd.json checkpoint storage ───────────────────────────────────────

@test "storage: diagnosis block written to _phaseI.diagnosisBlock in prd.json" {
  local block="## Current State
Old code.

## Problem Identified
Needs fix.

## Planned Changes
- Fix it."

  $JQ --arg block "$block" \
    '(.userStories[] | select(.id == "US-TEST") | ._phaseI.diagnosisBlock) = $block' \
    "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE"

  stored=$($JQ -r '.userStories[] | select(.id == "US-TEST") | ._phaseI.diagnosisBlock' "$PRD_FILE")
  echo "$stored" | grep -q "## Current State"
}

# ── Tests: gate behaviour ─────────────────────────────────────────────────────

@test "gate: missing diagnosis block when passes=true sets passes=false" {
  # Simulate: passes=true, no diagnosis block
  _PHASE_I_DIAGNOSIS_BLOCK=""
  SPIRAL_SKIP_DIAGNOSIS_CHECK="false"

  if [[ -z "$_PHASE_I_DIAGNOSIS_BLOCK" && "${SPIRAL_SKIP_DIAGNOSIS_CHECK:-false}" != "true" ]]; then
    $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE"
  fi

  passes=$($JQ -r '.userStories[] | select(.id == "US-TEST") | .passes' "$PRD_FILE")
  [ "$passes" = "false" ]
}

@test "gate: missing diagnosis block writes _failureReason with re-prompt message" {
  _PHASE_I_DIAGNOSIS_BLOCK=""
  SPIRAL_SKIP_DIAGNOSIS_CHECK="false"

  if [[ -z "$_PHASE_I_DIAGNOSIS_BLOCK" && "${SPIRAL_SKIP_DIAGNOSIS_CHECK:-false}" != "true" ]]; then
    $JQ --arg reason 'DIAGNOSIS_BLOCK_MISSING: Diagnosis block required before making changes. Please output your diagnosis first.' \
      '(.userStories[] | select(.id == "'"$NEXT_STORY"'") | ._failureReason) = $reason' \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE"
  fi

  reason=$($JQ -r '.userStories[] | select(.id == "US-TEST") | ._failureReason' "$PRD_FILE")
  echo "$reason" | grep -q "DIAGNOSIS_BLOCK_MISSING"
}

@test "gate: SPIRAL_SKIP_DIAGNOSIS_CHECK=true bypasses the gate" {
  _PHASE_I_DIAGNOSIS_BLOCK=""
  SPIRAL_SKIP_DIAGNOSIS_CHECK="true"

  # Gate should NOT fire — passes stays true
  if [[ -z "$_PHASE_I_DIAGNOSIS_BLOCK" && "${SPIRAL_SKIP_DIAGNOSIS_CHECK:-false}" != "true" ]]; then
    $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE"
  fi

  passes=$($JQ -r '.userStories[] | select(.id == "US-TEST") | .passes' "$PRD_FILE")
  [ "$passes" = "true" ]
}

@test "gate: present diagnosis block leaves passes=true unchanged" {
  _PHASE_I_DIAGNOSIS_BLOCK="## Current State
Old code.

## Problem Identified
Needs update.

## Planned Changes
- Edit lib/foo.py"
  SPIRAL_SKIP_DIAGNOSIS_CHECK="false"

  if [[ -z "$_PHASE_I_DIAGNOSIS_BLOCK" && "${SPIRAL_SKIP_DIAGNOSIS_CHECK:-false}" != "true" ]]; then
    $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE"
  fi

  passes=$($JQ -r '.userStories[] | select(.id == "US-TEST") | .passes' "$PRD_FILE")
  [ "$passes" = "true" ]
}

@test "gate: missing diagnosis block increments retry count" {
  _PHASE_I_DIAGNOSIS_BLOCK=""
  SPIRAL_SKIP_DIAGNOSIS_CHECK="false"

  if [[ -z "$_PHASE_I_DIAGNOSIS_BLOCK" && "${SPIRAL_SKIP_DIAGNOSIS_CHECK:-false}" != "true" ]]; then
    $JQ "(.userStories[] | select(.id == \"$NEXT_STORY\") | .passes) = false" \
      "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE"
    increment_retry "$NEXT_STORY"
  fi

  retries=$($JQ -r '.userStories[] | select(.id == "US-TEST") | ._retryCount // 0' "$PRD_FILE")
  [ "$retries" -eq 1 ]
}

@test "gate: missing diagnosis block appends rejection to results log" {
  _PHASE_I_DIAGNOSIS_BLOCK=""
  SPIRAL_SKIP_DIAGNOSIS_CHECK="false"

  if [[ -z "$_PHASE_I_DIAGNOSIS_BLOCK" && "${SPIRAL_SKIP_DIAGNOSIS_CHECK:-false}" != "true" ]]; then
    append_result "reject"
  fi

  grep -q "reject" "$TMPDIR_DB/results.log"
}

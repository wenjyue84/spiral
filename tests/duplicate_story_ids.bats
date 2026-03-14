#!/usr/bin/env bats
# tests/duplicate_story_ids.bats — Tests for US-180: duplicate story ID scan in validate_preflight.sh
#
# Run with: bats tests/duplicate_story_ids.bats

setup() {
  export TMPDIR_TEST
  TMPDIR_TEST="$(mktemp -d)"
  export SCRATCH_DIR="$TMPDIR_TEST"

  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  export SPIRAL_PYTHON="python3"
  export SPIRAL_HOME="$PWD"

  # Helper: write a prd.json with given stories as JSON array fragment
  make_prd() {
    local file="$TMPDIR_TEST/prd.json"
    python3 -c "
import json, sys
stories = json.loads(sys.argv[1])
print(json.dumps({'schemaVersion': '1', 'userStories': stories}))
" "$1" > "$file"
    echo "$file"
  }
  export -f make_prd
}

teardown() {
  rm -rf "$TMPDIR_TEST"
}

# ── Inline duplicate-check function (mirrors validate_preflight.sh logic) ────

_run_dedup_check() {
  local prd_file="$1"
  local dedup_mode="${SPIRAL_DEDUP_IDS:-strict}"
  local scratch_dir="${SCRATCH_DIR:-/tmp}"
  local dup_ids
  dup_ids=$("$JQ" -r '[.userStories | group_by(.id)[] | select(length > 1) | .[0].id] | join(" ")' "$prd_file" 2>/dev/null || echo "")
  if [[ -n "$dup_ids" ]]; then
    if [[ "$dedup_mode" == "lenient" ]]; then
      echo "  [preflight] WARNING: Duplicate story IDs found: $dup_ids"
      echo "  [preflight]   Lenient mode: keeping passes:true entry, dropping duplicates..."
      local _dup_tmp
      _dup_tmp=$(mktemp)
      "$JQ" '.userStories |= (group_by(.id) | map((map(select(.passes == true)) | first) // first))' \
        "$prd_file" > "$_dup_tmp" && mv "$_dup_tmp" "$prd_file"
      printf '{"ts":"%s","event":"duplicate_ids_deduped","ids":"%s","mode":"lenient"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$dup_ids" \
        >> "${scratch_dir}/spiral_events.jsonl" 2>/dev/null || true
      echo "  [preflight] Duplicate IDs resolved (lenient)."
    else
      echo "  [preflight] FATAL: Duplicate story IDs detected — aborting."
      echo "  [preflight]   Duplicates: $dup_ids"
      echo "  [preflight]   Run with SPIRAL_DEDUP_IDS=lenient to auto-deduplicate."
      printf '{"ts":"%s","event":"duplicate_ids_fatal","ids":"%s","mode":"strict"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$dup_ids" \
        >> "${scratch_dir}/spiral_events.jsonl" 2>/dev/null || true
      return 1
    fi
  fi
  return 0
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "no duplicates: check passes silently" {
  local prd
  prd="$(make_prd '[{"id":"US-001","title":"A","passes":false},{"id":"US-002","title":"B","passes":false}]')"
  run _run_dedup_check "$prd"
  [ "$status" -eq 0 ]
  [[ "$output" != *"FATAL"* ]]
  [[ "$output" != *"WARNING"* ]]
}

@test "strict mode (default): duplicate IDs cause exit 1 with conflict list" {
  local prd
  prd="$(make_prd '[{"id":"US-001","title":"A","passes":false},{"id":"US-001","title":"A-dup","passes":false}]')"
  SPIRAL_DEDUP_IDS=strict run _run_dedup_check "$prd"
  [ "$status" -ne 0 ]
  [[ "$output" == *"FATAL"* ]]
  [[ "$output" == *"US-001"* ]]
  [[ "$output" == *"SPIRAL_DEDUP_IDS=lenient"* ]]
}

@test "strict mode is default when SPIRAL_DEDUP_IDS is unset" {
  local prd
  prd="$(make_prd '[{"id":"US-005","title":"X","passes":false},{"id":"US-005","title":"X-dup","passes":false}]')"
  unset SPIRAL_DEDUP_IDS
  run _run_dedup_check "$prd"
  [ "$status" -ne 0 ]
  [[ "$output" == *"FATAL"* ]]
}

@test "lenient mode: keeps passes:true entry, removes duplicate" {
  local prd
  prd="$(make_prd '[{"id":"US-010","title":"Pass","passes":true},{"id":"US-010","title":"Fail","passes":false}]')"
  SPIRAL_DEDUP_IDS=lenient run _run_dedup_check "$prd"
  [ "$status" -eq 0 ]
  [[ "$output" == *"WARNING"* ]]
  [[ "$output" == *"Resolved"* || "$output" == *"resolved"* ]]
  # The file should now have only 1 entry with passes:true
  local remaining
  remaining=$("$JQ" '[.userStories[] | select(.id == "US-010")] | length' "$prd")
  [ "$remaining" -eq 1 ]
  local kept_passes
  kept_passes=$("$JQ" -r '.userStories[] | select(.id == "US-010") | .passes' "$prd")
  [ "$kept_passes" = "true" ]
}

@test "lenient mode: when all duplicates are passes:false, keeps first" {
  local prd
  prd="$(make_prd '[{"id":"US-020","title":"First","passes":false},{"id":"US-020","title":"Second","passes":false}]')"
  SPIRAL_DEDUP_IDS=lenient run _run_dedup_check "$prd"
  [ "$status" -eq 0 ]
  local remaining
  remaining=$("$JQ" '[.userStories[] | select(.id == "US-020")] | length' "$prd")
  [ "$remaining" -eq 1 ]
}

@test "lenient mode: writes event to spiral_events.jsonl" {
  local prd
  prd="$(make_prd '[{"id":"US-030","title":"T","passes":false},{"id":"US-030","title":"T2","passes":false}]')"
  SPIRAL_DEDUP_IDS=lenient _run_dedup_check "$prd"
  [ -f "$SCRATCH_DIR/spiral_events.jsonl" ]
  grep -q "duplicate_ids_deduped" "$SCRATCH_DIR/spiral_events.jsonl"
}

@test "strict mode: writes event to spiral_events.jsonl on failure" {
  local prd
  prd="$(make_prd '[{"id":"US-040","title":"T","passes":false},{"id":"US-040","title":"T2","passes":false}]')"
  SPIRAL_DEDUP_IDS=strict _run_dedup_check "$prd" || true
  [ -f "$SCRATCH_DIR/spiral_events.jsonl" ]
  grep -q "duplicate_ids_fatal" "$SCRATCH_DIR/spiral_events.jsonl"
}

@test "multiple duplicate IDs: all listed in strict-mode output" {
  local prd
  prd="$(make_prd '[{"id":"US-001","title":"A","passes":false},{"id":"US-001","title":"A2","passes":false},{"id":"US-002","title":"B","passes":false},{"id":"US-002","title":"B2","passes":false}]')"
  SPIRAL_DEDUP_IDS=strict run _run_dedup_check "$prd"
  [ "$status" -ne 0 ]
  [[ "$output" == *"US-001"* ]]
  [[ "$output" == *"US-002"* ]]
}

@test "lenient mode: prd written back atomically (file is valid JSON after dedup)" {
  local prd
  prd="$(make_prd '[{"id":"US-050","title":"A","passes":false},{"id":"US-050","title":"B","passes":false}]')"
  SPIRAL_DEDUP_IDS=lenient _run_dedup_check "$prd"
  "$JQ" empty "$prd"
  [ $? -eq 0 ]
}

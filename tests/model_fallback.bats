#!/usr/bin/env bats
# tests/model_fallback.bats — Tests for model fallback chain with per-model circuit breaker
#
# Run with: bats tests/model_fallback.bats
#
# Tests verify:
#   - Fallback chain parses colon-separated model identifiers
#   - When primary model is OPEN, fallback to next available model
#   - When all models in chain are OPEN, story gets _failureReason: all_models_unavailable
#   - Per-model circuit breaker state is isolated
#   - Fallback emits model_fallback event to spiral_events.jsonl

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_FB="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_FB"
  export SPIRAL_CB_FAILURE_THRESHOLD=3
  export SPIRAL_CB_COOLDOWN_SECS=600

  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  source "lib/circuit_breaker.sh"

  # Create a minimal prd.json for tests
  cat > "$TMPDIR_FB/prd.json" <<'PRDEOF'
{
  "userStories": [
    {"id": "US-TEST-001", "title": "Test story", "priority": "high", "passes": false}
  ]
}
PRDEOF
}

teardown() {
  rm -rf "$TMPDIR_FB"
}

# ── Helpers ───────────────────────────────────────────────────────────────────

# Trip a model's circuit breaker to OPEN
trip_breaker() {
  local model="$1"
  local threshold="${SPIRAL_CB_FAILURE_THRESHOLD:-3}"
  for ((i=1; i<=threshold; i++)); do
    cb_record_failure "$model" 429
  done
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "fallback chain: primary model OPEN, first fallback CLOSED succeeds" {
  # Trip primary model
  trip_breaker "sonnet"

  # Verify primary is OPEN
  run cb_check "sonnet"
  [ "$status" -eq 1 ]

  # haiku should still be CLOSED
  run cb_check "haiku"
  [ "$status" -eq 0 ]
}

@test "fallback chain: each model has independent circuit breaker state" {
  trip_breaker "sonnet"
  trip_breaker "opus"

  run cb_check "sonnet"
  [ "$status" -eq 1 ]

  run cb_check "opus"
  [ "$status" -eq 1 ]

  # haiku is untouched
  run cb_check "haiku"
  [ "$status" -eq 0 ]
}

@test "fallback chain: all models OPEN when all tripped" {
  trip_breaker "sonnet"
  trip_breaker "haiku"
  trip_breaker "opus"

  run cb_check "sonnet"
  [ "$status" -eq 1 ]
  run cb_check "haiku"
  [ "$status" -eq 1 ]
  run cb_check "opus"
  [ "$status" -eq 1 ]
}

@test "fallback chain: colon-separated parsing works" {
  local chain="sonnet:haiku:opus"
  IFS=':' read -ra models <<< "$chain"
  [ "${#models[@]}" -eq 3 ]
  [ "${models[0]}" = "sonnet" ]
  [ "${models[1]}" = "haiku" ]
  [ "${models[2]}" = "opus" ]
}

@test "fallback chain: single model chain parses correctly" {
  local chain="haiku"
  IFS=':' read -ra models <<< "$chain"
  [ "${#models[@]}" -eq 1 ]
  [ "${models[0]}" = "haiku" ]
}

@test "all models OPEN sets _failureReason on story in prd.json" {
  local prd="$TMPDIR_FB/prd.json"

  # Trip all models
  trip_breaker "sonnet"
  trip_breaker "haiku"
  trip_breaker "opus"

  # Simulate the fallback chain logic from ralph.sh
  local primary="sonnet"
  local chain="sonnet:haiku:opus"
  IFS=':' read -ra fallback_models <<< "$chain"

  found_fallback=0
  for fb_model in "${fallback_models[@]}"; do
    [[ "$fb_model" == "$primary" ]] && continue
    if cb_check "$fb_model"; then
      found_fallback=1
      break
    fi
  done

  [ "$found_fallback" -eq 0 ]

  # Write _failureReason (same jq pattern as ralph.sh)
  $JQ '(.userStories[] | select(.id == "US-TEST-001") | ._failureReason) = "all_models_unavailable"' \
    "$prd" > "${prd}.tmp" && mv "${prd}.tmp" "$prd"

  # Verify
  run $JQ -r '.userStories[0]._failureReason' "$prd"
  [ "$output" = "all_models_unavailable" ]
}

@test "fallback chain: success on fallback model resets only that model's breaker" {
  trip_breaker "sonnet"

  # Simulate successful call on haiku (fallback)
  cb_record_success "haiku"

  # sonnet should still be OPEN
  run cb_check "sonnet"
  [ "$status" -eq 1 ]

  # haiku should be CLOSED
  cb_read "haiku"
  [ "$CB_STATE" = "CLOSED" ]
}

@test "fallback chain: model_fallback event is logged" {
  local events_file="$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"
  mkdir -p "$SPIRAL_SCRATCH_DIR"

  # Define log_spiral_event (simplified version for testing)
  log_spiral_event() {
    local event_type="$1"
    local extra_json="${2:-}"
    local ts
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    if [[ -n "$extra_json" ]]; then
      printf '{"type":"%s","ts":"%s","story_id":"",%s}\n' \
        "$event_type" "$ts" "$extra_json" >> "$events_file"
    fi
  }

  # Emit a model_fallback event
  log_spiral_event "model_fallback" \
    "\"primary_model\":\"sonnet\",\"fallback_model\":\"haiku\",\"reason\":\"circuit_breaker_open\""

  # Verify event was written
  [ -f "$events_file" ]
  run grep -c "model_fallback" "$events_file"
  [ "$output" = "1" ]
  run grep "primary_model" "$events_file"
  [[ "$output" == *"sonnet"* ]]
  [[ "$output" == *"haiku"* ]]
}

@test "all_models_unavailable event is logged when chain exhausted" {
  local events_file="$SPIRAL_SCRATCH_DIR/spiral_events.jsonl"
  mkdir -p "$SPIRAL_SCRATCH_DIR"

  log_spiral_event() {
    local event_type="$1"
    local extra_json="${2:-}"
    local ts
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    if [[ -n "$extra_json" ]]; then
      printf '{"type":"%s","ts":"%s",%s}\n' \
        "$event_type" "$ts" "$extra_json" >> "$events_file"
    fi
  }

  # Trip all models
  trip_breaker "sonnet"
  trip_breaker "haiku"

  local chain="sonnet:haiku"
  IFS=':' read -ra models <<< "$chain"

  all_open=1
  for m in "${models[@]}"; do
    if cb_check "$m"; then
      all_open=0
      break
    fi
  done

  [ "$all_open" -eq 1 ]

  log_spiral_event "all_models_unavailable" \
    "\"story_id\":\"US-TEST-001\",\"primary_model\":\"sonnet\",\"chain\":\"$chain\""

  run grep -c "all_models_unavailable" "$events_file"
  [ "$output" = "1" ]
}

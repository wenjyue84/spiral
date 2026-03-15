#!/usr/bin/env bats
# tests/policy_check.bats — Unit tests for policy adherence gate (US-242)
#
# Run with: bats tests/policy_check.bats
#
# Tests verify:
#   - policy_load creates .spiral/policy.json with safe defaults when missing
#   - policy_check allows operations not in deny list
#   - policy_check blocks operations that match deny patterns
#   - policy_check uses global deny as fallback
#   - policy_log_violation appends to _policyViolations in prd.json
#   - Missing policy file defaults to allow-all
#   - Wildcard deny patterns work correctly

setup() {
  export TMPDIR_PC
  TMPDIR_PC="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_PC"
  export SPIRAL_POLICY_FILE="$TMPDIR_PC/policy.json"
  export PRD_FILE="$TMPDIR_PC/prd.json"
  export NEXT_STORY="US-TEST"

  # Minimal prd.json
  printf '%s\n' '{"userStories":[{"id":"US-TEST","title":"Test Story","passes":false}]}' > "$PRD_FILE"

  # Resolve jq binary
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Source the policy library
  source lib/policy_check.sh
}

teardown() {
  [[ -d "$TMPDIR_PC" ]] && rm -rf "$TMPDIR_PC"
}

# ── Tests: policy_load ────────────────────────────────────────────────────────

@test "policy_load creates policy.json with safe defaults when missing" {
  rm -f "$SPIRAL_POLICY_FILE"
  policy_load
  [ -f "$SPIRAL_POLICY_FILE" ]
}

@test "policy_load creates valid JSON" {
  rm -f "$SPIRAL_POLICY_FILE"
  policy_load
  run "$JQ" empty "$SPIRAL_POLICY_FILE"
  [ "$status" -eq 0 ]
}

@test "policy_load default has global key" {
  rm -f "$SPIRAL_POLICY_FILE"
  policy_load
  result=$("$JQ" -r '.global' "$SPIRAL_POLICY_FILE")
  [ "$result" != "null" ]
}

@test "policy_load default deny list is empty (allow-all by default)" {
  rm -f "$SPIRAL_POLICY_FILE"
  policy_load
  result=$("$JQ" -r '.global.deny | length' "$SPIRAL_POLICY_FILE")
  [ "$result" -eq 0 ]
}

@test "policy_load does not overwrite existing policy file" {
  printf '%s\n' '{"global":{"allow":[],"deny":["git_commit"]}}' > "$SPIRAL_POLICY_FILE"
  policy_load
  result=$("$JQ" -r '.global.deny[0]' "$SPIRAL_POLICY_FILE")
  [ "$result" = "git_commit" ]
}

# ── Tests: policy_check — allow ───────────────────────────────────────────────

@test "policy_check allows operation when deny list is empty" {
  printf '%s\n' '{"global":{"allow":["*"],"deny":[]}}' > "$SPIRAL_POLICY_FILE"
  run policy_check "git_commit" "I"
  [ "$status" -eq 0 ]
}

@test "policy_check allows operation not in deny list" {
  printf '%s\n' '{"global":{"allow":[],"deny":["git_push"]}}' > "$SPIRAL_POLICY_FILE"
  run policy_check "git_commit" "I"
  [ "$status" -eq 0 ]
}

@test "policy_check allows all operations with default policy (allow-all)" {
  rm -f "$SPIRAL_POLICY_FILE"
  policy_load
  run policy_check "git_push" "M"
  [ "$status" -eq 0 ]
}

# ── Tests: policy_check — deny ────────────────────────────────────────────────

@test "policy_check blocks operation matching global deny list" {
  printf '%s\n' '{"global":{"allow":[],"deny":["git_push"]}}' > "$SPIRAL_POLICY_FILE"
  run policy_check "git_push" "I"
  [ "$status" -eq 1 ]
}

@test "policy_check blocks operation matching phase-specific deny list" {
  printf '%s\n' '{"global":{"allow":["*"],"deny":[]},"I":{"allow":[],"deny":["story_reset"]}}' > "$SPIRAL_POLICY_FILE"
  run policy_check "story_reset" "I"
  [ "$status" -eq 1 ]
}

@test "policy_check blocks operation matching wildcard deny pattern" {
  printf '%s\n' '{"global":{"allow":[],"deny":["git_*"]}}' > "$SPIRAL_POLICY_FILE"
  run policy_check "git_push" "I"
  [ "$status" -eq 1 ]
}

@test "policy_check blocks git_merge matching wildcard" {
  printf '%s\n' '{"global":{"allow":[],"deny":["git_*"]}}' > "$SPIRAL_POLICY_FILE"
  run policy_check "git_merge" "M"
  [ "$status" -eq 1 ]
}

@test "phase-specific deny blocks in that phase but not other phases" {
  printf '%s\n' '{"global":{"allow":["*"],"deny":[]},"I":{"allow":[],"deny":["git_commit"]}}' > "$SPIRAL_POLICY_FILE"
  # In phase I: git_commit is denied
  run policy_check "git_commit" "I"
  [ "$status" -eq 1 ]
  # In phase M: git_commit is allowed (not in M deny, not in global deny)
  run policy_check "git_commit" "M"
  [ "$status" -eq 0 ]
}

@test "policy_check global deny blocks across all phases" {
  printf '%s\n' '{"global":{"allow":[],"deny":["git_push_force"]},"I":{"allow":["*"],"deny":[]}}' > "$SPIRAL_POLICY_FILE"
  run policy_check "git_push_force" "I"
  [ "$status" -eq 1 ]
}

# ── Tests: policy_log_violation ───────────────────────────────────────────────

@test "policy_log_violation adds _policyViolations array to story" {
  policy_log_violation "$PRD_FILE" "US-TEST" "git_push" "M" "$JQ"
  result=$("$JQ" -r '.userStories[] | select(.id=="US-TEST") | ._policyViolations | length' "$PRD_FILE")
  [ "$result" -eq 1 ]
}

@test "policy_log_violation records correct operation name" {
  policy_log_violation "$PRD_FILE" "US-TEST" "git_push" "M" "$JQ"
  result=$("$JQ" -r '.userStories[] | select(.id=="US-TEST") | ._policyViolations[0].operation' "$PRD_FILE")
  [ "$result" = "git_push" ]
}

@test "policy_log_violation records correct phase" {
  policy_log_violation "$PRD_FILE" "US-TEST" "git_merge" "I" "$JQ"
  result=$("$JQ" -r '.userStories[] | select(.id=="US-TEST") | ._policyViolations[0].phase' "$PRD_FILE")
  [ "$result" = "I" ]
}

@test "policy_log_violation sets blocked=true" {
  policy_log_violation "$PRD_FILE" "US-TEST" "story_reset" "I" "$JQ"
  result=$("$JQ" -r '.userStories[] | select(.id=="US-TEST") | ._policyViolations[0].blocked' "$PRD_FILE")
  [ "$result" = "true" ]
}

@test "policy_log_violation appends multiple violations in order" {
  policy_log_violation "$PRD_FILE" "US-TEST" "git_push" "M" "$JQ"
  policy_log_violation "$PRD_FILE" "US-TEST" "git_merge" "M" "$JQ"
  result=$("$JQ" -r '.userStories[] | select(.id=="US-TEST") | ._policyViolations | length' "$PRD_FILE")
  [ "$result" -eq 2 ]
  op0=$("$JQ" -r '.userStories[] | select(.id=="US-TEST") | ._policyViolations[0].operation' "$PRD_FILE")
  op1=$("$JQ" -r '.userStories[] | select(.id=="US-TEST") | ._policyViolations[1].operation' "$PRD_FILE")
  [ "$op0" = "git_push" ]
  [ "$op1" = "git_merge" ]
}

@test "policy_log_violation records timestamp field" {
  policy_log_violation "$PRD_FILE" "US-TEST" "git_push" "M" "$JQ"
  result=$("$JQ" -r '.userStories[] | select(.id=="US-TEST") | ._policyViolations[0].timestamp' "$PRD_FILE")
  [ "$result" != "null" ] && [ -n "$result" ]
}

@test "policy_log_violation is non-fatal when prd file missing" {
  run policy_log_violation "/nonexistent/dir/prd.json" "US-TEST" "git_push" "M" "$JQ"
  [ "$status" -eq 0 ]
}

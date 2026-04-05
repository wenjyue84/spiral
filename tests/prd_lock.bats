#!/usr/bin/env bats
# tests/prd_lock.bats — Tests for US-1137: atomic_patch_prd serialization
#
# Run with: bats tests/prd_lock.bats

bats_require_minimum_version 1.7.0

setup() {
  TMPDIR_ROOT="$(mktemp -d)"
  export TMPDIR_ROOT
  # Use bundled jq if available
  if [[ -f "$BATS_TEST_DIRNAME/../ralph/jq.exe" ]]; then
    export JQ="$BATS_TEST_DIRNAME/../ralph/jq.exe"
  else
    export JQ="jq"
  fi
  source "$BATS_TEST_DIRNAME/../lib/core/prd_lock.sh"
}

teardown() {
  rm -rf "$TMPDIR_ROOT"
}

_make_prd() {
  local dir="$1"
  local story_id="${2:-US-TEST}"
  mkdir -p "$dir"
  printf '{"userStories":[{"id":"%s","_antiPatterns":[]}]}\n' "$story_id" >"$dir/prd.json"
}

# ── Basic patch ───────────────────────────────────────────────────────────────

@test "atomic_patch_prd: updates branchName correctly" {
  local wtree="$TMPDIR_ROOT/w1"
  _make_prd "$wtree"

  run atomic_patch_prd "$wtree" '.branchName = $b' --arg b "test-branch"
  [ "$status" -eq 0 ]
  result=$("$JQ" -r '.branchName' "$wtree/prd.json")
  [ "$result" = "test-branch" ]
}

@test "atomic_patch_prd: lock is released after success" {
  local wtree="$TMPDIR_ROOT/w2"
  _make_prd "$wtree"

  atomic_patch_prd "$wtree" '.branchName = "x"'
  [ ! -d "$wtree/prd.json.lock" ]
}

@test "atomic_patch_prd: lock is released after failure" {
  local wtree="$TMPDIR_ROOT/w3"
  mkdir -p "$wtree"
  # No prd.json → jq will fail
  run atomic_patch_prd "$wtree" '.x = 1'
  [ ! -d "$wtree/prd.json.lock" ]
}

@test "atomic_patch_prd: stale lock (>60s) is removed and succeeds" {
  local wtree="$TMPDIR_ROOT/w4"
  _make_prd "$wtree"

  # Create a fake stale lock and back-date its mtime to 1970 (ancient)
  mkdir -p "$wtree/prd.json.lock"
  echo "99999" >"$wtree/prd.json.lock/pid"
  touch -t 197001010000 "$wtree/prd.json.lock" 2>/dev/null ||
    touch -d "1970-01-01" "$wtree/prd.json.lock" 2>/dev/null || true

  run atomic_patch_prd "$wtree" '.branchName = "after-stale"'
  [ "$status" -eq 0 ]
  result=$("$JQ" -r '.branchName' "$wtree/prd.json")
  [ "$result" = "after-stale" ]
}

# ── Concurrency: 10 parallel appends must all land ───────────────────────────

@test "atomic_patch_prd: 10 concurrent appends produce all 10 entries" {
  local wtree="$TMPDIR_ROOT/concurrent"
  _make_prd "$wtree" "US-CONC"

  # Launch 10 parallel subshells, each appending one entry to ._antiPatterns
  local pids=()
  for i in $(seq 1 10); do
    (
      source "$BATS_TEST_DIRNAME/../lib/core/prd_lock.sh"
      export JQ
      atomic_patch_prd "$wtree" \
        '(.userStories[] | select(.id == "US-CONC") | ._antiPatterns) |= . + [{"i": ($i | tonumber)}]' \
        --arg i "$i"
    ) &
    pids+=($!)
  done

  # Wait for all
  local failed=0
  for pid in "${pids[@]}"; do
    wait "$pid" || failed=$((failed + 1))
  done
  [ "$failed" -eq 0 ]

  # All 10 entries must be present
  count=$("$JQ" '[.userStories[] | select(.id == "US-CONC") | ._antiPatterns[]] | length' "$wtree/prd.json")
  [ "$count" -eq 10 ]
}

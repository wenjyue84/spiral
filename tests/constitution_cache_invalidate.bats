#!/usr/bin/env bats
# tests/constitution_cache_invalidate.bats — Tests for US-302:
#   Invalidate research cache automatically when constitution.md content changes
#
# Run with: bats tests/constitution_cache_invalidate.bats
#
# Tests verify:
#   - First run: hash is recorded in _constitution_hash, no cache clearing
#   - Second run with same file: no clearing (hashes match)
#   - Modified constitution: cache entries are cleared and event is emitted
#   - No constitution file: block is a no-op
#   - SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE=false: feature is disabled
#   - Event includes old_hash, new_hash, cleared_count fields

# ── Helper: run the US-302 block in a subshell ───────────────────────────────
# Args: REPO_ROOT, SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE, SPIRAL_SPECKIT_CONSTITUTION
run_cache_invalidate() {
  local repo_root="$1"
  local feature_flag="${2:-true}"
  local speckit_constitution="${3:-}"

  bash -c '
    set -euo pipefail

    REPO_ROOT="$1"
    SCRATCH_DIR="$REPO_ROOT/.spiral"
    RESEARCH_CACHE_DIR="$SCRATCH_DIR/research_cache"
    SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE="$2"
    SPIRAL_SPECKIT_CONSTITUTION="$3"
    SPIRAL_PYTHON="${SPIRAL_PYTHON:-python3}"

    mkdir -p "$SCRATCH_DIR"

    # Stub log_spiral_event — writes events to SCRATCH_DIR/spiral_events.jsonl
    log_spiral_event() {
      local ev="$1"
      local extra="${2:-}"
      printf "{\"event\":\"%s\",%s}\n" "$ev" "$extra" >>"$SCRATCH_DIR/spiral_events.jsonl"
    }

    # ── US-302 block (extracted from spiral.sh) ──────────────────────────────
    if [[ "${SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE:-true}" != "false" ]]; then
      _CONSTITUTION_HASH_FILE="$SCRATCH_DIR/_constitution_hash"
      _CONSTITUTION_FILE=""
      if [[ -n "$SPIRAL_SPECKIT_CONSTITUTION" && -f "$REPO_ROOT/$SPIRAL_SPECKIT_CONSTITUTION" ]]; then
        _CONSTITUTION_FILE="$REPO_ROOT/$SPIRAL_SPECKIT_CONSTITUTION"
      elif [[ -f "$REPO_ROOT/constitution.md" ]]; then
        _CONSTITUTION_FILE="$REPO_ROOT/constitution.md"
      fi
      if [[ -n "$_CONSTITUTION_FILE" ]]; then
        _NEW_CONST_HASH=$(sha256sum "$_CONSTITUTION_FILE" 2>/dev/null | cut -d" " -f1 || \
          "$SPIRAL_PYTHON" -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'"'"'rb'"'"').read()).hexdigest())" \
            "$_CONSTITUTION_FILE" 2>/dev/null || echo "")
        if [[ -n "$_NEW_CONST_HASH" ]]; then
          _OLD_CONST_HASH=""
          [[ -f "$_CONSTITUTION_HASH_FILE" ]] && _OLD_CONST_HASH=$(tr -d "[:space:]" <"$_CONSTITUTION_HASH_FILE" 2>/dev/null || echo "")
          if [[ "$_OLD_CONST_HASH" != "$_NEW_CONST_HASH" ]]; then
            _CONST_CLEARED_COUNT=0
            if [[ -d "$RESEARCH_CACHE_DIR" ]]; then
              _CONST_CLEARED_COUNT=$(find "$RESEARCH_CACHE_DIR" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d "[:space:]")
              find "$RESEARCH_CACHE_DIR" -maxdepth 1 -type f -delete 2>/dev/null || true
            fi
            printf "%s\n" "$_NEW_CONST_HASH" >"$_CONSTITUTION_HASH_FILE"
            if [[ -n "$_OLD_CONST_HASH" ]]; then
              echo "[startup] constitution.md changed — cleared ${_CONST_CLEARED_COUNT} research cache entries"
              log_spiral_event "research_cache_invalidated" \
                "\"old_hash\":\"$_OLD_CONST_HASH\",\"new_hash\":\"$_NEW_CONST_HASH\",\"cleared_count\":${_CONST_CLEARED_COUNT},\"constitution\":\"$(basename "$_CONSTITUTION_FILE")\""
            else
              echo "[startup] constitution.md hash recorded (first run)"
            fi
          fi
        fi
      fi
    fi
  ' -- "$repo_root" "$feature_flag" "$speckit_constitution"
}

# ── Setup / teardown ─────────────────────────────────────────────────────────

setup() {
  TMPDIR_T="$(mktemp -d)"
  export TMPDIR_T
}

teardown() {
  rm -rf "$TMPDIR_T"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "first run: hash is recorded and first-run message printed" {
  echo "# Project goals: be fast" > "$TMPDIR_T/constitution.md"
  mkdir -p "$TMPDIR_T/.spiral/research_cache"

  run run_cache_invalidate "$TMPDIR_T" "true" ""
  [ "$status" -eq 0 ]
  [[ "$output" == *"first run"* ]]
  # Hash file must exist after first run
  [ -f "$TMPDIR_T/.spiral/_constitution_hash" ]
  # No invalidation event on first run (no old hash to compare against)
  [ ! -f "$TMPDIR_T/.spiral/spiral_events.jsonl" ]
}

@test "second run with unchanged constitution: no clearing" {
  echo "# Project goals: be fast" > "$TMPDIR_T/constitution.md"
  mkdir -p "$TMPDIR_T/.spiral/research_cache"
  touch "$TMPDIR_T/.spiral/research_cache/cache1.json"

  # Simulate first run by writing hash
  run run_cache_invalidate "$TMPDIR_T" "true" ""
  [ "$status" -eq 0 ]

  # Place a new cache entry
  touch "$TMPDIR_T/.spiral/research_cache/cache2.json"

  # Second run with same file — no change
  run run_cache_invalidate "$TMPDIR_T" "true" ""
  [ "$status" -eq 0 ]
  [[ "$output" != *"cleared"* ]]
  [ -f "$TMPDIR_T/.spiral/research_cache/cache2.json" ]
}

@test "modified constitution: cache entries cleared and event emitted" {
  echo "# Version 1" > "$TMPDIR_T/constitution.md"
  mkdir -p "$TMPDIR_T/.spiral/research_cache"

  # Simulate a previously completed first run by writing the hash directly
  sha256sum "$TMPDIR_T/constitution.md" | cut -d' ' -f1 > "$TMPDIR_T/.spiral/_constitution_hash"

  # Place cache entries (simulating research that ran during prior iterations)
  touch "$TMPDIR_T/.spiral/research_cache/entry_a.json"
  touch "$TMPDIR_T/.spiral/research_cache/entry_b.json"

  # Modify constitution (triggers hash mismatch)
  echo "# Version 2 — new goals added" > "$TMPDIR_T/constitution.md"

  run run_cache_invalidate "$TMPDIR_T" "true" ""
  [ "$status" -eq 0 ]
  [[ "$output" == *"changed"* ]]
  [[ "$output" == *"2"* ]]  # cleared 2 entries
  # Cache files must be gone
  [ ! -f "$TMPDIR_T/.spiral/research_cache/entry_a.json" ]
  [ ! -f "$TMPDIR_T/.spiral/research_cache/entry_b.json" ]
  # Hash file updated to new hash
  [ -f "$TMPDIR_T/.spiral/_constitution_hash" ]
}

@test "event emitted with old_hash, new_hash, cleared_count fields" {
  echo "# Version 1" > "$TMPDIR_T/constitution.md"
  mkdir -p "$TMPDIR_T/.spiral/research_cache"
  touch "$TMPDIR_T/.spiral/research_cache/item.json"

  run run_cache_invalidate "$TMPDIR_T" "true" ""
  echo "# Version 2" > "$TMPDIR_T/constitution.md"

  run run_cache_invalidate "$TMPDIR_T" "true" ""
  [ "$status" -eq 0 ]

  local events_file="$TMPDIR_T/.spiral/spiral_events.jsonl"
  [ -f "$events_file" ]
  local event_line
  event_line=$(grep "research_cache_invalidated" "$events_file")
  [[ "$event_line" == *'"old_hash"'* ]]
  [[ "$event_line" == *'"new_hash"'* ]]
  [[ "$event_line" == *'"cleared_count"'* ]]
  [[ "$event_line" == *'"constitution"'* ]]
}

@test "SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE=false disables behavior" {
  echo "# Version 1" > "$TMPDIR_T/constitution.md"
  mkdir -p "$TMPDIR_T/.spiral/research_cache"
  touch "$TMPDIR_T/.spiral/research_cache/keep_me.json"

  # Write a stale hash to simulate hash mismatch
  printf 'deadbeef\n' > "$TMPDIR_T/.spiral/_constitution_hash"

  run run_cache_invalidate "$TMPDIR_T" "false" ""
  [ "$status" -eq 0 ]
  [[ "$output" != *"cleared"* ]]
  # Cache must be untouched
  [ -f "$TMPDIR_T/.spiral/research_cache/keep_me.json" ]
  # No event emitted
  [ ! -f "$TMPDIR_T/.spiral/spiral_events.jsonl" ]
}

@test "no constitution file: block is a no-op" {
  mkdir -p "$TMPDIR_T/.spiral/research_cache"
  touch "$TMPDIR_T/.spiral/research_cache/safe.json"
  # No constitution.md, SPIRAL_SPECKIT_CONSTITUTION empty

  run run_cache_invalidate "$TMPDIR_T" "true" ""
  [ "$status" -eq 0 ]
  [[ "$output" != *"cleared"* ]]
  [ -f "$TMPDIR_T/.spiral/research_cache/safe.json" ]
}

@test "SPIRAL_SPECKIT_CONSTITUTION path takes precedence over constitution.md" {
  mkdir -p "$TMPDIR_T/.specify/memory"
  echo "# Spec-Kit constitution v1" > "$TMPDIR_T/.specify/memory/constitution.md"
  echo "# Root constitution (should be ignored)" > "$TMPDIR_T/constitution.md"
  mkdir -p "$TMPDIR_T/.spiral/research_cache"
  touch "$TMPDIR_T/.spiral/research_cache/entry.json"

  # First run
  run run_cache_invalidate "$TMPDIR_T" "true" ".specify/memory/constitution.md"
  [ "$status" -eq 0 ]

  # Hash should be based on speckit file
  local hash1
  hash1=$(cat "$TMPDIR_T/.spiral/_constitution_hash")

  # Modify speckit file
  echo "# Spec-Kit constitution v2" > "$TMPDIR_T/.specify/memory/constitution.md"

  run run_cache_invalidate "$TMPDIR_T" "true" ".specify/memory/constitution.md"
  [ "$status" -eq 0 ]
  [[ "$output" == *"changed"* ]]
  # Cache cleared
  [ ! -f "$TMPDIR_T/.spiral/research_cache/entry.json" ]
}

@test "new hash is written to _constitution_hash after invalidation" {
  echo "# Version 1" > "$TMPDIR_T/constitution.md"
  mkdir -p "$TMPDIR_T/.spiral"

  run run_cache_invalidate "$TMPDIR_T" "true" ""
  local hash_v1
  hash_v1=$(cat "$TMPDIR_T/.spiral/_constitution_hash")

  echo "# Version 2 — changed" > "$TMPDIR_T/constitution.md"
  run run_cache_invalidate "$TMPDIR_T" "true" ""

  local hash_v2
  hash_v2=$(cat "$TMPDIR_T/.spiral/_constitution_hash")
  [ "$hash_v1" != "$hash_v2" ]
  [ -n "$hash_v2" ]
}

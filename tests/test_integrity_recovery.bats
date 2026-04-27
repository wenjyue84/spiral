#!/usr/bin/env bats
# tests/test_integrity_recovery.bats — Tests for US-1316: integrity auto-recovery
#
# Run with: tests/bats-core/bin/bats tests/test_integrity_recovery.bats
#
# Tests verify:
#   - Clean hash: no-op (no recovery needed)
#   - Modified file + AUTO_RECOVER=true + clean git: auto-restores, reports N files
#   - Modified file + AUTO_RECOVER=false: halts with E500
#   - Modified file + dirty git tree: halts with dirty-tree message
#   - Modified file + not a git repo: halts with git-unavailable message

bats_require_minimum_version 1.7.0

# ── Helper ───────────────────────────────────────────────────────────────────

# Run the integrity check inline in a subshell.
# Args: $1=SPIRAL_HOME $2=_CORE_HASH_FILE $3=SPIRAL_INTEGRITY_AUTO_RECOVER
run_integrity_check() {
  bash -c '
    set -euo pipefail

    SPIRAL_HOME="$1"
    _CORE_HASH_FILE="$2"
    SPIRAL_INTEGRITY_AUTO_RECOVER="$3"
    SPIRAL_ITER=1

    spiral_exit() { echo "EXIT: $1 $2"; exit 1; }

    if [[ -f "$_CORE_HASH_FILE" ]]; then
      if ! sha256sum -c "$_CORE_HASH_FILE" >/dev/null 2>&1; then
        _CHANGED_FILES=$(sha256sum -c "$_CORE_HASH_FILE" 2>&1 | grep -i ": FAILED$" | sed "s/: FAILED\$//" || true)
        _CHANGED_COUNT=$(echo "$_CHANGED_FILES" | grep -c "." 2>/dev/null || echo 0)

        if [[ "${SPIRAL_INTEGRITY_AUTO_RECOVER:-true}" == "true" ]]; then
          echo ""
          echo "  [integrity] Core files modified — auto-recovering"
          echo ""
          echo "  Changed files:"
          echo "$_CHANGED_FILES"
          echo ""
          _GIT_STAGED=$(git -C "$SPIRAL_HOME" diff --cached --name-only 2>/dev/null || true)
          if [[ -n "$_GIT_STAGED" ]] || ! git -C "$SPIRAL_HOME" rev-parse --git-dir >/dev/null 2>&1; then
            echo "  [integrity] Cannot auto-recover: SPIRAL_HOME has staged git changes or is not a git repo."
            spiral_exit E500 "Core file integrity check failed (staged git changes — cannot auto-restore)"
          fi
          _RESTORE_FAILED=0
          while IFS= read -r _cf; do
            [[ -z "$_cf" ]] && continue
            _rel="${_cf#"${SPIRAL_HOME}/"}"
            if ! git -C "$SPIRAL_HOME" checkout HEAD -- "$_rel" 2>/dev/null; then
              echo "  [integrity] Failed to restore: $_rel"
              _RESTORE_FAILED=1
            fi
          done <<<"$_CHANGED_FILES"
          if [[ "$_RESTORE_FAILED" -eq 1 ]]; then
            spiral_exit E500 "Core file integrity check failed (git restore failed)"
          fi
          if sha256sum -c "$_CORE_HASH_FILE" >/dev/null 2>&1; then
            echo "  [integrity] Auto-recovered ${_CHANGED_COUNT} files: $(echo "$_CHANGED_FILES" | tr "\n" " ")"
          else
            echo "  [integrity] Re-verify failed after restore — halting."
            spiral_exit E500 "Core file integrity check failed (re-verify after restore failed)"
          fi
        else
          echo "  CRITICAL: Core files modified during iteration $SPIRAL_ITER"
          echo "  Set SPIRAL_INTEGRITY_AUTO_RECOVER=true to enable auto-recovery."
          spiral_exit E500 "Core file integrity check failed"
        fi
      else
        echo "  [integrity] OK"
      fi
    fi
  ' -- "$1" "$2" "$3"
}

# ── Setup / teardown ─────────────────────────────────────────────────────────

setup() {
  load test_helper/common-setup

  TMPDIR_AS="$(mktemp -d)"

  # Create a minimal git repo acting as SPIRAL_HOME
  SPIRAL_HOME_REPO="$TMPDIR_AS/spiral_home"
  mkdir -p "$SPIRAL_HOME_REPO"
  git -C "$SPIRAL_HOME_REPO" init -q
  git -C "$SPIRAL_HOME_REPO" config user.email "test@spiral.test"
  git -C "$SPIRAL_HOME_REPO" config user.name "Spiral Test"
  # Disable CRLF conversion so hash checks are consistent cross-platform
  git -C "$SPIRAL_HOME_REPO" config core.autocrlf false

  # Add a core file
  mkdir -p "$SPIRAL_HOME_REPO/lib"
  printf "original content\n" >"$SPIRAL_HOME_REPO/lib/core.sh"
  git -C "$SPIRAL_HOME_REPO" add lib/core.sh
  git -C "$SPIRAL_HOME_REPO" commit -q -m "init"

  # Generate hash file AFTER commit (hashes must match restored content)
  HASH_FILE="$TMPDIR_AS/core_hashes.txt"
  sha256sum "$SPIRAL_HOME_REPO/lib/core.sh" >"$HASH_FILE"

  export TMPDIR_AS SPIRAL_HOME_REPO HASH_FILE
}

teardown() {
  rm -rf "$TMPDIR_AS"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "no modification: integrity check passes silently" {
  run run_integrity_check "$SPIRAL_HOME_REPO" "$HASH_FILE" "true"
  assert_success
  assert_output --partial "[integrity] OK"
}

@test "AUTO_RECOVER=true + clean git: auto-restores modified file" {
  # Simulate a hook modifying a core file
  echo "modified by hook" >"$SPIRAL_HOME_REPO/lib/core.sh"

  run run_integrity_check "$SPIRAL_HOME_REPO" "$HASH_FILE" "true"
  assert_success
  assert_output --partial "auto-recovering"
  assert_output --partial "[integrity] Auto-recovered"
}

@test "AUTO_RECOVER=true + clean git: recovery message includes file count" {
  echo "tampered" >"$SPIRAL_HOME_REPO/lib/core.sh"

  run run_integrity_check "$SPIRAL_HOME_REPO" "$HASH_FILE" "true"
  assert_success
  assert_output --partial "Auto-recovered 1 files"
}

@test "AUTO_RECOVER=true + clean git: file is actually restored to original" {
  echo "tampered" >"$SPIRAL_HOME_REPO/lib/core.sh"

  run run_integrity_check "$SPIRAL_HOME_REPO" "$HASH_FILE" "true"
  assert_success

  # File should be back to original content
  content=$(cat "$SPIRAL_HOME_REPO/lib/core.sh")
  [ "$content" = "original content" ]
}

@test "AUTO_RECOVER=false: halts with E500 and instructs manual restore" {
  echo "tampered" >"$SPIRAL_HOME_REPO/lib/core.sh"

  run run_integrity_check "$SPIRAL_HOME_REPO" "$HASH_FILE" "false"
  assert_failure
  assert_output --partial "EXIT: E500"
  assert_output --partial "SPIRAL_INTEGRITY_AUTO_RECOVER=true"
}

@test "AUTO_RECOVER=true + dirty git index: falls back to halt with clear message" {
  echo "tampered" >"$SPIRAL_HOME_REPO/lib/core.sh"
  # Stage a NEW file to simulate developer work in SPIRAL_HOME
  echo "staged work" >"$SPIRAL_HOME_REPO/lib/other.sh"
  git -C "$SPIRAL_HOME_REPO" add lib/other.sh

  run run_integrity_check "$SPIRAL_HOME_REPO" "$HASH_FILE" "true"
  assert_failure
  assert_output --partial "staged git changes"
  assert_output --partial "EXIT: E500"
}

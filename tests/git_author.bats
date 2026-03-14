#!/usr/bin/env bats
# tests/git_author.bats — Unit tests for the do_git_commit helper in ralph/ralph.sh
#
# Run with: bats tests/git_author.bats
#
# Tests verify:
#   - When SPIRAL_GIT_AUTHOR is unset, do_git_commit calls plain `git commit -m`
#   - When SPIRAL_GIT_AUTHOR is set, do_git_commit passes -c user.name / user.email
#   - The Generated-By: SPIRAL trailer is appended only when SPIRAL_GIT_AUTHOR is set
#   - SPIRAL_GIT_EMAIL defaults to spiral@noreply.local when SPIRAL_GIT_AUTHOR is set
#     but SPIRAL_GIT_EMAIL is left empty

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export SPIRAL_SCRATCH_DIR="$(mktemp -d)"
  export PRD_FILE="/dev/null"
  export PROGRESS_FILE="/dev/null"
  export SPIRAL_MAX_DIFF_LINES=500

  # Resolve jq binary (same logic as other bats tests)
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Source only the do_git_commit function from ralph.sh
  source <(sed -n '/^do_git_commit()/,/^}/p' ralph/ralph.sh)

  # Stub out `git` so no real commits are attempted; record the full
  # argument list to GIT_CALL_ARGS for assertions.
  git() {
    GIT_CALL_ARGS=("$@")
    return 0
  }
  export -f git
}

teardown() {
  rm -rf "$SPIRAL_SCRATCH_DIR"
  unset SPIRAL_GIT_AUTHOR SPIRAL_GIT_EMAIL GIT_CALL_ARGS
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "do_git_commit: no SPIRAL_GIT_AUTHOR — calls plain git commit -m" {
  unset SPIRAL_GIT_AUTHOR
  do_git_commit "test message"
  [ "${GIT_CALL_ARGS[0]}" = "commit" ]
  [ "${GIT_CALL_ARGS[1]}" = "-m" ]
  [ "${GIT_CALL_ARGS[2]}" = "test message" ]
}

@test "do_git_commit: no SPIRAL_GIT_AUTHOR — no -c flags passed" {
  unset SPIRAL_GIT_AUTHOR
  do_git_commit "test message"
  # None of the args should be '-c'
  for arg in "${GIT_CALL_ARGS[@]}"; do
    [ "$arg" != "-c" ]
  done
}

@test "do_git_commit: SPIRAL_GIT_AUTHOR set — passes -c user.name flag" {
  export SPIRAL_GIT_AUTHOR="SPIRAL Agent"
  export SPIRAL_GIT_EMAIL="spiral@noreply.local"
  do_git_commit "test message"
  # First arg must be -c (identity override)
  [ "${GIT_CALL_ARGS[0]}" = "-c" ]
  [ "${GIT_CALL_ARGS[1]}" = "user.name=SPIRAL Agent" ]
}

@test "do_git_commit: SPIRAL_GIT_AUTHOR set — passes -c user.email flag" {
  export SPIRAL_GIT_AUTHOR="SPIRAL Agent"
  export SPIRAL_GIT_EMAIL="ai@example.com"
  do_git_commit "test message"
  [ "${GIT_CALL_ARGS[2]}" = "-c" ]
  [ "${GIT_CALL_ARGS[3]}" = "user.email=ai@example.com" ]
}

@test "do_git_commit: SPIRAL_GIT_AUTHOR set — appends Generated-By trailer" {
  export SPIRAL_GIT_AUTHOR="SPIRAL Agent"
  export SPIRAL_GIT_EMAIL="spiral@noreply.local"
  do_git_commit "feat: US-001 - My story"
  # The commit message (last arg) should contain the trailer
  local msg="${GIT_CALL_ARGS[-1]}"
  [[ "$msg" == *"Generated-By: SPIRAL"* ]]
}

@test "do_git_commit: no SPIRAL_GIT_AUTHOR — no Generated-By trailer" {
  unset SPIRAL_GIT_AUTHOR
  do_git_commit "feat: US-001 - My story"
  local msg="${GIT_CALL_ARGS[-1]}"
  [[ "$msg" != *"Generated-By: SPIRAL"* ]]
}

@test "do_git_commit: SPIRAL_GIT_EMAIL unset — defaults to spiral@noreply.local" {
  export SPIRAL_GIT_AUTHOR="SPIRAL Agent"
  unset SPIRAL_GIT_EMAIL
  do_git_commit "test message"
  [ "${GIT_CALL_ARGS[3]}" = "user.email=spiral@noreply.local" ]
}

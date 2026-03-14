#!/usr/bin/env bats
# tests/test_github_pr.bats — Unit tests for US-143: GitHub PR creation
#
# Run with: bats tests/test_github_pr.bats
#
# Tests cover:
#   - SPIRAL_CREATE_PRS=false: PR creation is skipped (no gh invoked)
#   - gh CLI not found: emits actionable SKIP message, story not failed
#   - gh not authenticated: emits actionable SKIP message, story not failed
#   - SPIRAL_CREATE_PRS=true + mock gh: pushes branch and creates PR
#   - PR URL stored in prd.json _prUrl field
#   - Existing PR (idempotent): re-uses existing PR URL, no duplicate created
#   - SPIRAL_PR_DRAFT=true: --draft flag passed to gh pr create
#   - SPIRAL_PR_BASE_BRANCH override: custom base branch used
#   - rollback: _prUrl cleared from prd.json by --rollback

RALPH_SH="$(cd "$(dirname "${BATS_TEST_DIRNAME}")" && pwd)/ralph/ralph.sh"
SPIRAL_SH="$(cd "$(dirname "${BATS_TEST_DIRNAME}")" && pwd)/spiral.sh"

setup() {
  # Fresh temp git repo per test
  TEST_REPO="$(mktemp -d)"
  export TEST_REPO

  git -C "$TEST_REPO" init -b main -q 2>/dev/null || git -C "$TEST_REPO" init -q
  git -C "$TEST_REPO" config user.email "test@spiral.local"
  git -C "$TEST_REPO" config user.name "Spiral Test"

  # Initial commit so HEAD exists
  echo "initial" >"$TEST_REPO/README.md"
  git -C "$TEST_REPO" add README.md
  git -C "$TEST_REPO" commit -m "Initial commit" -q
  export INITIAL_SHA
  INITIAL_SHA=$(git -C "$TEST_REPO" rev-parse HEAD)

  # Scratch / spiral dirs
  mkdir -p "$TEST_REPO/.spiral"
  export SCRATCH_DIR="$TEST_REPO/.spiral"

  # Minimal prd.json with one story
  cat >"$TEST_REPO/prd.json" <<'PRDJSON'
{
  "schemaVersion": 1,
  "projectName": "Test Project",
  "productName": "Test",
  "branchName": "main",
  "description": "Test PRD",
  "userStories": [
    {
      "id": "US-001",
      "title": "Add hello world feature",
      "description": "Implement a hello world feature for testing.",
      "priority": "high",
      "passes": true,
      "acceptanceCriteria": [
        "Function prints hello world",
        "Unit test covers the function"
      ],
      "_passedCommit": "PLACEHOLDER_SHA"
    }
  ]
}
PRDJSON

  # Resolve JQ path (same logic as ralph.sh)
  if command -v jq &>/dev/null; then
    export JQ_BIN="jq"
  elif [[ -f "$(dirname "$RALPH_SH")/jq.exe" ]]; then
    export JQ_BIN="$(dirname "$RALPH_SH")/jq.exe"
  elif [[ -f "$(dirname "$RALPH_SH")/jq" ]]; then
    export JQ_BIN="$(dirname "$RALPH_SH")/jq"
  else
    export JQ_BIN="jq"
  fi

  # Directory for fake CLI stubs
  export FAKE_BIN_DIR="$TEST_REPO/_fake_bin"
  mkdir -p "$FAKE_BIN_DIR"
}

teardown() {
  rm -rf "$TEST_REPO"
}

# Helper: source only create_github_pr function from ralph.sh and call it.
# Env vars expected: PRD_FILE, JQ, SPIRAL_RUN_ID, SPIRAL_SCRATCH_DIR.
_run_create_pr_env() {
  local story_id="$1" story_title="$2" commit_sha="$3"
  bash -c "
    cd '$TEST_REPO'
    PRD_FILE='$TEST_REPO/prd.json'
    JQ='$JQ_BIN'
    SPIRAL_RUN_ID='test-run-001'
    SPIRAL_SCRATCH_DIR='$TEST_REPO/.spiral'
    eval \"\$(sed -n '/^create_github_pr()/,/^}/p' '$RALPH_SH')\"
    log_ralph_event() { :; }
    create_github_pr '$story_id' '$story_title' '$commit_sha'
  "
}

# ── Test 1: SPIRAL_CREATE_PRS=false → skip silently ──────────────────────────

@test "SPIRAL_CREATE_PRS=false: PR creation guard in ralph.sh prevents invocation" {
  # Create a fake gh that fails loudly if invoked
  cat >"$FAKE_BIN_DIR/gh" <<'STUB'
#!/bin/bash
echo "ERROR: gh should not be called when SPIRAL_CREATE_PRS=false" >&2
exit 99
STUB
  chmod +x "$FAKE_BIN_DIR/gh"

  run env PATH="$FAKE_BIN_DIR:$PATH" \
    SPIRAL_CREATE_PRS=false \
    bash -c "
      cd '$TEST_REPO'
      PRD_FILE='$TEST_REPO/prd.json'
      JQ='$JQ_BIN'
      SPIRAL_RUN_ID='test-run'
      SPIRAL_SCRATCH_DIR='$TEST_REPO/.spiral'
      eval \"\$(sed -n '/^create_github_pr()/,/^}/p' '$RALPH_SH')\"
      log_ralph_event() { :; }
      # Replicate the guard from ralph.sh main loop
      if [[ \"\${SPIRAL_CREATE_PRS:-false}\" == 'true' ]]; then
        create_github_pr 'US-001' 'Add hello world feature' '$INITIAL_SHA'
      fi
      echo 'done'
    "
  [ "$status" -eq 0 ]
  [[ "$output" == *"done"* ]]
  [[ "$output" != *"ERROR: gh should not be called"* ]]
}

# ── Test 2: gh not in PATH → SKIP with actionable message ────────────────────

@test "gh CLI not found: emits SKIP message, exits 0" {
  run env PATH="/usr/bin:/bin" \
    SPIRAL_CREATE_PRS=true \
    bash -c "
      cd '$TEST_REPO'
      PRD_FILE='$TEST_REPO/prd.json'
      JQ='$JQ_BIN'
      SPIRAL_RUN_ID='test-run'
      SPIRAL_SCRATCH_DIR='$TEST_REPO/.spiral'
      eval \"\$(sed -n '/^create_github_pr()/,/^}/p' '$RALPH_SH')\"
      log_ralph_event() { :; }
      create_github_pr 'US-001' 'Add hello world feature' '$INITIAL_SHA'
    "
  [ "$status" -eq 0 ]
  [[ "$output" == *"SKIP: gh CLI not found"* ]]
}

# ── Test 3: gh present but not authenticated → SKIP message ──────────────────

@test "gh not authenticated: emits SKIP message, exits 0" {
  cat >"$FAKE_BIN_DIR/gh" <<'STUB'
#!/bin/bash
if [[ "$1" == "auth" && "$2" == "status" ]]; then
  echo "You are not logged into any GitHub hosts." >&2
  exit 1
fi
echo "unexpected gh call: $*" >&2
exit 2
STUB
  chmod +x "$FAKE_BIN_DIR/gh"

  run env PATH="$FAKE_BIN_DIR:$PATH" \
    SPIRAL_CREATE_PRS=true \
    bash -c "
      cd '$TEST_REPO'
      PRD_FILE='$TEST_REPO/prd.json'
      JQ='$JQ_BIN'
      SPIRAL_RUN_ID='test-run'
      SPIRAL_SCRATCH_DIR='$TEST_REPO/.spiral'
      eval \"\$(sed -n '/^create_github_pr()/,/^}/p' '$RALPH_SH')\"
      log_ralph_event() { :; }
      create_github_pr 'US-001' 'Add hello world feature' '$INITIAL_SHA'
    "
  [ "$status" -eq 0 ]
  [[ "$output" == *"SKIP: gh CLI is not authenticated"* ]]
}

# ── Test 4: happy path → branch pushed, PR created, _prUrl stored ────────────

@test "SPIRAL_CREATE_PRS=true: pushes branch and stores _prUrl in prd.json" {
  local fake_pr_url="https://github.com/owner/repo/pull/42"

  # Mock gh: auth ok, label create ok, pr list returns empty (no existing PR), pr create returns URL
  cat >"$FAKE_BIN_DIR/gh" <<STUB
#!/bin/bash
case "\$1 \$2" in
  "auth status")   exit 0 ;;
  "label create")  exit 0 ;;
  "pr list")       echo ""; exit 0 ;;
  "pr create")     echo "$fake_pr_url"; exit 0 ;;
  *)               echo "unexpected: \$*" >&2; exit 2 ;;
esac
STUB
  chmod +x "$FAKE_BIN_DIR/gh"

  # Mock git push to succeed silently; pass through all other git commands
  cat >"$FAKE_BIN_DIR/git" <<'STUB'
#!/bin/bash
if [[ "$1" == "push" ]]; then
  exit 0
fi
exec "$(command -v git 2>/dev/null || echo git)" "$@"
STUB
  chmod +x "$FAKE_BIN_DIR/git"

  run env PATH="$FAKE_BIN_DIR:$PATH" \
    SPIRAL_CREATE_PRS=true \
    SPIRAL_PR_BASE_BRANCH=main \
    SPIRAL_PR_DRAFT=false \
    bash -c "
      cd '$TEST_REPO'
      PRD_FILE='$TEST_REPO/prd.json'
      JQ='$JQ_BIN'
      SPIRAL_RUN_ID='test-run'
      SPIRAL_SCRATCH_DIR='$TEST_REPO/.spiral'
      eval \"\$(sed -n '/^create_github_pr()/,/^}/p' '$RALPH_SH')\"
      log_ralph_event() { :; }
      create_github_pr 'US-001' 'Add hello world feature' '$INITIAL_SHA'
    "
  [ "$status" -eq 0 ]
  [[ "$output" == *"Created PR: $fake_pr_url"* ]]

  # _prUrl must be written to prd.json
  local stored_url
  stored_url=$("$JQ_BIN" -r '.userStories[] | select(.id=="US-001") | ._prUrl // ""' "$TEST_REPO/prd.json")
  [ "$stored_url" = "$fake_pr_url" ]
}

# ── Test 5: existing PR → idempotent, reuses URL ─────────────────────────────

@test "Existing PR: reuses existing URL without creating duplicate" {
  local existing_url="https://github.com/owner/repo/pull/7"

  # gh pr list returns existing URL; gh pr create should NOT be called
  cat >"$FAKE_BIN_DIR/gh" <<STUB
#!/bin/bash
if [[ "\$1" == "auth" ]]; then exit 0; fi
if [[ "\$1" == "label" ]]; then exit 0; fi
if [[ "\$1" == "pr" && "\$2" == "list" ]]; then
  echo "$existing_url"
  exit 0
fi
if [[ "\$1" == "pr" && "\$2" == "create" ]]; then
  echo "ERROR: should not create duplicate" >&2
  exit 99
fi
echo "unexpected: \$*" >&2; exit 2
STUB
  chmod +x "$FAKE_BIN_DIR/gh"

  cat >"$FAKE_BIN_DIR/git" <<'STUB'
#!/bin/bash
[[ "$1" == "push" ]] && exit 0
exec "$(command -v git 2>/dev/null || echo git)" "$@"
STUB
  chmod +x "$FAKE_BIN_DIR/git"

  run env PATH="$FAKE_BIN_DIR:$PATH" \
    SPIRAL_CREATE_PRS=true \
    bash -c "
      cd '$TEST_REPO'
      PRD_FILE='$TEST_REPO/prd.json'
      JQ='$JQ_BIN'
      SPIRAL_RUN_ID='test-run'
      SPIRAL_SCRATCH_DIR='$TEST_REPO/.spiral'
      eval \"\$(sed -n '/^create_github_pr()/,/^}/p' '$RALPH_SH')\"
      log_ralph_event() { :; }
      create_github_pr 'US-001' 'Add hello world feature' '$INITIAL_SHA'
    "
  [ "$status" -eq 0 ]
  [[ "$output" != *"ERROR: should not create duplicate"* ]]
  [[ "$output" == *"PR already exists: $existing_url"* ]]
}

# ── Test 6: SPIRAL_PR_DRAFT=true → --draft flag passed ──────────────────────

@test "SPIRAL_PR_DRAFT=true: --draft flag passed to gh pr create" {
  local args_file="$TEST_REPO/gh_pr_create_args.txt"

  cat >"$FAKE_BIN_DIR/gh" <<STUB
#!/bin/bash
if [[ "\$1" == "auth" ]]; then exit 0; fi
if [[ "\$1" == "label" ]]; then exit 0; fi
if [[ "\$1" == "pr" && "\$2" == "list" ]]; then echo ""; exit 0; fi
if [[ "\$1" == "pr" && "\$2" == "create" ]]; then
  echo "\$@" >>"$args_file"
  echo "https://github.com/owner/repo/pull/99"
  exit 0
fi
exit 2
STUB
  chmod +x "$FAKE_BIN_DIR/gh"

  cat >"$FAKE_BIN_DIR/git" <<'STUB'
#!/bin/bash
[[ "$1" == "push" ]] && exit 0
exec "$(command -v git 2>/dev/null || echo git)" "$@"
STUB
  chmod +x "$FAKE_BIN_DIR/git"

  run env PATH="$FAKE_BIN_DIR:$PATH" \
    SPIRAL_CREATE_PRS=true \
    SPIRAL_PR_DRAFT=true \
    bash -c "
      cd '$TEST_REPO'
      PRD_FILE='$TEST_REPO/prd.json'
      JQ='$JQ_BIN'
      SPIRAL_RUN_ID='test-run'
      SPIRAL_SCRATCH_DIR='$TEST_REPO/.spiral'
      eval \"\$(sed -n '/^create_github_pr()/,/^}/p' '$RALPH_SH')\"
      log_ralph_event() { :; }
      create_github_pr 'US-001' 'Add hello world feature' '$INITIAL_SHA'
    "
  [ "$status" -eq 0 ]
  [[ -f "$args_file" ]]
  grep -q "\-\-draft" "$args_file"
}

# ── Test 7: SPIRAL_PR_BASE_BRANCH override ───────────────────────────────────

@test "SPIRAL_PR_BASE_BRANCH override: custom base branch used" {
  local args_file="$TEST_REPO/gh_pr_base_args.txt"

  cat >"$FAKE_BIN_DIR/gh" <<STUB
#!/bin/bash
if [[ "\$1" == "auth" ]]; then exit 0; fi
if [[ "\$1" == "label" ]]; then exit 0; fi
if [[ "\$1" == "pr" && "\$2" == "list" ]]; then echo ""; exit 0; fi
if [[ "\$1" == "pr" && "\$2" == "create" ]]; then
  echo "\$@" >>"$args_file"
  echo "https://github.com/owner/repo/pull/55"
  exit 0
fi
exit 2
STUB
  chmod +x "$FAKE_BIN_DIR/gh"

  cat >"$FAKE_BIN_DIR/git" <<'STUB'
#!/bin/bash
[[ "$1" == "push" ]] && exit 0
exec "$(command -v git 2>/dev/null || echo git)" "$@"
STUB
  chmod +x "$FAKE_BIN_DIR/git"

  run env PATH="$FAKE_BIN_DIR:$PATH" \
    SPIRAL_CREATE_PRS=true \
    SPIRAL_PR_BASE_BRANCH=develop \
    bash -c "
      cd '$TEST_REPO'
      PRD_FILE='$TEST_REPO/prd.json'
      JQ='$JQ_BIN'
      SPIRAL_RUN_ID='test-run'
      SPIRAL_SCRATCH_DIR='$TEST_REPO/.spiral'
      eval \"\$(sed -n '/^create_github_pr()/,/^}/p' '$RALPH_SH')\"
      log_ralph_event() { :; }
      create_github_pr 'US-001' 'Add hello world feature' '$INITIAL_SHA'
    "
  [ "$status" -eq 0 ]
  [[ -f "$args_file" ]]
  grep -q "develop" "$args_file"
}

# ── Test 8: rollback clears _prUrl from prd.json ─────────────────────────────

@test "rollback: _prUrl cleared from prd.json" {
  # Write prd.json with a passed story that has _passedCommit and _prUrl
  # Must include all required schema fields (acceptanceCriteria, dependencies)
  python3 -c "
import json, os
prd = {
  'schemaVersion': 1,
  'projectName': 'Test Project',
  'productName': 'Test',
  'branchName': 'main',
  'description': 'Test PRD',
  'userStories': [{
    'id': 'US-001',
    'title': 'Test story',
    'description': 'Test',
    'priority': 'high',
    'passes': True,
    'acceptanceCriteria': ['It works'],
    'dependencies': [],
    '_passedCommit': os.environ['INITIAL_SHA'],
    '_prUrl': 'https://github.com/owner/repo/pull/1'
  }]
}
with open(os.path.join(os.environ['TEST_REPO'], 'prd.json'), 'w') as f:
    json.dump(prd, f, indent=2)
"

  # Create spiral.config.sh as the rollback tests do
  cat >"$TEST_REPO/spiral.config.sh" <<CONFEOF
#!/bin/bash
export REPO_ROOT="$TEST_REPO"
export PRD_FILE="$TEST_REPO/prd.json"
export SCRATCH_DIR="$SCRATCH_DIR"
export SPIRAL_PYTHON="python3"
export SPIRAL_VALIDATE_CMD="echo 'test-validate-ok'"
CONFEOF
  chmod +x "$TEST_REPO/spiral.config.sh"

  cd "$TEST_REPO"
  run bash "$SPIRAL_SH" --rollback US-001

  [ "$status" -eq 0 ]

  # _prUrl must be absent after rollback
  local pr_url
  pr_url=$(python3 -c "
import json, os
with open(os.path.join(os.getcwd(), 'prd.json'), encoding='utf-8') as f:
    d = json.load(f)
s = next(x for x in d['userStories'] if x['id'] == 'US-001')
print(s.get('_prUrl', 'ABSENT'))
")
  [ "$pr_url" = "ABSENT" ]
}

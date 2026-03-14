#!/usr/bin/env bats
# tests/test_self_review.bats — Tests for US-145 LLM self-review gate (Phase I.5)
#
# Run with: bats tests/test_self_review.bats
#
# Tests verify:
#   - SPIRAL_SKIP_SELF_REVIEW defaults to false (gate enabled by default)
#   - SPIRAL_SELF_REVIEW_MODEL defaults to haiku
#   - run_self_review returns 0 when review response has no critical issues
#   - run_self_review returns 1 when review response has critical issues
#   - run_self_review returns 0 gracefully when claude returns non-JSON
#   - _selfReviewIssues is stored in prd.json on critical find
#   - _REVIEW_TOKENS is set from usage.input_tokens + usage.output_tokens
#   - review_tokens column appears in results.tsv header

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_SR
  TMPDIR_SR="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_SR"

  # Create mock binary directory and prepend to PATH
  export MOCK_BIN="$TMPDIR_SR/bin"
  mkdir -p "$MOCK_BIN"
  export PATH="$MOCK_BIN:$PATH"

  # Resolve jq binary
  if command -v jq &>/dev/null; then
    export JQ="jq"
  elif [[ -f "ralph/jq.exe" ]]; then
    export JQ="ralph/jq.exe"
  elif [[ -f "ralph/jq" ]]; then
    export JQ="ralph/jq"
  fi

  # Stub log_spiral_event and log_ralph_event (not needed in unit tests)
  log_spiral_event() { true; }
  export -f log_spiral_event
  log_ralph_event() { true; }
  export -f log_ralph_event

  # Default PRD_FILE pointing to a temp prd.json
  export PRD_FILE="$TMPDIR_SR/prd.json"
  cat >"$PRD_FILE" <<'EOF'
{
  "userStories": [
    {
      "id": "US-TEST",
      "title": "Test Story",
      "description": "A test story",
      "acceptanceCriteria": ["It works"],
      "dependencies": [],
      "passes": true
    }
  ]
}
EOF
}

teardown() {
  rm -rf "$TMPDIR_SR"
}

# ── Helper: source only run_self_review from ralph.sh ────────────────────────

source_self_review_fn() {
  eval "$(sed -n '/^run_self_review()/,/^}/p' ralph/ralph.sh)"
}

# ── Tests: default config values ─────────────────────────────────────────────

@test "SPIRAL_SKIP_SELF_REVIEW default is false (gate enabled)" {
  # Source defaults from ralph.sh
  eval "$(grep 'SPIRAL_SKIP_SELF_REVIEW=' ralph/ralph.sh | head -1)"
  [[ "$SPIRAL_SKIP_SELF_REVIEW" == "false" ]]
}

@test "SPIRAL_SELF_REVIEW_MODEL default is haiku" {
  eval "$(grep 'SPIRAL_SELF_REVIEW_MODEL=' ralph/ralph.sh | head -1)"
  [[ "$SPIRAL_SELF_REVIEW_MODEL" == "haiku" ]]
}

# ── Tests: run_self_review returns 0 on no critical issues ───────────────────

@test "run_self_review returns 0 when review finds no critical issues" {
  # Stub git to return a diff
  cat >"$MOCK_BIN/git" <<'EOF'
#!/bin/bash
echo "diff --git a/foo.py b/foo.py"
echo "+++ b/foo.py"
echo "+x = 1"
EOF
  chmod +x "$MOCK_BIN/git"

  # Stub claude to return a clean review JSON via stream-json result line
  cat >"$MOCK_BIN/claude" <<'EOF'
#!/bin/bash
# Emit a stream-json result line with no issues
echo '{"type":"result","subtype":"success","result":"{\"issues\":[]}","usage":{"input_tokens":100,"output_tokens":20}}'
EOF
  chmod +x "$MOCK_BIN/claude"

  source_self_review_fn
  run run_self_review "US-TEST"
  [ "$status" -eq 0 ]
}

@test "run_self_review returns 0 when review finds only minor issues" {
  cat >"$MOCK_BIN/git" <<'EOF'
#!/bin/bash
echo "diff --git a/foo.py b/foo.py"
echo "+x = 1"
EOF
  chmod +x "$MOCK_BIN/git"

  cat >"$MOCK_BIN/claude" <<'EOF'
#!/bin/bash
echo '{"type":"result","subtype":"success","result":"{\"issues\":[{\"severity\":\"minor\",\"location\":\"foo.py:1\",\"description\":\"Variable name too short\"}]}","usage":{"input_tokens":150,"output_tokens":30}}'
EOF
  chmod +x "$MOCK_BIN/claude"

  source_self_review_fn
  run run_self_review "US-TEST"
  [ "$status" -eq 0 ]
}

# ── Tests: run_self_review returns 1 on critical issues ──────────────────────

@test "run_self_review returns 1 when review finds a critical issue" {
  cat >"$MOCK_BIN/git" <<'EOF'
#!/bin/bash
echo "diff --git a/api.py b/api.py"
echo "+query = 'SELECT * FROM users WHERE id=' + user_id"
EOF
  chmod +x "$MOCK_BIN/git"

  cat >"$MOCK_BIN/claude" <<'EOF'
#!/bin/bash
echo '{"type":"result","subtype":"success","result":"{\"issues\":[{\"severity\":\"critical\",\"location\":\"api.py:1\",\"description\":\"SQL injection vulnerability: user_id not sanitized\"}]}","usage":{"input_tokens":200,"output_tokens":40}}'
EOF
  chmod +x "$MOCK_BIN/claude"

  source_self_review_fn
  run run_self_review "US-TEST"
  [ "$status" -eq 1 ]
}

@test "run_self_review stores _selfReviewIssues in prd.json on critical find" {
  cat >"$MOCK_BIN/git" <<'EOF'
#!/bin/bash
echo "diff --git a/api.py b/api.py"
echo "+eval(user_input)"
EOF
  chmod +x "$MOCK_BIN/git"

  cat >"$MOCK_BIN/claude" <<'EOF'
#!/bin/bash
echo '{"type":"result","subtype":"success","result":"{\"issues\":[{\"severity\":\"critical\",\"location\":\"api.py:1\",\"description\":\"Code injection via eval\"}]}","usage":{"input_tokens":180,"output_tokens":35}}'
EOF
  chmod +x "$MOCK_BIN/claude"

  source_self_review_fn
  run_self_review "US-TEST" || true

  # _selfReviewIssues should be stored in prd.json
  issues=$($JQ -r '.userStories[] | select(.id == "US-TEST") | ._selfReviewIssues | length' "$PRD_FILE")
  [[ "$issues" -ge 1 ]]
}

# ── Tests: token tracking ─────────────────────────────────────────────────────

@test "run_self_review sets _REVIEW_TOKENS from usage fields" {
  cat >"$MOCK_BIN/git" <<'EOF'
#!/bin/bash
echo "diff --git a/foo.py b/foo.py"
echo "+x = 1"
EOF
  chmod +x "$MOCK_BIN/git"

  cat >"$MOCK_BIN/claude" <<'EOF'
#!/bin/bash
echo '{"type":"result","subtype":"success","result":"{\"issues\":[]}","usage":{"input_tokens":123,"output_tokens":45}}'
EOF
  chmod +x "$MOCK_BIN/claude"

  source_self_review_fn
  _REVIEW_TOKENS=0
  run_self_review "US-TEST" || true
  # _REVIEW_TOKENS should equal 123 + 45 = 168
  [[ "$_REVIEW_TOKENS" -eq 168 ]]
}

# ── Tests: graceful handling of non-JSON response ────────────────────────────

@test "run_self_review returns 0 gracefully when claude returns non-JSON" {
  cat >"$MOCK_BIN/git" <<'EOF'
#!/bin/bash
echo "diff --git a/foo.py b/foo.py"
echo "+x = 1"
EOF
  chmod +x "$MOCK_BIN/git"

  cat >"$MOCK_BIN/claude" <<'EOF'
#!/bin/bash
# Return garbled / empty output
echo '{"type":"result","subtype":"success","result":"sorry I cannot help","usage":{"input_tokens":50,"output_tokens":10}}'
EOF
  chmod +x "$MOCK_BIN/claude"

  source_self_review_fn
  run run_self_review "US-TEST"
  # Should return 0 (non-JSON treated as no issues — fail open)
  [ "$status" -eq 0 ]
}

@test "run_self_review returns 0 when there is no diff" {
  cat >"$MOCK_BIN/git" <<'EOF'
#!/bin/bash
# Return empty diff for both HEAD and HEAD~1
echo ""
EOF
  chmod +x "$MOCK_BIN/git"

  source_self_review_fn
  run run_self_review "US-TEST"
  [ "$status" -eq 0 ]
}

# ── Tests: results.tsv header ────────────────────────────────────────────────

@test "results.tsv header includes review_tokens column" {
  # Extract the header printf line from ralph.sh
  header=$(grep "printf.*review_tokens" ralph/ralph.sh | head -1)
  [[ "$header" == *"review_tokens"* ]]
}

@test "append_result printf includes review_tokens value" {
  # The printf data line should have 14 format specifiers (%s) for 14 columns
  data_line=$(grep -A3 "local safe_title=" ralph/ralph.sh | grep "printf '%s" | head -1)
  count=$(echo "$data_line" | grep -o '%s' | wc -l | tr -d ' ')
  [[ "$count" -ge 14 ]]
}

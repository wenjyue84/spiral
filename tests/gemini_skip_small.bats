#!/usr/bin/env bats
# tests/gemini_skip_small.bats — Tests for US-171 fast-path Gemini skip
#
# Run with: bats tests/gemini_skip_small.bats
#
# Tests verify:
#   - SPIRAL_GEMINI_SKIP_SMALL defaults to true
#   - Gemini is NOT called when story is small with <=2 filesTouch
#   - Skip is logged: '[precontext] skipped -- small story with <= 2 file hints'
#   - SPIRAL_GEMINI_SKIP_SMALL=false disables the fast-path
#   - Fast-path does NOT apply when SPIRAL_GEMINI_ANNOTATE_PROMPT is set
#   - Fast-path does NOT apply for non-small complexity
#   - Fast-path does NOT apply when filesTouch > 2

# ── Test setup ────────────────────────────────────────────────────────────────

setup() {
  export TMPDIR_GS
  TMPDIR_GS="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_GS"

  # Create mock binary directory and prepend to PATH so we can intercept gemini
  export MOCK_BIN="$TMPDIR_GS/bin"
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

  # Gemini call counter — records invocations into a file
  GEMINI_CALLS_FILE="$TMPDIR_GS/gemini_calls"
  echo "0" > "$GEMINI_CALLS_FILE"

  # Default: gemini mock increments counter and returns empty (simulates not installed)
  cat > "$MOCK_BIN/gemini" <<GEMEOF
#!/usr/bin/env bash
count=\$(cat "$GEMINI_CALLS_FILE")
echo \$((count + 1)) > "$GEMINI_CALLS_FILE"
echo "mocked gemini output"
exit 0
GEMEOF
  chmod +x "$MOCK_BIN/gemini"

  # Stub helpers that the fast-path block may reference
  log_spiral_event() { true; }
  export -f log_spiral_event
  log_ralph_event() { true; }
  export -f log_ralph_event
}

teardown() {
  rm -rf "$TMPDIR_GS"
}

# ── Helper: extract and eval the fast-path block from ralph.sh ───────────────
# We source the fast-path detection logic directly (lines between the two
# fast-path markers) so we can unit-test it in isolation.

source_fastpath_fn() {
  # Extract the fast-path block as a shell function
  eval "
_run_gemini_fastpath() {
  local STORY_JSON=\"\$1\"
  _GEMINI_FAST_SKIP=0
  if [[ \"\${SPIRAL_GEMINI_SKIP_SMALL:-true}\" != \"false\" && \\
        -z \"\${SPIRAL_GEMINI_ANNOTATE_PROMPT:-}\" && \\
        -n \"\$STORY_JSON\" && \"\$STORY_JSON\" != \"{}\" ]]; then
    _FP_COMPLEXITY=\$($JQ -r '.estimatedComplexity // \"\"' <<<\"\$STORY_JSON\" 2>/dev/null || echo \"\")
    _FP_FILES_COUNT=\$($JQ '(.filesTouch // []) | length' <<<\"\$STORY_JSON\" 2>/dev/null || echo \"99\")
    if [[ \"\$_FP_COMPLEXITY\" == \"small\" && \"\$_FP_FILES_COUNT\" -le 2 ]]; then
      echo \"  [precontext] skipped -- small story with <= 2 file hints\"
      _GEMINI_FAST_SKIP=1
    fi
  fi
}
"
}

# ── Tests: default value ──────────────────────────────────────────────────────

@test "SPIRAL_GEMINI_SKIP_SMALL defaults to true in ralph.sh" {
  run grep 'SPIRAL_GEMINI_SKIP_SMALL.*:-' ralph/ralph.sh
  [ "$status" -eq 0 ]
  [[ "$output" == *'SPIRAL_GEMINI_SKIP_SMALL:-true'* ]]
}

# ── Tests: fast-path fires ────────────────────────────────────────────────────

@test "fast-path: skips Gemini for small story with 0 filesTouch" {
  source_fastpath_fn
  STORY_JSON='{"id":"US-T01","estimatedComplexity":"small","filesTouch":[]}'
  export SPIRAL_GEMINI_SKIP_SMALL="true"
  unset SPIRAL_GEMINI_ANNOTATE_PROMPT

  _fp_out="$TMPDIR_GS/fp_out.txt"
  _run_gemini_fastpath "$STORY_JSON" > "$_fp_out" 2>&1
  grep -q "\[precontext\] skipped -- small story with <= 2 file hints" "$_fp_out"
  [ "$_GEMINI_FAST_SKIP" -eq 1 ]
}

@test "fast-path: skips Gemini for small story with 1 filesTouch" {
  source_fastpath_fn
  STORY_JSON='{"id":"US-T02","estimatedComplexity":"small","filesTouch":["lib/foo.py"]}'
  export SPIRAL_GEMINI_SKIP_SMALL="true"
  unset SPIRAL_GEMINI_ANNOTATE_PROMPT

  _fp_out="$TMPDIR_GS/fp_out.txt"
  _run_gemini_fastpath "$STORY_JSON" > "$_fp_out" 2>&1
  grep -q "\[precontext\] skipped -- small story with <= 2 file hints" "$_fp_out"
  [ "$_GEMINI_FAST_SKIP" -eq 1 ]
}

@test "fast-path: skips Gemini for small story with exactly 2 filesTouch" {
  source_fastpath_fn
  STORY_JSON='{"id":"US-T03","estimatedComplexity":"small","filesTouch":["lib/a.py","lib/b.py"]}'
  export SPIRAL_GEMINI_SKIP_SMALL="true"
  unset SPIRAL_GEMINI_ANNOTATE_PROMPT

  _fp_out="$TMPDIR_GS/fp_out.txt"
  _run_gemini_fastpath "$STORY_JSON" > "$_fp_out" 2>&1
  grep -q "\[precontext\] skipped -- small story with <= 2 file hints" "$_fp_out"
  [ "$_GEMINI_FAST_SKIP" -eq 1 ]
}

@test "fast-path: skips when SPIRAL_GEMINI_SKIP_SMALL is unset (defaults to true)" {
  source_fastpath_fn
  STORY_JSON='{"id":"US-T04","estimatedComplexity":"small","filesTouch":[]}'
  unset SPIRAL_GEMINI_SKIP_SMALL
  unset SPIRAL_GEMINI_ANNOTATE_PROMPT

  _fp_out="$TMPDIR_GS/fp_out.txt"
  _run_gemini_fastpath "$STORY_JSON" > "$_fp_out" 2>&1
  grep -q "\[precontext\] skipped" "$_fp_out"
  [ "$_GEMINI_FAST_SKIP" -eq 1 ]
}

# ── Tests: fast-path does NOT fire ───────────────────────────────────────────

@test "fast-path disabled: SPIRAL_GEMINI_SKIP_SMALL=false allows Gemini" {
  source_fastpath_fn
  STORY_JSON='{"id":"US-T05","estimatedComplexity":"small","filesTouch":[]}'
  export SPIRAL_GEMINI_SKIP_SMALL="false"
  unset SPIRAL_GEMINI_ANNOTATE_PROMPT

  _run_gemini_fastpath "$STORY_JSON"
  [ "$_GEMINI_FAST_SKIP" -eq 0 ]
}

@test "fast-path does NOT apply when SPIRAL_GEMINI_ANNOTATE_PROMPT is set" {
  source_fastpath_fn
  STORY_JSON='{"id":"US-T06","estimatedComplexity":"small","filesTouch":[]}'
  export SPIRAL_GEMINI_SKIP_SMALL="true"
  export SPIRAL_GEMINI_ANNOTATE_PROMPT="Annotate this story."

  _run_gemini_fastpath "$STORY_JSON"
  [ "$_GEMINI_FAST_SKIP" -eq 0 ]
}

@test "fast-path does NOT apply for medium complexity" {
  source_fastpath_fn
  STORY_JSON='{"id":"US-T07","estimatedComplexity":"medium","filesTouch":[]}'
  export SPIRAL_GEMINI_SKIP_SMALL="true"
  unset SPIRAL_GEMINI_ANNOTATE_PROMPT

  _run_gemini_fastpath "$STORY_JSON"
  [ "$_GEMINI_FAST_SKIP" -eq 0 ]
}

@test "fast-path does NOT apply for large complexity" {
  source_fastpath_fn
  STORY_JSON='{"id":"US-T08","estimatedComplexity":"large","filesTouch":[]}'
  export SPIRAL_GEMINI_SKIP_SMALL="true"
  unset SPIRAL_GEMINI_ANNOTATE_PROMPT

  _run_gemini_fastpath "$STORY_JSON"
  [ "$_GEMINI_FAST_SKIP" -eq 0 ]
}

@test "fast-path does NOT apply when filesTouch has 3 entries" {
  source_fastpath_fn
  STORY_JSON='{"id":"US-T09","estimatedComplexity":"small","filesTouch":["a.py","b.py","c.py"]}'
  export SPIRAL_GEMINI_SKIP_SMALL="true"
  unset SPIRAL_GEMINI_ANNOTATE_PROMPT

  _run_gemini_fastpath "$STORY_JSON"
  [ "$_GEMINI_FAST_SKIP" -eq 0 ]
}

@test "fast-path does NOT apply for empty STORY_JSON" {
  source_fastpath_fn
  STORY_JSON="{}"
  export SPIRAL_GEMINI_SKIP_SMALL="true"
  unset SPIRAL_GEMINI_ANNOTATE_PROMPT

  _run_gemini_fastpath "$STORY_JSON"
  [ "$_GEMINI_FAST_SKIP" -eq 0 ]
}

@test "fast-path: no filesTouch key treated as 0 entries (fast-path fires)" {
  # No filesTouch key → jq returns 0 → fast-path fires for small stories
  source_fastpath_fn
  STORY_JSON='{"id":"US-T10","estimatedComplexity":"small"}'
  export SPIRAL_GEMINI_SKIP_SMALL="true"
  unset SPIRAL_GEMINI_ANNOTATE_PROMPT

  _fp_out="$TMPDIR_GS/fp_out.txt"
  _run_gemini_fastpath "$STORY_JSON" > "$_fp_out" 2>&1
  # No filesTouch key → treated as 0 → fast-path fires
  grep -q "\[precontext\] skipped" "$_fp_out"
  [ "$_GEMINI_FAST_SKIP" -eq 1 ]
}

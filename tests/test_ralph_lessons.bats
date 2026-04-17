#!/usr/bin/env bats
# tests/test_ralph_lessons.bats — Integration tests for US-1258 learned-lessons sidecar
#
# Run with: tests/bats-core/bin/bats tests/test_ralph_lessons.bats

bats_require_minimum_version 1.7.0

setup() {
  load test_helper/common-setup
  _resolve_jq
  export TMPDIR_LL
  TMPDIR_LL="$(mktemp -d)"
  export SPIRAL_SCRATCH_DIR="$TMPDIR_LL"
  export SPIRAL_HOME
  SPIRAL_HOME="$(cd "$BATS_TEST_DIRNAME/.." && pwd)"
  # Resolve python: prefer uv-managed python, fall back to python3/python
  if command -v python3 >/dev/null 2>&1; then
    export SPIRAL_PYTHON="${SPIRAL_PYTHON:-python3}"
  else
    export SPIRAL_PYTHON="${SPIRAL_PYTHON:-python}"
  fi

  # Minimal prompt builder env
  export PROMPT_FILE="$TMPDIR_LL/prompt.txt"
  echo "System prompt" >"$PROMPT_FILE"
  export NEXT_STORY="US-TEST-001"
  export STORY_TITLE="Test Story"
  export PRD_FILE="$TMPDIR_LL/prd.json"
  export PROGRESS_FILE="$TMPDIR_LL/progress.txt"
  export MAX_RETRIES=3
  export RETRY_NOW=0
  export RALPH_FOCUS=""
  export SPIRAL_EPISODIC_MEMORY="false"
  export SPIRAL_REPO_MAP="false"
  export SPIRAL_CONTEXT_MODE="diff"
  export SPIRAL_ANTI_PATTERN_INJECT="true"

  $JQ -n '{"userStories": []}' >"$PRD_FILE"
  echo "## Codebase Patterns" >"$PROGRESS_FILE"

  log_ralph_event() { true; }
  export -f log_ralph_event
  build_files_context() { true; }
  export -f build_files_context
  build_filestouch_context() { true; }
  export -f build_filestouch_context

  _PB_LIB="$SPIRAL_HOME/ralph/lib/prompt_builder.sh"
  [[ -f "$_PB_LIB" ]] || skip "ralph/lib/prompt_builder.sh not found"
  source "$_PB_LIB"
}

teardown() {
  rm -rf "$TMPDIR_LL"
}

_write_lessons_jsonl() {
  local path="$1"
  cat >"$path" <<'JSONL'
{"pattern":"Import sorting fails with ruff I001","fix":"Put stdlib first, third-party second","error_category":"lint","story_title":"Test import fix","seen_count":3,"confidence":0.8}
{"pattern":"Missing encoding=utf-8 on open()","fix":"Always pass encoding='utf-8'","error_category":"runtime","story_title":"UTF-8 crash","seen_count":5,"confidence":0.9}
{"pattern":"Unused variable triggers F841","fix":"Remove or prefix with underscore","error_category":"lint","story_title":"Lint cleanup","seen_count":2,"confidence":0.7}
JSONL
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "US-1258: lessons sidecar injected when lessons match story" {
  local lessons_file="$TMPDIR_LL/learned_lessons.jsonl"
  _write_lessons_jsonl "$lessons_file"
  export SPIRAL_LEARNED_LESSONS="$lessons_file"
  export SPIRAL_LESSON_INJECTION="true"

  export STORY_JSON=$($JQ -n '{
    "id": "US-TEST-001",
    "title": "Fix import sorting lint errors",
    "description": "Resolve ruff I001 import sorting failures",
    "tags": ["lint"],
    "filesTouch": []
  }')

  build_ralph_prompts

  [[ "$RALPH_USER_PROMPT" == *"Learned Lessons"* ]]
  [[ "$RALPH_USER_PROMPT" == *"Import sorting"* ]]
}

@test "US-1258: sidecar file created at expected path" {
  local lessons_file="$TMPDIR_LL/learned_lessons.jsonl"
  _write_lessons_jsonl "$lessons_file"
  export SPIRAL_LEARNED_LESSONS="$lessons_file"
  export SPIRAL_LESSON_INJECTION="true"

  export STORY_JSON=$($JQ -n '{
    "id": "US-TEST-001",
    "title": "Fix ruff lint errors",
    "description": "Fix import sorting",
    "tags": [],
    "filesTouch": []
  }')

  build_ralph_prompts

  [[ -f "$TMPDIR_LL/ralph-lessons-US-TEST-001.md" ]]
}

@test "US-1258: disabled when SPIRAL_LESSON_INJECTION=false" {
  local lessons_file="$TMPDIR_LL/learned_lessons.jsonl"
  _write_lessons_jsonl "$lessons_file"
  export SPIRAL_LEARNED_LESSONS="$lessons_file"
  export SPIRAL_LESSON_INJECTION="false"

  export STORY_JSON=$($JQ -n '{
    "id": "US-TEST-001",
    "title": "Fix import sorting lint errors",
    "description": "Resolve ruff I001 import sorting failures",
    "tags": ["lint"],
    "filesTouch": []
  }')

  build_ralph_prompts

  [[ "$RALPH_USER_PROMPT" != *"Learned Lessons"* ]]
}

@test "US-1258: skip silently when no lessons file exists" {
  export SPIRAL_LEARNED_LESSONS="$TMPDIR_LL/nonexistent.jsonl"
  export SPIRAL_LESSON_INJECTION="true"

  export STORY_JSON=$($JQ -n '{
    "id": "US-TEST-001",
    "title": "Test Story",
    "tags": [],
    "filesTouch": []
  }')

  build_ralph_prompts

  [[ "$RALPH_USER_PROMPT" != *"Learned Lessons"* ]]
}

#!/usr/bin/env bats
# tests/tool_examples.bats — Per-tool usage examples loading (US-340)
#
# Verifies that ralph/tool_examples.json is valid, has required tools,
# and that examples are correctly formatted and loadable into the system prompt.

bats_require_minimum_version 1.7.0
setup() {
  load test_helper/common-setup
  _resolve_jq
  export TOOL_EXAMPLES_FILE="${BATS_TEST_DIRNAME}/../ralph/tool_examples.json"
}

# ── JSON validity ─────────────────────────────────────────────────────────────

@test "tool_examples.json is valid JSON" {
  run "$JQ" '.' "$TOOL_EXAMPLES_FILE"
  assert_success
}

# ── Required tool keys ────────────────────────────────────────────────────────

@test "tool_examples.json has bash_execute tool" {
  run "$JQ" -e '.tools.bash_execute' "$TOOL_EXAMPLES_FILE"
  assert_success
}

@test "tool_examples.json has file_write tool" {
  run "$JQ" -e '.tools.file_write' "$TOOL_EXAMPLES_FILE"
  assert_success
}

@test "tool_examples.json has git_commit tool" {
  run "$JQ" -e '.tools.git_commit' "$TOOL_EXAMPLES_FILE"
  assert_success
}

@test "tool_examples.json has run_tests tool" {
  run "$JQ" -e '.tools.run_tests' "$TOOL_EXAMPLES_FILE"
  assert_success
}

# ── Example counts (2-5 per tool) ────────────────────────────────────────────

@test "bash_execute has 2-5 examples" {
  local count
  count=$("$JQ" '.tools.bash_execute.input_examples | length' "$TOOL_EXAMPLES_FILE")
  [ "$count" -ge 2 ]
  [ "$count" -le 5 ]
}

@test "file_write has 2-5 examples" {
  local count
  count=$("$JQ" '.tools.file_write.input_examples | length' "$TOOL_EXAMPLES_FILE")
  [ "$count" -ge 2 ]
  [ "$count" -le 5 ]
}

@test "git_commit has 2-5 examples" {
  local count
  count=$("$JQ" '.tools.git_commit.input_examples | length' "$TOOL_EXAMPLES_FILE")
  [ "$count" -ge 2 ]
  [ "$count" -le 5 ]
}

@test "run_tests has 2-5 examples" {
  local count
  count=$("$JQ" '.tools.run_tests.input_examples | length' "$TOOL_EXAMPLES_FILE")
  [ "$count" -ge 2 ]
  [ "$count" -le 5 ]
}

# ── Example structure ─────────────────────────────────────────────────────────

@test "every example has description and input fields" {
  local missing
  missing=$("$JQ" '
    [.tools[].input_examples[] |
      select(.description == null or .input == null) |
      .description // "null"
    ] | length
  ' "$TOOL_EXAMPLES_FILE")
  [ "$missing" -eq 0 ]
}

@test "every example input has a command or file_path field" {
  local invalid
  invalid=$("$JQ" '
    [.tools[].input_examples[] |
      select(.input.command == null and .input.file_path == null) |
      .description
    ] | length
  ' "$TOOL_EXAMPLES_FILE")
  [ "$invalid" -eq 0 ]
}

@test "every tool has a description field" {
  local missing
  missing=$("$JQ" '
    [.tools | to_entries[] | select(.value.description == null) | .key] | length
  ' "$TOOL_EXAMPLES_FILE")
  [ "$missing" -eq 0 ]
}

# ── System prompt formatting ─────────────────────────────────────────────────

@test "jq formatting produces non-empty output" {
  local output
  output=$("$JQ" -r '
    .tools | to_entries[] |
    "### " + .value.description + " (" + .key + ")\n" +
    ([.value.input_examples[] |
      "- **" + .description + "**\n  ```json\n  " + (.input | tojson) + "\n  ```"
    ] | join("\n"))
  ' "$TOOL_EXAMPLES_FILE")
  [ -n "$output" ]
}

@test "formatted output contains all four tool section headers" {
  local output
  output=$("$JQ" -r '
    .tools | to_entries[] |
    "### " + .value.description + " (" + .key + ")"
  ' "$TOOL_EXAMPLES_FILE")
  echo "$output" | grep -q "bash_execute"
  echo "$output" | grep -q "file_write"
  echo "$output" | grep -q "git_commit"
  echo "$output" | grep -q "run_tests"
}

@test "total example count matches sum of all tools" {
  local total
  total=$("$JQ" '[.tools[].input_examples | length] | add' "$TOOL_EXAMPLES_FILE")
  [ "$total" -ge 8 ]
  [ "$total" -le 20 ]
}

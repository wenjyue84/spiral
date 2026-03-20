#!/usr/bin/env bats
# US-339: Programmatic tool calling (code_execution_20250825) bats tests

bats_require_minimum_version 1.7.0

setup() {
  # Ensure we're in the project root
  cd "$BATS_TEST_DIRNAME/.." || exit 1
  TOOL_MANIFEST="ralph/tool_manifest.json"
  # Find jq binary
  if [[ -f "ralph/jq.exe" ]]; then
    JQ_BIN="ralph/jq.exe"
  else
    JQ_BIN="jq"
  fi
}

@test "US-339: tool_manifest.json exists" {
  [ -f "$TOOL_MANIFEST" ]
}

@test "US-339: tool_manifest has _programmatic_tools_v1 section" {
  local has_prog_tools
  has_prog_tools=$("$JQ_BIN" -r 'has("_programmatic_tools_v1")' "$TOOL_MANIFEST")
  [ "$has_prog_tools" = "true" ]
}

@test "US-339: code_execution tool is defined with correct type" {
  local code_exec_type
  code_exec_type=$("$JQ_BIN" -r '._programmatic_tools_v1.code_execution.type' "$TOOL_MANIFEST")
  [ "$code_exec_type" = "code_execution_20250825" ]
}

@test "US-339: code_execution tool has description" {
  local has_desc
  has_desc=$("$JQ_BIN" -r '._programmatic_tools_v1.code_execution | has("description")' "$TOOL_MANIFEST")
  [ "$has_desc" = "true" ]
}

@test "US-339: bash_execute has allowed_callers" {
  local has_allowed
  has_allowed=$("$JQ_BIN" -r '._programmatic_tools_v1.bash_execute | has("allowed_callers")' "$TOOL_MANIFEST")
  [ "$has_allowed" = "true" ]
}

@test "US-339: bash_execute.allowed_callers includes code_execution_20250825" {
  local has_code_exec
  has_code_exec=$("$JQ_BIN" -r '._programmatic_tools_v1.bash_execute.allowed_callers | map(select(. == "code_execution_20250825")) | length > 0' "$TOOL_MANIFEST")
  [ "$has_code_exec" = "true" ]
}

@test "US-339: file_read has allowed_callers" {
  local has_allowed
  has_allowed=$("$JQ_BIN" -r '._programmatic_tools_v1.file_read | has("allowed_callers")' "$TOOL_MANIFEST")
  [ "$has_allowed" = "true" ]
}

@test "US-339: file_read.allowed_callers includes code_execution_20250825" {
  local has_code_exec
  has_code_exec=$("$JQ_BIN" -r '._programmatic_tools_v1.file_read.allowed_callers | map(select(. == "code_execution_20250825")) | length > 0' "$TOOL_MANIFEST")
  [ "$has_code_exec" = "true" ]
}

@test "US-339: file_write has allowed_callers" {
  local has_allowed
  has_allowed=$("$JQ_BIN" -r '._programmatic_tools_v1.file_write | has("allowed_callers")' "$TOOL_MANIFEST")
  [ "$has_allowed" = "true" ]
}

@test "US-339: file_write.allowed_callers includes code_execution_20250825" {
  local has_code_exec
  has_code_exec=$("$JQ_BIN" -r '._programmatic_tools_v1.file_write.allowed_callers | map(select(. == "code_execution_20250825")) | length > 0' "$TOOL_MANIFEST")
  [ "$has_code_exec" = "true" ]
}

@test "US-339: core tools are defined as array" {
  local is_array
  is_array=$("$JQ_BIN" -r '.core | type' "$TOOL_MANIFEST")
  [ "$is_array" = "array" ]
}

@test "US-339: deferred tools are defined as array" {
  local is_array
  is_array=$("$JQ_BIN" -r '.deferred | type' "$TOOL_MANIFEST")
  [ "$is_array" = "array" ]
}

@test "US-339: core and deferred tools don't overlap" {
  local overlap_count
  overlap_count=$("$JQ_BIN" -r '
    (.core as $core | .deferred as $deferred |
    $core | map(select(. as $item | $deferred | map(. == $item) | any)) |
    length) as $overlap_count |
    $overlap_count
  ' "$TOOL_MANIFEST")
  [ "$overlap_count" -eq 0 ]
}

@test "US-339: all allowed_callers are strings" {
  local invalid_callers
  invalid_callers=$("$JQ_BIN" -r '
    ._programmatic_tools_v1 as $tools |
    [$tools | to_entries[] | select(.key | startswith("_") | not) |
     .value | select(type == "object") | .allowed_callers[]? |
     select(type != "string")] |
    length
  ' "$TOOL_MANIFEST")
  [ "$invalid_callers" -eq 0 ]
}

@test "US-339: _programmatic_tools_v1 has expected tool keys" {
  local tools_json
  tools_json=$("$JQ_BIN" -r '._programmatic_tools_v1 | keys | sort | join(",")' "$TOOL_MANIFEST")
  # Expected: bash_execute, code_execution, file_read, file_write
  [[ "$tools_json" == *"bash_execute"* ]]
  [[ "$tools_json" == *"code_execution"* ]]
  [[ "$tools_json" == *"file_read"* ]]
  [[ "$tools_json" == *"file_write"* ]]
}

@test "US-339: tool_manifest is valid JSON" {
  "$JQ_BIN" empty "$TOOL_MANIFEST"
}

@test "US-339: spiral.config.sh has SPIRAL_PROGRAMMATIC_TOOLS config" {
  grep -q "SPIRAL_PROGRAMMATIC_TOOLS" spiral.config.sh
}

@test "US-339: spiral.config.sh SPIRAL_PROGRAMMATIC_TOOLS has default value" {
  grep -q 'SPIRAL_PROGRAMMATIC_TOOLS="${SPIRAL_PROGRAMMATIC_TOOLS:-' spiral.config.sh
}

@test "US-339: ralph.sh has log_tool_call_from_code function" {
  grep -q "log_tool_call_from_code()" ralph/ralph.sh
}

@test "US-339: ralph.sh has programmatic tools initialization" {
  grep -q "Programmatic tool calling" ralph/ralph.sh
}

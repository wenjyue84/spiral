#!/usr/bin/env bats
# tests/env_validation.bats — Tests for US-264: env var schema validation
#
# Run with: tests/bats-core/bin/bats tests/env_validation.bats

setup() {
  export SPIRAL_HOME="$PWD"

  # Prefer the uv venv Python; fall back to system python3
  if [[ -f "$SPIRAL_HOME/.venv/Scripts/python.exe" ]]; then
    export SPIRAL_PYTHON="$SPIRAL_HOME/.venv/Scripts/python.exe"
  elif [[ -f "$SPIRAL_HOME/.venv/bin/python" ]]; then
    export SPIRAL_PYTHON="$SPIRAL_HOME/.venv/bin/python"
  else
    export SPIRAL_PYTHON="python3"
  fi

  export SCHEMA="$SPIRAL_HOME/env_schema.json"
}

# ── Helper ────────────────────────────────────────────────────────────────────
run_validator() {
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/validate_env.py" --schema "$SCHEMA" "$@"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "env_schema.json exists and is valid JSON" {
  [[ -f "$SCHEMA" ]]
  "$SPIRAL_PYTHON" - "$SCHEMA" <<'EOF'
import json, sys
json.load(open(sys.argv[1], encoding="utf-8"))
EOF
}

@test "env_schema.json contains at least one required var" {
  count=$("$SPIRAL_PYTHON" - "$SCHEMA" <<'EOF'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
print(sum(1 for v in data["vars"] if v.get("required", False)))
EOF
)
  [[ "$count" -gt 0 ]]
}

@test "validator passes when ANTHROPIC_API_KEY is set" {
  export ANTHROPIC_API_KEY="sk-ant-test-key"
  run run_validator
  [ "$status" -eq 0 ]
  [[ "$output" == *"OK"* ]]
}

@test "missing required var prints var name in error output" {
  unset ANTHROPIC_API_KEY
  run run_validator
  [ "$status" -eq 1 ]
  [[ "$output" == *"ANTHROPIC_API_KEY"* ]]
}

@test "missing required var prints description in error output" {
  unset ANTHROPIC_API_KEY
  run run_validator
  [ "$status" -eq 1 ]
  # description contains 'Anthropic API key'
  [[ "$output" == *"Anthropic API key"* ]]
}

@test "missing required var prints fix hint in error output" {
  unset ANTHROPIC_API_KEY
  run run_validator
  [ "$status" -eq 1 ]
  # fix hint starts with 'export ANTHROPIC_API_KEY='
  [[ "$output" == *"export ANTHROPIC_API_KEY="* ]]
}

@test "invalid URL var prints INVALID with type info" {
  export ANTHROPIC_API_KEY="sk-ant-test-key"
  export SPIRAL_NOTIFY_WEBHOOK="not-a-url"
  run run_validator
  [ "$status" -eq 1 ]
  [[ "$output" == *"INVALID"* ]]
  [[ "$output" == *"SPIRAL_NOTIFY_WEBHOOK"* ]]
  unset SPIRAL_NOTIFY_WEBHOOK
}

@test "invalid int var prints INVALID with type info" {
  export ANTHROPIC_API_KEY="sk-ant-test-key"
  export SPIRAL_MAX_PENDING="notanumber"
  run run_validator
  [ "$status" -eq 1 ]
  [[ "$output" == *"INVALID"* ]]
  [[ "$output" == *"SPIRAL_MAX_PENDING"* ]]
  unset SPIRAL_MAX_PENDING
}

@test "valid URL passes type check" {
  export ANTHROPIC_API_KEY="sk-ant-test-key"
  export SPIRAL_NOTIFY_WEBHOOK="https://hooks.example.com/spiral"
  run run_validator
  [ "$status" -eq 0 ]
  unset SPIRAL_NOTIFY_WEBHOOK
}

@test "validator exits 0 when all required vars present and optional vars absent" {
  export ANTHROPIC_API_KEY="sk-ant-test-key"
  unset SPIRAL_NOTIFY_WEBHOOK
  unset OTEL_EXPORTER_OTLP_ENDPOINT
  run run_validator
  [ "$status" -eq 0 ]
}

@test "summary line shows required vars missing count" {
  unset ANTHROPIC_API_KEY
  run run_validator
  [ "$status" -eq 1 ]
  [[ "$output" == *"MISSING required"* ]]
}

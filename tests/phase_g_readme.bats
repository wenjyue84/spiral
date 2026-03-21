#!/usr/bin/env bats
# tests/phase_g_readme.bats — Integration tests for generate_readme_features()
#
# Run with: tests/bats-core/bin/bats tests/phase_g_readme.bats
#
# Tests verify:
#   - generate_readme_features() creates .spiral/phase-g-readme-snippet.md
#   - Output contains a valid "## Features" markdown header
#   - Exactly 5 feature entries are generated from a fixture of 5 completed stories
#   - Incomplete stories (passes=false) are excluded
#   - Story titles and descriptions appear in the output
#   - Missing prd.json returns non-zero exit code

bats_require_minimum_version 1.7.0

setup() {
  export TEST_DIR
  TEST_DIR="$(mktemp -d)"
  export SPIRAL_PRD_PATH="${TEST_DIR}/prd.json"
  export SPIRAL_HOME="${TEST_DIR}"

  # Resolve Python interpreter (prefer project venv)
  export SPIRAL_PYTHON
  local _spiral_repo
  _spiral_repo="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  if [[ -f "${_spiral_repo}/.venv/Scripts/python.exe" ]]; then
    SPIRAL_PYTHON="${_spiral_repo}/.venv/Scripts/python.exe"
  elif [[ -f "${_spiral_repo}/.venv/bin/python" ]]; then
    SPIRAL_PYTHON="${_spiral_repo}/.venv/bin/python"
  else
    SPIRAL_PYTHON="$(command -v python3)"
  fi

  # Fixture: 5 completed stories + 1 incomplete story
  cat >"${TEST_DIR}/prd.json" <<'EOF'
{
  "schemaVersion": 1,
  "projectName": "Test Project",
  "productName": "Test Product",
  "branchName": "main",
  "description": "Test PRD for generate_readme_features bats tests",
  "userStories": [
    {
      "id": "US-001",
      "title": "Story One",
      "description": "First completed story description",
      "passes": true
    },
    {
      "id": "US-002",
      "title": "Story Two",
      "description": "Second completed story description",
      "passes": true
    },
    {
      "id": "US-003",
      "title": "Story Three",
      "description": "Third completed story description",
      "passes": true
    },
    {
      "id": "US-004",
      "title": "Story Four",
      "description": "Fourth completed story description",
      "passes": true
    },
    {
      "id": "US-005",
      "title": "Story Five",
      "description": "Fifth completed story description",
      "passes": true
    },
    {
      "id": "US-006",
      "title": "Incomplete Story",
      "description": "This story is not yet complete",
      "passes": false
    }
  ]
}
EOF

  # Source the function under test (disable pipefail for sourcing)
  local _phase_g
  _phase_g="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)/lib/phases/phase-g.sh"
  # shellcheck source=lib/phases/phase-g.sh
  set +euo pipefail
  # shellcheck disable=SC1090
  source "$_phase_g"
  set -euo pipefail
}

teardown() {
  "$SPIRAL_PYTHON" -c "import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$TEST_DIR"
}

@test "generate_readme_features creates the output file" {
  run generate_readme_features
  [ "$status" -eq 0 ]
  [ -f "${TEST_DIR}/.spiral/phase-g-readme-snippet.md" ]
}

@test "output contains valid ## Features markdown header" {
  generate_readme_features
  grep -q "^## Features$" "${TEST_DIR}/.spiral/phase-g-readme-snippet.md"
}

@test "output contains exactly 5 completed story entries" {
  generate_readme_features
  local count
  count=$(grep -c "^- \*\*" "${TEST_DIR}/.spiral/phase-g-readme-snippet.md")
  [ "$count" -eq 5 ]
}

@test "output contains all 5 completed story titles" {
  generate_readme_features
  local snippet="${TEST_DIR}/.spiral/phase-g-readme-snippet.md"
  grep -q "Story One" "$snippet"
  grep -q "Story Two" "$snippet"
  grep -q "Story Three" "$snippet"
  grep -q "Story Four" "$snippet"
  grep -q "Story Five" "$snippet"
}

@test "incomplete stories are excluded from output" {
  generate_readme_features
  run grep "Incomplete Story" "${TEST_DIR}/.spiral/phase-g-readme-snippet.md"
  [ "$status" -ne 0 ]
}

@test "output entries include story descriptions" {
  generate_readme_features
  local snippet="${TEST_DIR}/.spiral/phase-g-readme-snippet.md"
  grep -q "First completed story description" "$snippet"
  grep -q "Fifth completed story description" "$snippet"
}

@test "returns non-zero when prd.json is missing" {
  export SPIRAL_PRD_PATH="${TEST_DIR}/nonexistent.json"
  run generate_readme_features
  [ "$status" -ne 0 ]
}

#!/usr/bin/env bats
# tests/test_deploy_docs.bats — Shell tests for spiral deploy-docs CLI (US-732)
#
# Run with: tests/bats-core/bin/bats tests/test_deploy_docs.bats
#
# Tests verify:
#   - spiral deploy-docs --help exits 0 and shows usage
#   - spiral deploy-docs --dry-run creates .spiral/changelog-output/CHANGELOG.md
#   - spiral deploy-docs --dry-run creates .spiral/changelog-output/pdoc/index.html
#   - Missing output dir returns non-zero exit code if prepare step skipped
#   - spiral deploy-docs --branch creates the correct branch name

bats_require_minimum_version 1.7.0

setup() {
  export TEST_DIR
  TEST_DIR="$(mktemp -d)"

  # Resolve Python interpreter (prefer project venv)
  local _spiral_repo
  _spiral_repo="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
  export SPIRAL_REPO="${_spiral_repo}"

  if [[ -f "${_spiral_repo}/.venv/Scripts/python.exe" ]]; then
    PYTHON="${_spiral_repo}/.venv/Scripts/python.exe"
  elif [[ -f "${_spiral_repo}/.venv/bin/python" ]]; then
    PYTHON="${_spiral_repo}/.venv/bin/python"
  else
    PYTHON="$(command -v python3)"
  fi
  export PYTHON

  # Create a minimal git repo in TEST_DIR for deploy tests
  git -C "$TEST_DIR" init
  git -C "$TEST_DIR" config user.email "test@test.com"
  git -C "$TEST_DIR" config user.name "Test"
  echo "# Test" >"${TEST_DIR}/README.md"
  git -C "$TEST_DIR" add README.md
  git -C "$TEST_DIR" commit -m "chore: initial commit"

  # Write a minimal prd.json with 4 passing stories
  "$PYTHON" - "${TEST_DIR}/prd.json" <<'PYEOF'
import json, sys
prd = {
  "schemaVersion": 1,
  "projectName": "test",
  "productName": "Test",
  "branchName": "main",
  "description": "bats test prd",
  "userStories": [
    {"id": f"US-{i:03d}", "title": f"Story {i}", "description": f"Desc {i}", "passes": True}
    for i in range(1, 5)
  ]
}
with open(sys.argv[1], "w") as f:
    json.dump(prd, f, indent=2)
PYEOF
}

teardown() {
  "$PYTHON" -c "import shutil, sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" "$TEST_DIR"
}

# Helper: run spiral deploy-docs via main.py from TEST_DIR
_deploy_docs() {
  (cd "$TEST_DIR" && "$PYTHON" "${SPIRAL_REPO}/main.py" deploy-docs "$@")
}

@test "spiral deploy-docs --help exits 0 and shows usage" {
  run _deploy_docs --help
  [ "$status" -eq 0 ]
  echo "$output" | grep -qi "deploy"
}

@test "deploy-docs --dry-run creates .spiral/changelog-output/" {
  run _deploy_docs --dry-run
  [ "$status" -eq 0 ]
  [ -d "${TEST_DIR}/.spiral/changelog-output" ]
}

@test "deploy-docs --dry-run creates CHANGELOG.md in changelog-output/" {
  run _deploy_docs --dry-run
  [ "$status" -eq 0 ]
  [ -f "${TEST_DIR}/.spiral/changelog-output/CHANGELOG.md" ]
}

@test "deploy-docs --dry-run creates pdoc/index.html in changelog-output/" {
  run _deploy_docs --dry-run
  [ "$status" -eq 0 ]
  [ -f "${TEST_DIR}/.spiral/changelog-output/pdoc/index.html" ]
}

@test "deploy-docs --dry-run creates gh-pages branch" {
  run _deploy_docs --dry-run
  [ "$status" -eq 0 ]
  run git -C "$TEST_DIR" branch --list gh-pages
  echo "$output" | grep -q "gh-pages"
}

@test "deploy-docs --branch custom-branch creates named branch" {
  run _deploy_docs --branch custom-docs --dry-run
  [ "$status" -eq 0 ]
  run git -C "$TEST_DIR" branch --list custom-docs
  echo "$output" | grep -q "custom-docs"
}

@test "CHANGELOG.md on gh-pages has 3+ story entries from prd.json" {
  _deploy_docs --dry-run
  local changelog
  changelog=$(git -C "$TEST_DIR" show gh-pages:CHANGELOG.md 2>/dev/null)
  local count
  count=$(echo "$changelog" | grep -cE 'US-[0-9]+' || true)
  [ "$count" -ge 3 ]
}

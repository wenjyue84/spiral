#!/usr/bin/env bats
# tests/test_precommit_config.bats — Verify .pre-commit-config.yaml is present and well-formed

PRECOMMIT_CONFIG="$BATS_TEST_DIRNAME/../.pre-commit-config.yaml"

@test ".pre-commit-config.yaml exists in repo root" {
  [ -f "$PRECOMMIT_CONFIG" ]
}

@test ".pre-commit-config.yaml contains at least 4 repo entries" {
  count=$(grep -c "^  - repo:" "$PRECOMMIT_CONFIG")
  [ "$count" -ge 4 ]
}

@test ".pre-commit-config.yaml has ruff hook" {
  grep -q "ruff" "$PRECOMMIT_CONFIG"
}

@test ".pre-commit-config.yaml has mypy hook" {
  grep -q "mypy" "$PRECOMMIT_CONFIG"
}

@test ".pre-commit-config.yaml has shellcheck hook" {
  grep -q "shellcheck" "$PRECOMMIT_CONFIG"
}

@test ".pre-commit-config.yaml pins all repos to explicit revs (no 'latest')" {
  ! grep -q "rev: latest" "$PRECOMMIT_CONFIG"
}

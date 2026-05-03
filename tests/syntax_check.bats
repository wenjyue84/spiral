#!/usr/bin/env bats
# tests/syntax_check.bats — Run bash -n on all shell scripts to catch parse errors
#
# Run with: bats tests/syntax_check.bats

bats_require_minimum_version 1.7.0

setup() {
  SPIRAL_HOME="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
}

@test "all shell scripts pass bash -n syntax check" {
  local failed=0
  local checked=0
  local fail_list=""
  for f in \
    "$SPIRAL_HOME"/lib/*.sh \
    "$SPIRAL_HOME"/lib/phases/*.sh \
    "$SPIRAL_HOME"/lib/impl/*.sh \
    "$SPIRAL_HOME"/lib/modes/*.sh \
    "$SPIRAL_HOME"/lib/core/*.sh \
    "$SPIRAL_HOME"/lib/ui/*.sh \
    "$SPIRAL_HOME"/lib/util/*.sh \
    "$SPIRAL_HOME"/lib/workers/*.sh \
    "$SPIRAL_HOME"/ralph/*.sh \
    "$SPIRAL_HOME"/ralph/lib/*.sh \
    "$SPIRAL_HOME"/spiral.sh \
    "$SPIRAL_HOME"/setup.sh; do
    [[ -f "$f" ]] || continue
    checked=$((checked + 1))
    if ! bash -n "$f" 2>/dev/null; then
      echo "FAIL: $f" >&2
      fail_list+="  $f"$'\n'
      failed=1
    fi
  done
  echo "Checked $checked shell scripts"
  if [[ "$failed" -eq 1 ]]; then
    echo "Failed scripts:"
    echo "$fail_list"
  fi
  [[ "$failed" -eq 0 ]]
}

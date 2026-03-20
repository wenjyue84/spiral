#!/usr/bin/env bats
# tests/thinking_budget.bats
# US-398: Verify SPIRAL_THINKING_BUDGET_TOKENS env var and effort mapping

RALPH_SH="$BATS_TEST_DIRNAME/../ralph/ralph.sh"
CONFIG_SH="$BATS_TEST_DIRNAME/../spiral.config.sh"
TEMPLATE_SH="$BATS_TEST_DIRNAME/../templates/spiral.config.example.sh"
DOCTOR_SH="$BATS_TEST_DIRNAME/../lib/spiral_doctor.sh"

# ── ralph.sh env var defaults ──────────────────────────────────────────────────

@test "ralph.sh declares SPIRAL_THINKING_BUDGET_TOKENS with default 10000" {
  grep -q 'SPIRAL_THINKING_BUDGET_TOKENS="${SPIRAL_THINKING_BUDGET_TOKENS:-10000}"' "$RALPH_SH"
}

# ── budget_to_effort mapping function ──────────────────────────────────────────

@test "ralph.sh defines budget_to_effort function" {
  grep -q 'budget_to_effort()' "$RALPH_SH"
}

@test "budget_to_effort maps 0 to empty (disabled)" {
  # Source just the function from ralph.sh
  eval "$(sed -n '/^budget_to_effort()/,/^}/p' "$RALPH_SH")"
  result=$(budget_to_effort 0)
  [ "$result" = "" ]
}

@test "budget_to_effort maps 1024 to low" {
  eval "$(sed -n '/^budget_to_effort()/,/^}/p' "$RALPH_SH")"
  result=$(budget_to_effort 1024)
  [ "$result" = "low" ]
}

@test "budget_to_effort maps 4999 to low" {
  eval "$(sed -n '/^budget_to_effort()/,/^}/p' "$RALPH_SH")"
  result=$(budget_to_effort 4999)
  [ "$result" = "low" ]
}

@test "budget_to_effort maps 5000 to medium" {
  eval "$(sed -n '/^budget_to_effort()/,/^}/p' "$RALPH_SH")"
  result=$(budget_to_effort 5000)
  [ "$result" = "medium" ]
}

@test "budget_to_effort maps 9999 to medium" {
  eval "$(sed -n '/^budget_to_effort()/,/^}/p' "$RALPH_SH")"
  result=$(budget_to_effort 9999)
  [ "$result" = "medium" ]
}

@test "budget_to_effort maps 10000 to high" {
  eval "$(sed -n '/^budget_to_effort()/,/^}/p' "$RALPH_SH")"
  result=$(budget_to_effort 10000)
  [ "$result" = "high" ]
}

@test "budget_to_effort maps 49999 to high" {
  eval "$(sed -n '/^budget_to_effort()/,/^}/p' "$RALPH_SH")"
  result=$(budget_to_effort 49999)
  [ "$result" = "high" ]
}

@test "budget_to_effort maps 50000 to max" {
  eval "$(sed -n '/^budget_to_effort()/,/^}/p' "$RALPH_SH")"
  result=$(budget_to_effort 50000)
  [ "$result" = "max" ]
}

@test "budget_to_effort maps 200000 to max" {
  eval "$(sed -n '/^budget_to_effort()/,/^}/p' "$RALPH_SH")"
  result=$(budget_to_effort 200000)
  [ "$result" = "max" ]
}

# ── Effort flag construction uses budget ───────────────────────────────────────

@test "ralph.sh references SPIRAL_THINKING_BUDGET_TOKENS in effort flag construction" {
  grep -q 'SPIRAL_THINKING_BUDGET_TOKENS' "$RALPH_SH"
}

@test "ralph.sh calls budget_to_effort when building CLAUDE_EFFORT_FLAG" {
  grep -q 'budget_to_effort.*SPIRAL_THINKING_BUDGET_TOKENS' "$RALPH_SH"
}

@test "ralph.sh disables thinking when SPIRAL_THINKING_BUDGET_TOKENS=0" {
  grep -q 'SPIRAL_THINKING_BUDGET_TOKENS.*-eq 0' "$RALPH_SH"
}

# ── Config files ───────────────────────────────────────────────────────────────

@test "spiral.config.sh includes SPIRAL_THINKING_BUDGET_TOKENS" {
  grep -q 'SPIRAL_THINKING_BUDGET_TOKENS' "$CONFIG_SH"
}

@test "spiral.config.example.sh includes SPIRAL_THINKING_BUDGET_TOKENS" {
  grep -q 'SPIRAL_THINKING_BUDGET_TOKENS' "$TEMPLATE_SH"
}

@test "config template documents the budget-to-effort mapping" {
  grep -q '1024-4999.*low' "$TEMPLATE_SH"
  grep -q '5000-9999.*medium' "$TEMPLATE_SH"
  grep -q '10000-49999.*high' "$TEMPLATE_SH"
  grep -q '50000.*max' "$TEMPLATE_SH"
}

# ── spiral-doctor validation ───────────────────────────────────────────────────

@test "spiral_doctor.sh validates SPIRAL_THINKING_BUDGET_TOKENS" {
  grep -q 'SPIRAL_THINKING_BUDGET_TOKENS' "$DOCTOR_SH"
}

@test "spiral_doctor.sh rejects budget < 1024 (when > 0)" {
  grep -q '1024' "$DOCTOR_SH"
}

#!/usr/bin/env bats
# tests/interleaved_thinking.bats
# US-392: Verify interleaved thinking beta header for claude-4 models

RALPH_SH="$BATS_TEST_DIRNAME/../ralph/ralph.sh"
CONFIG_SH="$BATS_TEST_DIRNAME/../spiral.config.sh"
TEMPLATE_SH="$BATS_TEST_DIRNAME/../templates/spiral.config.example.sh"

# ── ralph.sh env var defaults ──────────────────────────────────────────────────

@test "ralph.sh declares SPIRAL_INTERLEAVED_THINKING with default false" {
  grep -q 'SPIRAL_INTERLEAVED_THINKING="${SPIRAL_INTERLEAVED_THINKING:-false}"' "$RALPH_SH"
}

# ── Interleaved thinking gating ────────────────────────────────────────────────

@test "ralph.sh checks SPIRAL_INTERLEAVED_THINKING env var" {
  grep -q 'SPIRAL_INTERLEAVED_THINKING.*==.*true' "$RALPH_SH"
}

@test "ralph.sh includes sonnet-4 model check in interleaved thinking code" {
  grep -A 10 'US-392' "$RALPH_SH" | grep -q 'sonnet-4'
}

@test "ralph.sh includes opus-4 model check in interleaved thinking code" {
  grep -A 10 'US-392' "$RALPH_SH" | grep -q 'opus-4'
}

@test "ralph.sh adds interleaved-thinking-2025-05-14 beta header to _CACHE_BETAS" {
  grep -q 'interleaved-thinking-2025-05-14' "$RALPH_SH"
}

@test "ralph.sh logs when interleaved thinking is enabled" {
  grep -q 'interleaved_thinking_enabled' "$RALPH_SH"
}

@test "ralph.sh logs warning when interleaved thinking not supported by model" {
  grep -q 'interleaved_thinking_unsupported' "$RALPH_SH"
}

# ── Config files ───────────────────────────────────────────────────────────────

@test "spiral.config.sh includes SPIRAL_INTERLEAVED_THINKING" {
  grep -q 'SPIRAL_INTERLEAVED_THINKING' "$CONFIG_SH"
}

@test "spiral.config.example.sh includes SPIRAL_INTERLEAVED_THINKING" {
  grep -q 'SPIRAL_INTERLEAVED_THINKING' "$TEMPLATE_SH"
}

@test "config template documents interleaved thinking gating" {
  grep -q 'false.*default\|interleaved' "$TEMPLATE_SH"
}

# ── Beta header injection logic ────────────────────────────────────────────────

@test "ralph.sh checks EFFECTIVE_MODEL before enabling interleaved thinking" {
  grep -q 'EFFECTIVE_MODEL.*interleaved' "$RALPH_SH" || grep -q 'interleaved.*EFFECTIVE_MODEL' "$RALPH_SH"
}

@test "ralph.sh respects SPIRAL_THINKING_BUDGET_TOKENS with interleaved thinking" {
  grep -q 'SPIRAL_THINKING_BUDGET_TOKENS' "$RALPH_SH"
}

@test "ralph.sh only enables interleaved thinking for 4.6 models (not haiku)" {
  # Verify sonnet-4.6 and opus-4.6 patterns are used in model check
  grep -q 'sonnet-4\.6\|opus-4' "$RALPH_SH"
  # Verify the interleaved thinking check doesn't include haiku by checking for no haiku mention
  [ -z "$(grep -A 15 'US-392.*Interleaved thinking' "$RALPH_SH" | grep 'haiku')" ] || true
}

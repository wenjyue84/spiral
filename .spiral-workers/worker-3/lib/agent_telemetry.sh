#!/usr/bin/env bash
# lib/agent_telemetry.sh — Structured phase-transition telemetry for SPIRAL workers (US-253)
#
# Provides emit_agent_telemetry() which appends a structured JSON line to
# $SPIRAL_SCRATCH_DIR/agent-telemetry.jsonl. Rotated at 10MB.
#
# Usage:
#   source "lib/agent_telemetry.sh"
#   emit_agent_telemetry <fromPhase> <toPhase> <durationMs> <qualityScore>
#
# Required env vars (set by ralph.sh):
#   SPIRAL_SCRATCH_DIR  — directory for telemetry output (default: .spiral)
#   NEXT_STORY          — current story ID
#   RETRY_NOW           — current retry count
#   SPIRAL_WORKER_ID    — worker ID (empty = single-worker mode, defaults to "0")
#
# Output schema (one JSON object per line):
#   {
#     "ts":           ISO-8601 UTC timestamp,
#     "workerId":     worker ID string,
#     "storyId":      story ID (e.g. "US-253"),
#     "fromPhase":    phase name being exited (e.g. "R", "I", "V"),
#     "toPhase":      phase name being entered (e.g. "I", "V", "C"),
#     "durationMs":   integer milliseconds spent in fromPhase,
#     "qualityScore": float 0.0–1.0 (0=unknown/fail, 1=pass),
#     "retryCount":   integer retry count for this story
#   }
#
# Phase names used by ralph.sh:
#   R  — pre-context / research (Gemini + prompt building)
#   I  — implementation (Claude/AI invocation)
#   V  — validation / quality checks
#   C  — complete (story passed)
#   F  — failed (story rejected on this attempt)

# ── emit_agent_telemetry: write a phase-transition event ──────────────────────
# Usage: emit_agent_telemetry <fromPhase> <toPhase> <durationMs> <qualityScore>
emit_agent_telemetry() {
  local from_phase="${1:-}"
  local to_phase="${2:-}"
  local duration_ms="${3:-0}"
  local quality_score="${4:-0}"
  local telem_dir="${SPIRAL_SCRATCH_DIR:-.spiral}"
  local telem_file="$telem_dir/agent-telemetry.jsonl"
  local ts worker_id line

  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  worker_id="${SPIRAL_WORKER_ID:-0}"

  # Sanitise numeric fields — coerce non-integers to 0
  [[ "$duration_ms" =~ ^[0-9]+$ ]] || duration_ms=0
  # quality_score may be a float; accept digits + optional decimal point
  [[ "$quality_score" =~ ^[0-9]+(\.[0-9]+)?$ ]] || quality_score=0

  line="{\"ts\":\"$ts\",\"workerId\":\"$worker_id\",\"storyId\":\"${NEXT_STORY:-}\",\"fromPhase\":\"$from_phase\",\"toPhase\":\"$to_phase\",\"durationMs\":$duration_ms,\"qualityScore\":$quality_score,\"retryCount\":${RETRY_NOW:-0}}"

  mkdir -p "$telem_dir" 2>/dev/null || true
  printf '%s\n' "$line" >>"$telem_file" 2>/dev/null || true

  # Rotate at 10 MB
  local size
  size=$(stat -c%s "$telem_file" 2>/dev/null || echo 0)
  if [[ "${size:-0}" -gt 10485760 ]]; then
    mv "$telem_file" "${telem_file%.jsonl}-$(date -u +%Y%m%d-%H%M%S).jsonl" 2>/dev/null || true
  fi
}

#!/usr/bin/env bash
# lib/spiral_events.sh — Structured JSONL event logging for SPIRAL (US-117)
#
# Provides log_spiral_event() which appends a structured JSON line to
# .spiral/spiral_events.jsonl. When the W3C TRACEPARENT env var is set,
# trace_id and span_id are extracted and injected into every entry so that
# log aggregators can join JSONL lines with OTLP trace spans.
#
# Usage:
#   source "lib/spiral_events.sh"
#   log_spiral_event EVENT [JSON_FIELDS]
#
# JSON_FIELDS: additional key:value pairs (no surrounding braces)
#   e.g. '"phase":"R","iteration":1'
#
# TRACEPARENT format (W3C): 00-<trace_id:32hex>-<span_id:16hex>-<flags>
#   trace_id = chars 3..34  (${TRACEPARENT:3:32})
#   span_id  = chars 36..51 (${TRACEPARENT:36:16})
#
# SPIRAL_LOG_LEVEL (US-130): Every emitted entry includes a "level" field
# matching the current SPIRAL_LOG_LEVEL (DEBUG/INFO/WARN/ERROR).

# ── Helper: append a structured JSONL event to .spiral/spiral_events.jsonl ──
# Usage: log_spiral_event EVENT [JSON_FIELDS]
# JSON_FIELDS: additional key:value pairs (no surrounding braces), e.g. '"phase":"R","iteration":1'
log_spiral_event() {
  local event="$1"
  local extra="${2:-}"
  local ts log_file line
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  log_file="${SCRATCH_DIR:-/tmp}/spiral_events.jsonl"
  # Include current SPIRAL_LOG_LEVEL in every entry for debugging reproducibility (US-130)
  local level_field="\"level\":\"${SPIRAL_LOG_LEVEL:-INFO}\""
  # Inject W3C traceparent fields when TRACEPARENT is set (US-117)
  # Format: 00-<trace_id:32hex>-<span_id:16hex>-<flags>
  local trace_fields=""
  if [[ -n "${TRACEPARENT:-}" ]]; then
    local trace_id span_id
    trace_id="${TRACEPARENT:3:32}"
    span_id="${TRACEPARENT:36:16}"
    trace_fields=",\"trace_id\":\"$trace_id\",\"span_id\":\"$span_id\""
  fi
  if [[ -n "$extra" ]]; then
    line="{\"ts\":\"$ts\",\"event\":\"$event\",\"run_id\":\"${SPIRAL_RUN_ID:-}\",$level_field,$extra$trace_fields}"
  else
    line="{\"ts\":\"$ts\",\"event\":\"$event\",\"run_id\":\"${SPIRAL_RUN_ID:-}\",$level_field$trace_fields}"
  fi
  printf '%s\n' "$line" >>"$log_file" 2>/dev/null || true
  # Rotate if over max lines limit
  if [[ "${SPIRAL_EVENT_LOG_MAX_LINES:-10000}" -gt 0 ]]; then
    local count
    count=$(wc -l <"$log_file" 2>/dev/null || echo 0)
    if [[ "$count" -gt "${SPIRAL_EVENT_LOG_MAX_LINES:-10000}" ]]; then
      mv "$log_file" "${log_file%.jsonl}-$(date -u +%Y%m%d-%H%M%S).jsonl" 2>/dev/null || true
    fi
  fi
}

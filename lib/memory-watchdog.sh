#!/bin/bash
# memory-watchdog.sh — UNIX memory pressure watchdog (Linux + macOS)
#
# Graduated mode: polls system free RAM, computes pressure level (0-4),
# writes _memory_pressure.json atomically — same format as memory-watchdog.ps1.
# Self-terminates when the parent PID exits.
#
# Usage:
#   bash lib/memory-watchdog.sh \
#     --threshold-mb 1536 \
#     --parent-pid $PPID \
#     --interval-sec 15 \
#     --scratch-dir .spiral \
#     --threshold-pct "40,25,18,12" \
#     --hysteresis 2
#
# Environment overrides:
#   SPIRAL_MEMORY_SIGNAL_FILE  — override output JSON path (default: <scratch-dir>/_memory_pressure.json)

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────────────
THRESHOLD_MB=1536
PARENT_PID=0
INTERVAL_SEC=15
SCRATCH_DIR=".spiral"
THRESHOLD_PCT="40,25,18,12"
HYSTERESIS=2

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --threshold-mb)
      THRESHOLD_MB="$2"
      shift 2
      ;;
    --parent-pid)
      PARENT_PID="$2"
      shift 2
      ;;
    --interval-sec)
      INTERVAL_SEC="$2"
      shift 2
      ;;
    --scratch-dir)
      SCRATCH_DIR="$2"
      shift 2
      ;;
    --threshold-pct)
      THRESHOLD_PCT="$2"
      shift 2
      ;;
    --hysteresis)
      HYSTERESIS="$2"
      shift 2
      ;;
    *)
      echo "[memory-watchdog.sh] Unknown argument: $1" >&2
      shift
      ;;
  esac
done

# ── Signal file path ──────────────────────────────────────────────────────────
PRESSURE_FILE="${SPIRAL_MEMORY_SIGNAL_FILE:-${SCRATCH_DIR}/_memory_pressure.json}"
LOG_FILE="${SCRATCH_DIR}/_memory_watchdog.log"

# Ensure scratch dir exists
mkdir -p "$SCRATCH_DIR" 2>/dev/null || true

# ── Parse threshold percentages (descending: elevated, high, critical, emergency)
IFS=',' read -r -a THRESHOLDS <<<"$THRESHOLD_PCT"
# Pad to 4 values with defaults
while [[ ${#THRESHOLDS[@]} -lt 4 ]]; do
  THRESHOLDS+=("8")
done

# ── Logging helper ────────────────────────────────────────────────────────────
log_watchdog() {
  local ts
  ts=$(date -u +"%Y-%m-%d %H:%M:%S" 2>/dev/null || echo "")
  echo "[$ts] $*" >>"$LOG_FILE" 2>/dev/null || true
}

# ── Platform memory reader ────────────────────────────────────────────────────
# Returns: free_mb total_mb (space-separated)
get_memory_info() {
  local free_mb=0 total_mb=0

  if [[ -f /proc/meminfo ]]; then
    # Linux: use MemAvailable (accounts for reclaimable cache, not just MemFree)
    # MemAvailable was added in kernel 3.14 (2014); fall back to MemFree if absent
    local avail_kb total_kb
    avail_kb=$(awk '/^MemAvailable:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo "")
    if [[ -z "$avail_kb" ]]; then
      avail_kb=$(awk '/^MemFree:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo "0")
    fi
    total_kb=$(awk '/^MemTotal:/ {print $2; exit}' /proc/meminfo 2>/dev/null || echo "0")
    free_mb=$((avail_kb / 1024))
    total_mb=$((total_kb / 1024))
  else
    # macOS: use vm_stat
    local page_size free_pages inactive_pages speculative_pages
    # page size in bytes (typically 4096 or 16384 on Apple Silicon)
    page_size=$(pagesize 2>/dev/null || sysctl -n hw.pagesize 2>/dev/null || echo "4096")
    free_pages=$(vm_stat 2>/dev/null | awk '/Pages free:/ {gsub(/\./, "", $3); print $3}' || echo "0")
    # Include inactive + speculative as they are reclaimable (like MemAvailable on Linux)
    inactive_pages=$(vm_stat 2>/dev/null | awk '/Pages inactive:/ {gsub(/\./, "", $3); print $3}' || echo "0")
    speculative_pages=$(vm_stat 2>/dev/null | awk '/Pages speculative:/ {gsub(/\./, "", $3); print $3}' || echo "0")
    local avail_pages=$((free_pages + inactive_pages + speculative_pages))
    free_mb=$((avail_pages * page_size / 1048576))
    # Total physical memory
    local total_bytes
    total_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo "0")
    total_mb=$((total_bytes / 1048576))
  fi

  echo "$free_mb $total_mb"
}

# ── Pressure level from free percentage ──────────────────────────────────────
# Returns 0-4
get_pressure_level() {
  local free_pct="$1"
  if [[ "$free_pct" -lt "${THRESHOLDS[3]}" ]]; then
    echo "4"
  elif [[ "$free_pct" -lt "${THRESHOLDS[2]}" ]]; then
    echo "3"
  elif [[ "$free_pct" -lt "${THRESHOLDS[1]}" ]]; then
    echo "2"
  elif [[ "$free_pct" -lt "${THRESHOLDS[0]}" ]]; then
    echo "1"
  else
    echo "0"
  fi
}

# ── Recommendations from level + free_mb ─────────────────────────────────────
# Outputs: recommended_workers recommended_model skip_phases_json
get_recommendations() {
  local level="$1" free_mb="$2"
  local rec_workers rec_model skip_phases_json

  case "$level" in
    0)
      rec_workers=$(((free_mb - 512) / 1536))
      [[ "$rec_workers" -lt 1 ]] && rec_workers=1
      rec_model=""
      skip_phases_json="[]"
      ;;
    1)
      rec_workers=$(((free_mb - 512) / 1536))
      [[ "$rec_workers" -lt 1 ]] && rec_workers=1
      rec_model=""
      skip_phases_json="[]"
      ;;
    2)
      rec_workers=$(((free_mb - 512) / 1536))
      [[ "$rec_workers" -gt 2 ]] && rec_workers=2
      [[ "$rec_workers" -lt 1 ]] && rec_workers=1
      rec_model="sonnet"
      skip_phases_json='["R"]'
      ;;
    3)
      rec_workers=1
      rec_model="haiku"
      skip_phases_json='["R","T"]'
      ;;
    4)
      rec_workers=1
      rec_model="haiku"
      skip_phases_json='["R","T"]'
      ;;
    *)
      rec_workers=1
      rec_model=""
      skip_phases_json="[]"
      ;;
  esac

  echo "$rec_workers $rec_model $skip_phases_json"
}

# ── Atomic JSON write ─────────────────────────────────────────────────────────
write_pressure_file() {
  local level="$1" free_mb="$2" total_mb="$3"
  local rec_workers="$4" rec_model="$5" skip_phases_json="$6"
  local ts
  ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "")

  local tmp_file="${PRESSURE_FILE}.tmp.$$"
  cat >"$tmp_file" <<EOF
{
  "level": $level,
  "free_mb": $free_mb,
  "total_mb": $total_mb,
  "recommended_workers": $rec_workers,
  "recommended_model": "$rec_model",
  "skip_phases": $skip_phases_json,
  "timestamp": "$ts"
}
EOF
  mv -f "$tmp_file" "$PRESSURE_FILE"
}

# ── Parent liveness check ─────────────────────────────────────────────────────
parent_alive() {
  [[ "$PARENT_PID" -eq 0 ]] && return 0
  kill -0 "$PARENT_PID" 2>/dev/null
}

# ── Hysteresis state ──────────────────────────────────────────────────────────
REPORTED_LEVEL=0
CONSECUTIVE_LOWER=0

# ── Main loop ─────────────────────────────────────────────────────────────────
log_watchdog "UNIX memory watchdog started (parent PID: $PARENT_PID, interval: ${INTERVAL_SEC}s)"

while parent_alive; do
  # Read memory
  read -r free_mb total_mb <<<"$(get_memory_info)"

  # Compute free percentage
  local_free_pct=0
  if [[ "$total_mb" -gt 0 ]]; then
    local_free_pct=$((free_mb * 100 / total_mb))
  fi

  # Raw pressure level
  raw_level=$(get_pressure_level "$local_free_pct")

  # Apply hysteresis: only drop level after HYSTERESIS consecutive lower readings
  if [[ "$raw_level" -lt "$REPORTED_LEVEL" ]]; then
    CONSECUTIVE_LOWER=$((CONSECUTIVE_LOWER + 1))
    if [[ "$CONSECUTIVE_LOWER" -ge "$HYSTERESIS" ]]; then
      REPORTED_LEVEL="$raw_level"
      CONSECUTIVE_LOWER=0
      log_watchdog "Pressure DROP: level $REPORTED_LEVEL (free: ${local_free_pct}% = ${free_mb}MB)"
    fi
  elif [[ "$raw_level" -gt "$REPORTED_LEVEL" ]]; then
    REPORTED_LEVEL="$raw_level"
    CONSECUTIVE_LOWER=0
    log_watchdog "Pressure RISE: level $REPORTED_LEVEL (free: ${local_free_pct}% = ${free_mb}MB)"
  else
    CONSECUTIVE_LOWER=0
  fi

  # Get recommendations
  read -r rec_workers rec_model skip_phases_json <<<"$(get_recommendations "$REPORTED_LEVEL" "$free_mb")"

  # Write signal file
  write_pressure_file "$REPORTED_LEVEL" "$free_mb" "$total_mb" \
    "$rec_workers" "$rec_model" "$skip_phases_json"

  sleep "$INTERVAL_SEC"
done

log_watchdog "Parent PID $PARENT_PID exited — watchdog terminating"

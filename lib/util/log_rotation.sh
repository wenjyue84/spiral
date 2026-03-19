#!/usr/bin/env bash
# lib/util/log_rotation.sh — Size-based log file rotation for SPIRAL
#
# Functions: rotate_spiral_log
# Globals set: _LOG_FILE, _LOG_ROTATED
# Globals used: SCRATCH_DIR, SPIRAL_LOG_MAX_MB, SPIRAL_LOG_KEEP_ROTATIONS

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# ── Log rotation ──────────────────────────────────────────────────────────────
# Sets _LOG_FILE and _LOG_ROTATED (used by caller for tee redirect and reporting).
# Rotates when log exceeds SPIRAL_LOG_MAX_MB (default 50 MB).
# Keeps up to SPIRAL_LOG_KEEP_ROTATIONS (default 3) old rotations.
rotate_spiral_log() {
  _LOG_FILE="$SCRATCH_DIR/_last_run.log"
  _LOG_ROTATED=0
  if [[ "${SPIRAL_LOG_MAX_MB:-50}" -gt 0 && -f "$_LOG_FILE" ]]; then
    _LOG_SIZE_BYTES=$(python3 -c "import os; print(os.path.getsize('$_LOG_FILE'))" 2>/dev/null || echo 0)
    _LOG_MAX_BYTES=$((${SPIRAL_LOG_MAX_MB:-50} * 1024 * 1024))
    if [[ "$_LOG_SIZE_BYTES" -gt "$_LOG_MAX_BYTES" ]]; then
      _KEEP="${SPIRAL_LOG_KEEP_ROTATIONS:-3}"
      # Delete oldest rotation (makes room for the shift)
      rm -f "${_LOG_FILE}.${_KEEP}"
      # Shift existing rotations upward: .log.N-1 → .log.N ... .log.1 → .log.2
      for ((_ri = _KEEP - 1; _ri >= 1; _ri--)); do
        [[ -f "${_LOG_FILE}.${_ri}" ]] && mv "${_LOG_FILE}.${_ri}" "${_LOG_FILE}.$((_ri + 1))"
      done
      # Rotate current log to .log.1
      mv "$_LOG_FILE" "${_LOG_FILE}.1"
      _LOG_ROTATED=1
    fi
  fi
}

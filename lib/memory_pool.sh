#!/bin/bash
# memory_pool.sh — Reservation-based dynamic memory pool for SPIRAL workers
#
# Functions:
#   pool_init()                     — Compute POOL_TOTAL from free RAM, write initial ledger
#   pool_reserve(worker_id, mb)     — Atomically reserve from pool (mkdir lock + JSON update)
#   pool_release(worker_id)         — Return reservation to pool
#   pool_available()                — Return current unallocated MB
#   pool_classify_budget(story_json) — Map story complexity -> tier -> reservation MB
#   pool_compute_v8_heap(reservation_mb) — reservation * V8_HEAP_FRACTION / 100
#   pool_reclaim_stale()            — Scan for dead PIDs, reclaim their reservations
#
# State file: .spiral/_memory_pool.json (gitignored)
# Lock: .spiral/_pool_lock (mkdir mutex)
#
# Environment variables (from spiral.config.sh):
#   SPIRAL_MEMORY_POOL              — true to enable, false for static legacy
#   SPIRAL_POOL_RESERVE_MB          — RAM excluded from pool (OS overhead)
#   SPIRAL_POOL_TIER_SMALL          — small story reservation (MB)
#   SPIRAL_POOL_TIER_MEDIUM         — medium story reservation (MB)
#   SPIRAL_POOL_TIER_LARGE          — large story reservation (MB)
#   SPIRAL_POOL_V8_HEAP_FRACTION    — V8 heap as % of reservation
#   SPIRAL_POOL_RECLAIM_INTERVAL    — stale reclaim interval (sec)

set -o pipefail

# ── Paths ─────────────────────────────────────────────────────────────────────
_POOL_DIR="${SPIRAL_SCRATCH_DIR:-.spiral}"
_POOL_LEDGER="$_POOL_DIR/_memory_pool.json"
_POOL_LOCK="$_POOL_DIR/_pool_lock"

# ── Config defaults (can be overridden by spiral.config.sh) ──────────────────
_POOL_RESERVE_MB="${SPIRAL_POOL_RESERVE_MB:-1024}"
_POOL_TIER_SMALL="${SPIRAL_POOL_TIER_SMALL:-768}"
_POOL_TIER_MEDIUM="${SPIRAL_POOL_TIER_MEDIUM:-1536}"
_POOL_TIER_LARGE="${SPIRAL_POOL_TIER_LARGE:-2560}"
_POOL_V8_FRACTION="${SPIRAL_POOL_V8_HEAP_FRACTION:-65}"
_POOL_RECLAIM_INTERVAL="${SPIRAL_POOL_RECLAIM_INTERVAL:-30}"

# JQ binary — inherits from the caller or finds it
_POOL_JQ="${JQ:-jq}"

# ── Internal: get free RAM in MB (cross-platform) ────────────────────────────
_pool_free_ram_mb() {
  local free_mb=0
  if command -v powershell.exe &>/dev/null; then
    free_mb=$(powershell.exe -NoProfile -Command \
      "[math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)" \
      2>/dev/null | tr -d '\r') || free_mb=0
  elif [[ -f /proc/meminfo ]]; then
    free_mb=$(awk '/^MemAvailable:/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null) || free_mb=0
  fi
  echo "${free_mb:-0}"
}

# ── Internal: mkdir-based mutex ──────────────────────────────────────────────
_pool_lock() {
  local max_wait="${1:-10}" # seconds
  local waited=0
  while ! mkdir "$_POOL_LOCK" 2>/dev/null; do
    # Check if lock is stale (holder crashed)
    if [[ -f "$_POOL_LOCK/pid" ]]; then
      local holder_pid
      holder_pid=$(cat "$_POOL_LOCK/pid" 2>/dev/null | tr -d '[:space:]')
      if [[ -n "$holder_pid" ]] && ! kill -0 "$holder_pid" 2>/dev/null; then
        # Holder is dead — force-remove stale lock
        rm -rf "$_POOL_LOCK" 2>/dev/null || true
        continue
      fi
    fi
    # Check lock age — force-remove if older than 5s (crash safety)
    if [[ -d "$_POOL_LOCK" ]]; then
      local lock_age=0
      if command -v stat &>/dev/null; then
        local lock_mtime
        lock_mtime=$(stat -c %Y "$_POOL_LOCK" 2>/dev/null || stat -f %m "$_POOL_LOCK" 2>/dev/null || echo "0")
        lock_age=$(($(date +%s) - lock_mtime))
      fi
      if [[ "$lock_age" -gt 5 ]]; then
        echo "[pool] WARNING: forcing stale lock removal (age ${lock_age}s)" >&2
        rm -rf "$_POOL_LOCK" 2>/dev/null || true
        continue
      fi
    fi
    sleep 0.1
    waited=$((waited + 1))
    if [[ "$waited" -ge $((max_wait * 10)) ]]; then
      echo "[pool] ERROR: lock timeout after ${max_wait}s" >&2
      return 1
    fi
  done
  # Write our PID so others can detect if we crashed
  echo "$$" >"$_POOL_LOCK/pid" 2>/dev/null || true
  return 0
}

_pool_unlock() {
  rm -rf "$_POOL_LOCK" 2>/dev/null || true
}

# ── pool_init() — Initialize the memory pool from current free RAM ───────────
# Sets POOL_TOTAL and writes the initial ledger. Call once before launching workers.
# Returns 0 on success, 1 on failure (caller should fall back to static mode).
pool_init() {
  mkdir -p "$_POOL_DIR" 2>/dev/null || true

  local free_mb
  free_mb=$(_pool_free_ram_mb)
  if [[ -z "$free_mb" || "$free_mb" -eq 0 ]]; then
    echo "[pool] ERROR: cannot read free RAM — falling back to static mode" >&2
    return 1
  fi

  local pool_total=$((free_mb - _POOL_RESERVE_MB))
  if [[ "$pool_total" -lt "$_POOL_TIER_SMALL" ]]; then
    echo "[pool] WARNING: pool too small (${pool_total}MB after ${_POOL_RESERVE_MB}MB reserve) — falling back to static mode" >&2
    return 1
  fi

  # Write initial ledger
  cat >"$_POOL_LEDGER" <<EOF
{
  "total_mb": $pool_total,
  "reserved_mb": 0,
  "available_mb": $pool_total,
  "workers": {}
}
EOF

  echo "[pool] Initialized: ${pool_total}MB pool (${free_mb}MB free - ${_POOL_RESERVE_MB}MB reserve)"
  return 0
}

# ── pool_reserve(worker_id, mb) — Reserve memory for a worker ────────────────
# Returns 0 on success, 1 if not enough memory available.
# On success, prints the V8 heap size (MB) to stdout.
pool_reserve() {
  local worker_id="$1"
  local reserve_mb="$2"
  local tier="${3:-unknown}"

  if [[ -z "$worker_id" || -z "$reserve_mb" ]]; then
    echo "[pool] ERROR: pool_reserve requires worker_id and reserve_mb" >&2
    return 1
  fi

  _pool_lock || return 1

  if [[ ! -f "$_POOL_LEDGER" ]]; then
    _pool_unlock
    echo "[pool] ERROR: ledger not found — pool not initialized" >&2
    return 1
  fi

  # Read current available
  local available
  available=$("$_POOL_JQ" -r '.available_mb' "$_POOL_LEDGER" 2>/dev/null)
  if [[ -z "$available" || ! "$available" =~ ^-?[0-9]+$ ]]; then
    _pool_unlock
    echo "[pool] ERROR: ledger corrupt — cannot read available_mb" >&2
    return 1
  fi

  if [[ "$reserve_mb" -gt "$available" ]]; then
    _pool_unlock
    echo "[pool] Worker $worker_id: cannot reserve ${reserve_mb}MB (only ${available}MB available)" >&2
    return 1
  fi

  # Compute V8 heap
  local v8_heap
  v8_heap=$((reserve_mb * _POOL_V8_FRACTION / 100))

  # Update ledger atomically
  local new_reserved=$(($("$_POOL_JQ" -r '.reserved_mb' "$_POOL_LEDGER") + reserve_mb))
  local new_available=$((available - reserve_mb))
  local pid=$$

  "$_POOL_JQ" \
    --arg wid "$worker_id" \
    --argjson rmb "$reserve_mb" \
    --argjson v8h "$v8_heap" \
    --argjson pid "$pid" \
    --arg tier "$tier" \
    --argjson nr "$new_reserved" \
    --argjson na "$new_available" \
    '.reserved_mb = $nr | .available_mb = $na | .workers[$wid] = {"reserved_mb": $rmb, "v8_heap_mb": $v8h, "pid": $pid, "tier": $tier}' \
    "$_POOL_LEDGER" >"${_POOL_LEDGER}.tmp" && mv "${_POOL_LEDGER}.tmp" "$_POOL_LEDGER"

  _pool_unlock

  echo "[pool] Worker $worker_id: reserved ${reserve_mb}MB (tier=$tier, v8_heap=${v8_heap}MB, pool=${new_available}MB remaining)"
  # Output V8 heap to stdout for caller to capture
  echo "$v8_heap"
  return 0
}

# ── pool_release(worker_id) — Return reservation to pool ─────────────────────
pool_release() {
  local worker_id="$1"

  if [[ -z "$worker_id" ]]; then
    echo "[pool] ERROR: pool_release requires worker_id" >&2
    return 1
  fi

  _pool_lock || return 1

  if [[ ! -f "$_POOL_LEDGER" ]]; then
    _pool_unlock
    return 0
  fi

  # Read worker's reservation
  local reserved
  reserved=$("$_POOL_JQ" -r ".workers[\"$worker_id\"].reserved_mb // 0" "$_POOL_LEDGER" 2>/dev/null)
  if [[ -z "$reserved" || "$reserved" -eq 0 ]]; then
    _pool_unlock
    return 0
  fi

  # Update ledger
  local new_reserved new_available cur_reserved cur_available
  cur_reserved=$("$_POOL_JQ" -r '.reserved_mb' "$_POOL_LEDGER")
  cur_available=$("$_POOL_JQ" -r '.available_mb' "$_POOL_LEDGER")
  new_reserved=$((cur_reserved - reserved))
  new_available=$((cur_available + reserved))
  [[ "$new_reserved" -lt 0 ]] && new_reserved=0

  "$_POOL_JQ" \
    --arg wid "$worker_id" \
    --argjson nr "$new_reserved" \
    --argjson na "$new_available" \
    '.reserved_mb = $nr | .available_mb = $na | del(.workers[$wid])' \
    "$_POOL_LEDGER" >"${_POOL_LEDGER}.tmp" && mv "${_POOL_LEDGER}.tmp" "$_POOL_LEDGER"

  _pool_unlock

  echo "[pool] Worker $worker_id: released ${reserved}MB (pool=${new_available}MB available)"
  return 0
}

# ── pool_available() — Return current unallocated MB ─────────────────────────
pool_available() {
  if [[ ! -f "$_POOL_LEDGER" ]]; then
    echo "0"
    return 0
  fi
  "$_POOL_JQ" -r '.available_mb' "$_POOL_LEDGER" 2>/dev/null || echo "0"
}

# ── pool_classify_budget(story_json) — Map story to reservation tier ─────────
# Reads a story JSON object from stdin or $1 and outputs: tier_name reserve_mb
# Classification logic:
#   - opus model OR retries >= 2 OR complexity score 5+ → large
#   - sonnet model OR complexity score 2-4 → medium
#   - haiku model OR complexity score 0-1 → small
pool_classify_budget() {
  local story_json="${1:-}"
  if [[ -z "$story_json" ]]; then
    story_json=$(cat)
  fi

  local model retries complexity
  model=$(echo "$story_json" | "$_POOL_JQ" -r '.model // .routedModel // "haiku"' 2>/dev/null)
  retries=$(echo "$story_json" | "$_POOL_JQ" -r '.retryCount // 0' 2>/dev/null)
  complexity=$(echo "$story_json" | "$_POOL_JQ" -r '.complexityScore // 0' 2>/dev/null)

  # Ensure numeric
  [[ "$retries" =~ ^[0-9]+$ ]] || retries=0
  [[ "$complexity" =~ ^[0-9]+$ ]] || complexity=0

  local tier reserve_mb
  if [[ "$model" == *opus* ]] || [[ "$retries" -ge 2 ]] || [[ "$complexity" -ge 5 ]]; then
    tier="large"
    reserve_mb="$_POOL_TIER_LARGE"
  elif [[ "$model" == *sonnet* ]] || [[ "$complexity" -ge 2 ]]; then
    tier="medium"
    reserve_mb="$_POOL_TIER_MEDIUM"
  else
    tier="small"
    reserve_mb="$_POOL_TIER_SMALL"
  fi

  echo "$tier $reserve_mb"
}

# ── pool_compute_v8_heap(reservation_mb) — Compute V8 heap from reservation ──
pool_compute_v8_heap() {
  local reservation_mb="${1:-0}"
  echo $((reservation_mb * _POOL_V8_FRACTION / 100))
}

# ── pool_reclaim_stale() — Scan for dead PIDs, reclaim their reservations ────
pool_reclaim_stale() {
  if [[ ! -f "$_POOL_LEDGER" ]]; then
    return 0
  fi

  _pool_lock || return 1

  # Get list of worker IDs and their PIDs
  local worker_ids
  worker_ids=$("$_POOL_JQ" -r '.workers | keys[]' "$_POOL_LEDGER" 2>/dev/null)

  local reclaimed=0
  for wid in $worker_ids; do
    local wpid
    wpid=$("$_POOL_JQ" -r ".workers[\"$wid\"].pid // 0" "$_POOL_LEDGER" 2>/dev/null)
    if [[ -n "$wpid" && "$wpid" -ne 0 ]] && ! kill -0 "$wpid" 2>/dev/null; then
      # PID is dead — reclaim
      local reserved
      reserved=$("$_POOL_JQ" -r ".workers[\"$wid\"].reserved_mb // 0" "$_POOL_LEDGER" 2>/dev/null)

      local new_reserved new_available cur_reserved cur_available
      cur_reserved=$("$_POOL_JQ" -r '.reserved_mb' "$_POOL_LEDGER")
      cur_available=$("$_POOL_JQ" -r '.available_mb' "$_POOL_LEDGER")
      new_reserved=$((cur_reserved - reserved))
      new_available=$((cur_available + reserved))
      [[ "$new_reserved" -lt 0 ]] && new_reserved=0

      "$_POOL_JQ" \
        --arg wid "$wid" \
        --argjson nr "$new_reserved" \
        --argjson na "$new_available" \
        '.reserved_mb = $nr | .available_mb = $na | del(.workers[$wid])' \
        "$_POOL_LEDGER" >"${_POOL_LEDGER}.tmp" && mv "${_POOL_LEDGER}.tmp" "$_POOL_LEDGER"

      echo "[pool] Reclaimed ${reserved}MB from dead worker $wid (PID $wpid)"
      reclaimed=$((reclaimed + reserved))
    fi
  done

  _pool_unlock

  [[ "$reclaimed" -gt 0 ]] && echo "[pool] Total reclaimed: ${reclaimed}MB"
  return 0
}

# ── pool_cleanup() — Remove ledger and lock files ────────────────────────────
pool_cleanup() {
  rm -f "$_POOL_LEDGER" "${_POOL_LEDGER}.tmp" 2>/dev/null || true
  rm -rf "$_POOL_LOCK" 2>/dev/null || true
}

# Export functions for subshells
export -f pool_init pool_reserve pool_release pool_available pool_classify_budget pool_compute_v8_heap pool_reclaim_stale pool_cleanup _pool_free_ram_mb _pool_lock _pool_unlock

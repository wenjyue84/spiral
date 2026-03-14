#!/usr/bin/env bash
# lib/phases/phase_0_clarify.sh — Phase 0: CLARIFY
#
# One-time interactive session that runs BEFORE the main loop begins.
# Purpose: align the user and Spiral on time budget, focus area, and an
# initial story backlog before any autonomous research or implementation starts.
#
# Called once from spiral.sh after config is loaded.
# Skipped if --gate proceed or --gate skip is passed (non-interactive mode).
# Skipped on resume when .spiral/_phase_0_done marker file exists.
#
# Outputs:
#   .spiral/_clarify_output.json   — seeds added to prd.json (audit log)
#   .spiral/_phase_0_done          — marker so resume skips Phase 0
#
# Variables set (exported to parent shell):
#   TIME_LIMIT_MINS   — 0 = unlimited; >0 = stop after N minutes
#   SPIRAL_FOCUS      — optional focus area string

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_clarify() {
  local prd_file="${PRD_FILE:-prd.json}"
  local scratch="${SCRATCH_DIR:-.spiral}"
  local done_marker="$scratch/_phase_0_done"
  local output_file="$scratch/_clarify_output.json"

  # ── Skip conditions ────────────────────────────────────────────────────────
  # Non-interactive gate modes bypass Phase 0 entirely
  if [[ "${GATE_DEFAULT:-}" == "proceed" || "${GATE_DEFAULT:-}" == "skip" ]]; then
    echo "  [Phase 0] Skipping (--gate ${GATE_DEFAULT})"
    return 0
  fi

  # Already completed in a previous run (resume)
  if [[ -f "$done_marker" ]]; then
    echo "  [Phase 0] Skipping (checkpoint: phase_0_complete)"
    return 0
  fi

  mkdir -p "$scratch"

  echo ""
  echo "  ╔══════════════════════════════════════════════════════════════════╗"
  echo "  ║  SPIRAL Phase 0 — Session Setup                                 ║"
  echo "  ╚══════════════════════════════════════════════════════════════════╝"
  echo ""

  # ── Step 1: Time budget ────────────────────────────────────────────────────
  local _hours_input=""
  if [[ "${TIME_LIMIT_MINS:-0}" -gt 0 ]]; then
    echo "  [Phase 0] Time limit already set: ${TIME_LIMIT_MINS}m (from --time-limit)"
  else
    printf "  How many hours should Spiral run? (Enter for unlimited): "
    read -r _hours_input 2>/dev/null || _hours_input=""
    if [[ -n "$_hours_input" ]]; then
      # Validate: must be a positive number (integer or decimal)
      if [[ "$_hours_input" =~ ^[0-9]+(\.[0-9]+)?$ ]] && [[ "$_hours_input" != "0" ]]; then
        # Convert hours → minutes, rounding up
        TIME_LIMIT_MINS=$(python3 -c "import math; print(math.ceil(float('$_hours_input') * 60))" 2>/dev/null || \
          echo $(( ${_hours_input%%.*} * 60 )))
        export TIME_LIMIT_MINS
        echo "  [Phase 0] Time limit set to ${TIME_LIMIT_MINS}m (~${_hours_input}h)"
      else
        echo "  [Phase 0] Invalid input ('$_hours_input') — running unlimited"
      fi
    else
      echo "  [Phase 0] No time limit set — running unlimited"
    fi
  fi

  # ── Step 2: Focus area ─────────────────────────────────────────────────────
  local _focus_input=""
  if [[ -n "${SPIRAL_FOCUS:-}" ]]; then
    echo "  [Phase 0] Focus already set: \"$SPIRAL_FOCUS\" (from --focus)"
  else
    printf "  Any focus area for this session? (Enter to skip): "
    read -r _focus_input 2>/dev/null || _focus_input=""
    if [[ -n "$_focus_input" ]]; then
      SPIRAL_FOCUS="$_focus_input"
      export SPIRAL_FOCUS
      echo "  [Phase 0] Focus set to: \"$SPIRAL_FOCUS\""
    else
      echo "  [Phase 0] No focus set — running full backlog"
    fi
  fi

  # ── Step 3: Story seeds ────────────────────────────────────────────────────
  echo ""
  echo "  Enter initial story seeds (one per line; empty line to finish):"
  echo "  Example: Add dark mode toggle to dashboard"
  echo ""

  local _seeds=()
  local _seed_line=""
  while true; do
    printf "  > "
    read -r _seed_line 2>/dev/null || break
    [[ -z "$_seed_line" ]] && break
    _seeds+=("$_seed_line")
  done

  local _seeds_added=0
  if [[ ${#_seeds[@]} -gt 0 ]]; then
    echo ""
    echo "  [Phase 0] Adding ${#_seeds[@]} story seed(s) to prd.json..."

    # Find max existing numeric ID
    local _max_id
    _max_id=$("$SPIRAL_PYTHON" - "$prd_file" 2>/dev/null <<'_PY'
import json, sys, re

with open(sys.argv[1], encoding="utf-8") as f:
    prd = json.load(f)

prefix = prd.get("storyIdPrefix", "US")
max_n = 0
for s in prd.get("userStories", []):
    m = re.match(rf"^{re.escape(prefix)}-(\d+)$", s.get("id", ""))
    if m:
        max_n = max(max_n, int(m.group(1)))
print(max_n)
_PY
) || _max_id=0

    local _next_id=$(( _max_id + 1 ))
    local _story_prefix
    _story_prefix=$("$SPIRAL_PYTHON" -c "
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    prd = json.load(f)
print(prd.get('storyIdPrefix', 'US'))
" "$prd_file" 2>/dev/null) || _story_prefix="US"

    local _new_stories_json="[]"
    for _seed in "${_seeds[@]}"; do
      local _story_id="${_story_prefix}-${_next_id}"
      local _ts
      _ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      _new_stories_json=$("$SPIRAL_PYTHON" - "$prd_file" "$_story_id" "$_seed" "$_ts" 2>/dev/null <<'_PY'
import json, sys

prd_file, story_id, title, ts = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

with open(prd_file, encoding="utf-8") as f:
    prd = json.load(f)

new_story = {
    "id": story_id,
    "title": title,
    "priority": "medium",
    "passes": False,
    "description": title,
    "acceptanceCriteria": [],
    "seed": True,
    "added_by": "phase_0_clarify",
    "added_ts": ts,
}
prd["userStories"].append(new_story)

with open(prd_file, "w", encoding="utf-8") as f:
    json.dump(prd, f, indent=2, ensure_ascii=False)

print(json.dumps(new_story))
_PY
) || { echo "  [Phase 0] WARNING: Failed to add story '$_seed' to prd.json" >&2; continue; }

      echo "  [Phase 0]   Added [$_story_id] $_seed"
      _next_id=$(( _next_id + 1 ))
      _seeds_added=$(( _seeds_added + 1 ))
    done
  fi

  # ── Write audit log ────────────────────────────────────────────────────────
  local _ts_now
  _ts_now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  "$SPIRAL_PYTHON" - "$output_file" "$_ts_now" \
    "${TIME_LIMIT_MINS:-0}" \
    "${SPIRAL_FOCUS:-}" \
    "$_seeds_added" \
    2>/dev/null <<'_PY' || true
import json, sys

out_file, ts, time_limit, focus, seeds_added = \
    sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], int(sys.argv[5])

data = {
    "phase": "0",
    "ts": ts,
    "time_limit_mins": time_limit,
    "focus": focus,
    "seeds_added": seeds_added,
}
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
_PY

  # ── Mark Phase 0 complete (resume skip) ───────────────────────────────────
  echo "phase_0_complete" > "$done_marker"

  echo ""
  echo "  [Phase 0] Complete — session configured"
  [[ "${TIME_LIMIT_MINS:-0}" -gt 0 ]] && echo "  [Phase 0]   Time limit:  ${TIME_LIMIT_MINS}m"
  [[ -n "${SPIRAL_FOCUS:-}" ]]         && echo "  [Phase 0]   Focus:       $SPIRAL_FOCUS"
  [[ "$_seeds_added" -gt 0 ]]          && echo "  [Phase 0]   Seeds added: $_seeds_added"
  echo ""
}

#!/bin/bash
# SPIRAL — Runtime Assertion Library
# Source this file in spiral.sh and ralph.sh, then call assertions at phase boundaries.
# Violations are logged to _assert_violations.log and optionally halt execution.
#
# All assertions use SPIRAL_ASSERT_MODE (default: "warn") to control behavior:
#   "warn"  — log + continue (default, safe for production runs)
#   "strict" — log + exit 1 (for debugging / CI)

SPIRAL_ASSERT_MODE="${SPIRAL_ASSERT_MODE:-warn}"

_spiral_assert_fail() {
  local check_name="$1"
  local message="$2"
  local log_file="${SCRATCH_DIR:-/tmp}/_assert_violations.log"

  echo "[ASSERT FAIL] $check_name: $message"
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) | $check_name | $message" >>"$log_file"

  if [[ "$SPIRAL_ASSERT_MODE" == "strict" ]]; then
    echo "[ASSERT] Strict mode — aborting"
    exit 1
  fi
}

# ── PRD Schema Validation ────────────────────────────────────────────────────
spiral_assert_prd_valid() {
  local prd="${1:-$PRD_FILE}"
  if ! "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd" --quiet 2>/dev/null; then
    _spiral_assert_fail "prd_valid" "Schema validation failed for $prd"
    return 1
  fi
  return 0
}

# ── Story ID Uniqueness (fast jq check) ─────────────────────────────────────
spiral_assert_ids_unique() {
  local prd="${1:-$PRD_FILE}"
  local total ids unique
  total=$("$JQ" '[.userStories | length] | .[0]' "$prd")
  unique=$("$JQ" '[.userStories[].id] | unique | length' "$prd")
  if [[ "$total" -ne "$unique" ]]; then
    _spiral_assert_fail "ids_unique" "Duplicate IDs: $total stories but only $unique unique IDs"
    return 1
  fi
  return 0
}

# ── Dependency DAG (no cycles) ───────────────────────────────────────────────
spiral_assert_deps_dag() {
  local prd="${1:-$PRD_FILE}"
  if ! "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/check_dag.py" "$prd" >/dev/null 2>&1; then
    _spiral_assert_fail "deps_dag" "Dependency cycle detected in $prd"
    return 1
  fi
  return 0
}

# ── Story Count Bounded ─────────────────────────────────────────────────────
spiral_assert_story_count_bounded() {
  local prd="${1:-$PRD_FILE}"
  local max_stories="${SPIRAL_MAX_TOTAL_STORIES:-200}"
  local count
  count=$("$JQ" '[.userStories | length] | .[0]' "$prd")
  if [[ "$count" -gt "$max_stories" ]]; then
    _spiral_assert_fail "story_count_bounded" "Total stories ($count) exceeds max ($max_stories)"
    return 1
  fi
  return 0
}

# ── Passes Monotonic (non-decreasing between save/check calls) ───────────────
spiral_assert_passes_save_baseline() {
  local prd="${1:-$PRD_FILE}"
  local baseline_file="${SCRATCH_DIR:-/tmp}/_passes_baseline"
  local current
  current=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$prd")
  echo "$current" >"$baseline_file"
}

spiral_assert_passes_monotonic() {
  local prd="${1:-$PRD_FILE}"
  local baseline_file="${SCRATCH_DIR:-/tmp}/_passes_baseline"
  if [[ ! -f "$baseline_file" ]]; then
    return 0 # No baseline yet — skip
  fi
  local baseline current
  baseline=$(cat "$baseline_file")
  current=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$prd")
  if [[ "$current" -lt "$baseline" ]]; then
    _spiral_assert_fail "passes_monotonic" "Passes decreased: $baseline → $current (regression detected)"
    return 1
  fi
  # Update baseline to new value
  echo "$current" >"$baseline_file"
  return 0
}

# ── Phase Order Validation ───────────────────────────────────────────────────
spiral_assert_phase_order() {
  local current_phase="$1"
  local last_phase_file="${SCRATCH_DIR:-/tmp}/_last_phase"

  declare -A PHASE_ORDER=([R]=1 [T]=2 [M]=3 [G]=4 [I]=5 [V]=6 [C]=7)

  if [[ -f "$last_phase_file" ]]; then
    local last_phase
    last_phase=$(cat "$last_phase_file")
    local last_ord="${PHASE_ORDER[$last_phase]:-0}"
    local curr_ord="${PHASE_ORDER[$current_phase]:-0}"
    # Phase order must increase within an iteration, or reset (C → R on new iteration)
    if [[ "$curr_ord" -le "$last_ord" && "$current_phase" != "R" ]]; then
      _spiral_assert_fail "phase_order" "Phase went backward: $last_phase → $current_phase"
      return 1
    fi
  fi

  echo "$current_phase" >"$last_phase_file"
  return 0
}

# ── No Orphan .tmp Files ────────────────────────────────────────────────────
spiral_assert_no_orphan_tmpfiles() {
  local scratch="${SCRATCH_DIR:-/tmp}"
  local count
  count=$(find "$scratch" -maxdepth 1 -name "*.tmp" -mmin +10 2>/dev/null | wc -l)
  if [[ "$count" -gt 0 ]]; then
    _spiral_assert_fail "orphan_tmpfiles" "$count stale .tmp files in $scratch (>10 min old)"
    return 1
  fi
  return 0
}

# ── Merge No Story Loss ───────────────────────────────────────────────────
spiral_assert_merge_no_story_loss() {
  local before="$1"
  local after="$2"
  if [[ "$after" -lt "$before" ]]; then
    _spiral_assert_fail "merge_no_story_loss" "Stories decreased during merge: $before → $after"
    return 1
  fi
  return 0
}

# ── Pending Story Count Bounded ───────────────────────────────────────────
spiral_assert_pending_bounded() {
  local prd="${1:-$PRD_FILE}"
  local max_pending="${SPIRAL_MAX_PENDING:-0}"
  [[ "$max_pending" -eq 0 ]] && return 0 # unlimited
  local pending
  pending=$("$JQ" '[.userStories[] | select(.passes != true and ._decomposed != true)] | length' "$prd")
  if [[ "$pending" -gt "$max_pending" ]]; then
    _spiral_assert_fail "pending_bounded" "Pending stories ($pending) exceeds max ($max_pending)"
    return 1
  fi
  return 0
}

# ── Decomposition Integrity ──────────────────────────────────────────────
spiral_assert_decomposition_integrity() {
  local prd="${1:-$PRD_FILE}"
  local result
  result=$("$SPIRAL_PYTHON" -c "
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    prd = json.load(f)
stories = prd.get('userStories', [])
ids = {s['id'] for s in stories if isinstance(s, dict) and 'id' in s}
id_map = {s['id']: s for s in stories if isinstance(s, dict) and 'id' in s}
errors = []
for s in stories:
    if not isinstance(s, dict): continue
    sid = s.get('id', '?')
    if s.get('_decomposed'):
        children = s.get('_decomposedInto', [])
        if not children:
            errors.append(f'{sid}: _decomposed=true but no _decomposedInto')
        for cid in children:
            if cid not in ids:
                errors.append(f'{sid}: _decomposedInto child {cid} not found')
            elif not id_map[cid].get('_decomposedFrom'):
                errors.append(f'{sid}: child {cid} missing _decomposedFrom backlink')
    parent = s.get('_decomposedFrom')
    if parent:
        if parent not in ids:
            errors.append(f'{sid}: _decomposedFrom parent {parent} not found')
        elif not id_map[parent].get('_decomposed'):
            errors.append(f'{sid}: parent {parent} not marked _decomposed')
if errors:
    for e in errors:
        print(e, file=sys.stderr)
    sys.exit(1)
" "$prd" 2>&1)
  if [[ $? -ne 0 ]]; then
    _spiral_assert_fail "decomposition_integrity" "$result"
    return 1
  fi
  return 0
}

# ── Dependency Completion Order ──────────────────────────────────────────
spiral_assert_dependency_completion_order() {
  local prd="${1:-$PRD_FILE}"
  local violations
  violations=$("$JQ" -r '
    .userStories as $all |
    ($all | map({(.id): .passes}) | add) as $pass_map |
    $all[] |
    select(.passes == true) |
    .id as $sid |
    .dependencies[]? |
    select(. as $dep | $pass_map[$dep] != true) |
    "\($sid) passes but dependency \(.) does not"
  ' "$prd" 2>/dev/null || true)
  if [[ -n "$violations" ]]; then
    _spiral_assert_fail "dep_completion_order" "$violations"
    return 1
  fi
  return 0
}

# ── Worker Disjoint (parallel mode) ─────────────────────────────────────
spiral_assert_worker_disjoint() {
  local outdir="$1"
  shift
  local worker_files=("$@")
  if [[ ${#worker_files[@]} -lt 2 ]]; then
    return 0 # nothing to check with < 2 workers
  fi
  local result
  result=$("$SPIRAL_PYTHON" -c "
import json, sys
worker_files = sys.argv[1:]
seen = {}  # story_id -> worker_file
errors = []
for wf in worker_files:
    with open(wf, encoding='utf-8') as f:
        prd = json.load(f)
    for s in prd.get('userStories', []):
        if s.get('passes'): continue  # completed stories are shared (expected)
        sid = s['id']
        if sid in seen:
            errors.append(f'{sid} assigned to both {seen[sid]} and {wf}')
        else:
            seen[sid] = wf
if errors:
    for e in errors:
        print(e, file=sys.stderr)
    sys.exit(1)
" "${worker_files[@]}" 2>&1)
  if [[ $? -ne 0 ]]; then
    _spiral_assert_fail "worker_disjoint" "$result"
    return 1
  fi
  return 0
}

# ── Iteration Progress (spinning detection) ──────────────────────────────
spiral_assert_iteration_progress() {
  local zero_count="${1:-0}"
  local max_zero="${2:-3}"
  if [[ "$zero_count" -ge "$max_zero" ]]; then
    _spiral_assert_fail "iteration_progress" "No progress for $zero_count consecutive iterations (limit: $max_zero)"
    return 1
  fi
  return 0
}

# ── Story Lifecycle Validation ──────────────────────────────────────────────
spiral_assert_story_lifecycle() {
  local prd="${1:-$PRD_FILE}"
  local result
  result=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/state_machine.py" validate-stories --prd "$prd" 2>&1)
  if [[ $? -ne 0 ]]; then
    _spiral_assert_fail "story_lifecycle" "$result"
    return 1
  fi
  return 0
}

# ── Checkpoint Coherent ──────────────────────────────────────────────────
spiral_assert_checkpoint_coherent() {
  local ckpt="${SCRATCH_DIR:-/tmp}/_checkpoint.json"
  local expected_iter="${1:-}"
  [[ ! -f "$ckpt" ]] && return 0
  local ckpt_iter ckpt_phase
  ckpt_iter=$("$JQ" -r '.iter // empty' "$ckpt" 2>/dev/null || echo "")
  ckpt_phase=$("$JQ" -r '.phase // empty' "$ckpt" 2>/dev/null || echo "")
  if [[ -z "$ckpt_iter" || -z "$ckpt_phase" ]]; then
    _spiral_assert_fail "checkpoint_coherent" "Checkpoint missing iter or phase"
    return 1
  fi
  if [[ -n "$expected_iter" && "$ckpt_iter" != "$expected_iter" ]]; then
    _spiral_assert_fail "checkpoint_coherent" "Checkpoint iter=$ckpt_iter but expected $expected_iter"
    return 1
  fi
  case "$ckpt_phase" in
    R | T | M | G | I | V | C) ;;
    *)
      _spiral_assert_fail "checkpoint_coherent" "Invalid checkpoint phase: $ckpt_phase"
      return 1
      ;;
  esac
  return 0
}

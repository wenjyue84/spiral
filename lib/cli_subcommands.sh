#!/usr/bin/env bash
# lib/cli_subcommands.sh -- CLI subcommands that run-and-exit (--migrate, --status, etc.)
#
# Extracted from spiral.sh. Sourced after SPIRAL_HOME, SPIRAL_PYTHON, JQ,
# PRD_FILE, SCRATCH_DIR, CHECKPOINT_FILE, REPO_ROOT, DRY_RUN, and all
# *_MODE flags are defined.
#
# Each subcommand checks its flag and exits if matched.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# ── --migrate: run prd.json schema migration and exit ────────────────────────
if [[ "$MIGRATE_MODE" -eq 1 ]]; then
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/migrate_prd.py" "$PRD_FILE"
  exit $?
fi

# ── --archive-done: archive completed stories and exit ───────────────────────
if [[ "$ARCHIVE_MODE" -eq 1 ]]; then
  _ARCHIVE_ARGS=("--prd" "$PRD_FILE")
  [[ "$DRY_RUN" -eq 1 ]] && _ARCHIVE_ARGS+=("--dry-run")
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/archive_prd.py" "${_ARCHIVE_ARGS[@]}"
  exit $?
fi

# ── --changelog: generate CHANGELOG.md via git-cliff and exit ───────────────
if [[ "$CHANGELOG_MODE" -eq 1 ]]; then
  source "$SPIRAL_HOME/lib/phases/gen_changelog.sh"
  phase_gen_changelog
  exit $?
fi

# ── --append-changelog: append new iteration section to CHANGELOG.md ────────
if [[ "${APPEND_CHANGELOG:-0}" -eq 1 ]]; then
  _AC_ITER="${SPIRAL_ITERATION:-1}"
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/gen_changelog.py" \
    --append-changelog --iteration "$_AC_ITER" "$REPO_ROOT"
  exit $?
fi

# ── --show-docs: list generated API documentation and exit ────────────────────
if [[ "$SHOW_DOCS_MODE" -eq 1 ]]; then
  source "$SPIRAL_HOME/lib/phases/documentation.sh"
  if list_api_docs; then
    exit 0
  else
    exit 1
  fi
fi

# ── --stale-report: print stories inactive beyond SPIRAL_STALE_DAYS and exit ─
if [[ "$STALE_REPORT_MODE" -eq 1 ]]; then
  _STALE_DAYS="${SPIRAL_STALE_DAYS:-7}"
  echo "[spiral] Stale story report (threshold: ${_STALE_DAYS} days)"
  echo ""
  "$SPIRAL_PYTHON" - "$PRD_FILE" "$_STALE_DAYS" <<'STALE_REPORT_PY'
import json, sys
from datetime import datetime, timedelta, timezone

prd_file = sys.argv[1]
stale_days = int(sys.argv[2])
now = datetime.now(timezone.utc)
threshold = now - timedelta(days=stale_days)

with open(prd_file, encoding="utf-8") as f:
    prd = json.load(f)

stale = []
for s in prd.get("userStories", []):
    if s.get("passes") or s.get("_decomposed") or s.get("_skipped"):
        continue
    ts_raw = s.get("last_attempted", "")
    if not ts_raw:
        continue
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        age = now - ts
        if age > timedelta(days=stale_days):
            stale.append((s["id"], s.get("title", ""), age, ts_raw))
    except (ValueError, TypeError):
        pass

if not stale:
    print("  No stale stories found.")
else:
    print(f"  {'ID':<12} {'Age':>8}  {'Last Attempted':<24}  Title")
    print(f"  {'-'*12} {'-'*8}  {'-'*24}  {'-'*40}")
    for sid, title, age, ts_raw in sorted(stale, key=lambda x: -x[2].total_seconds()):
        age_days = age.days
        print(f"  {sid:<12} {age_days:>7}d  {ts_raw[:19]:<24}  {title[:60]}")
    print(f"\n  Total stale: {len(stale)}")
STALE_REPORT_PY
  exit 0
fi

# ── --flaky-tests report: print quarantined test registry and exit ─────────
if [[ "$FLAKY_REPORT_MODE" -eq 1 ]]; then
  _FLAKY_LIB="$SPIRAL_HOME/lib/flaky_tests.sh"
  if [[ ! -f "$_FLAKY_LIB" ]]; then
    echo "[spiral] ERROR: lib/flaky_tests.sh not found (SPIRAL_HOME=$SPIRAL_HOME)" >&2
    exit "$ERR_MISSING_DEP"
  fi
  source "$_FLAKY_LIB"
  flaky_report
  exit 0
fi

# ── --show-flaky-tests: print flaky tests from test synthesis history and exit
if [[ "$SHOW_FLAKY_TESTS_MODE" -eq 1 ]]; then
  echo ""
  echo "  Flaky Tests -- Failing <50% of last 5 iterations (excluded from Phase T)"
  echo "  ========================================================================="
  echo ""
  _FLAKY_TESTS=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/flaky_detector.py" list_with_rates 2>/dev/null || echo "")
  if [[ -z "$_FLAKY_TESTS" ]]; then
    echo "  No flaky tests detected."
  else
    while IFS= read -r _line; do
      echo "  $_line"
    done <<<"$_FLAKY_TESTS"
  fi
  echo ""
  exit 0
fi

# ── --calibration-report: print calibration report and exit ────────────────
if [[ "$CALIBRATION_REPORT_MODE" -eq 1 ]]; then
  _CALIB_FILE="calibration.jsonl"
  if [[ ! -f "$_CALIB_FILE" ]]; then
    echo "[spiral] ERROR: calibration.jsonl not found. Run SPIRAL first to generate calibration data." >&2
    exit 1
  fi
  echo "CALIBRATION REPORT -- Actual vs Estimated Complexity"
  echo "====================================================="
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/calibration_tracker.py" report --calibration-file "$_CALIB_FILE"
  exit 0
fi

# ── --show-patterns: display learned retry patterns and exit ────────────────
if [[ "$SHOW_PATTERNS_MODE" -eq 1 ]]; then
  _PATTERNS_FILE="$REPO_ROOT/.spiral/learned_patterns.json"
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/pattern_analyzer.py" show "$_PATTERNS_FILE" 2>/dev/null || true
  exit 0
fi

# ── --validate-federated: validate story ID namespacing and exit ──────────────
if [[ "$VALIDATE_FEDERATED_MODE" -eq 1 ]]; then
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/spiral/federated_namespace_validator.py" "$PRD_FILE" "$VALIDATE_FEDERATED_REPOS"
  exit $?
fi

# ── Schema version check ────────────────────────────────────────────────────
_PRD_SCHEMA_VER=$("$JQ" -r '.schemaVersion // empty' "$PRD_FILE" 2>/dev/null || echo "")
if [[ -n "$_PRD_SCHEMA_VER" ]] && [[ "$_PRD_SCHEMA_VER" -gt 1 ]] 2>/dev/null; then
  spiral_exit E503 "$_PRD_SCHEMA_VER"
fi

# ── --status: print session state and exit ───────────────────────────────────
if [[ "$STATUS_ONLY" -eq 1 ]]; then
  TOTAL=$("$JQ" '[.userStories[]] | length' "$PRD_FILE" 2>/dev/null || echo "?")
  PASSED=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE" 2>/dev/null || echo "?")
  PENDING=$("$JQ" '[.userStories[] | select(.passes != true)] | length' "$PRD_FILE" 2>/dev/null || echo "?")
  if [[ -f "$CHECKPOINT_FILE" ]]; then
    CKPT_ITER=$("$JQ" -r '.iter // "?"' "$CHECKPOINT_FILE" 2>/dev/null || echo "?")
    CKPT_PHASE=$("$JQ" -r '.phase // "?"' "$CHECKPOINT_FILE" 2>/dev/null || echo "?")
    CKPT_TS=$("$JQ" -r '.ts // "?"' "$CHECKPOINT_FILE" 2>/dev/null || echo "?")
    echo "[spiral] Session status"
    echo "  Iteration : $CKPT_ITER"
    echo "  Last phase: $CKPT_PHASE"
    echo "  Timestamp : $CKPT_TS"
  else
    echo "[spiral] No active session (no checkpoint found)"
  fi
  echo "  Stories   : $TOTAL total / $PASSED passed / $PENDING pending"
  _STORY_COSTS_FILE="$SCRATCH_DIR/story_costs.json"
  if [[ -f "$_STORY_COSTS_FILE" ]]; then
    _TOTAL_COST=$("$SPIRAL_PYTHON" -c "
import json, sys
try:
    with open('$_STORY_COSTS_FILE', encoding='utf-8') as f:
        costs = json.load(f)
    total = sum(v.get('estimated_usd', 0.0) for v in costs.values())
    print(f'\${total:.4f}')
except Exception:
    print('?')
" 2>/dev/null || echo "?")
    echo "  Run cost  : ${_TOTAL_COST} USD (from story_costs.json)"
  fi
  _WT_BASE="$REPO_ROOT/.spiral-workers"
  if [[ -d "$_WT_BASE" ]]; then
    _ORPHAN_COUNT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null |
      grep "^worktree " | grep -c "spiral-workers" 2>/dev/null || echo "0")
    if [[ "$_ORPHAN_COUNT" -gt 0 ]]; then
      echo "  Worktrees : $_ORPHAN_COUNT orphaned spiral-worker worktree(s) in $_WT_BASE"
    else
      echo "  Worktrees : clean (no orphaned spiral-worker worktrees)"
    fi
  else
    echo "  Worktrees : clean (no orphaned spiral-worker worktrees)"
  fi
  _LAST_ERR_FILE="$SCRATCH_DIR/_last_error.json"
  if [[ -f "$_LAST_ERR_FILE" ]]; then
    _LE_CODE=$("$JQ" -r '.error_code // "?"' "$_LAST_ERR_FILE" 2>/dev/null || echo "?")
    _LE_CAT=$("$JQ" -r '.category // "?"' "$_LAST_ERR_FILE" 2>/dev/null || echo "?")
    _LE_MSG=$("$JQ" -r '.message // "?"' "$_LAST_ERR_FILE" 2>/dev/null || echo "?")
    _LE_TS=$("$JQ" -r '.ts // "?"' "$_LAST_ERR_FILE" 2>/dev/null || echo "?")
    echo "  Last error: [SPIRAL-E-${_LE_CODE}] [${_LE_CAT}] ${_LE_MSG} (${_LE_TS})"
  else
    echo "  Last error: none"
  fi
  _WORKER_ERR_DIR="$SCRATCH_DIR/workers"
  if [[ -d "$_WORKER_ERR_DIR" ]]; then
    for _WE_DIR in "$_WORKER_ERR_DIR"/*/; do
      _WE_FILE="${_WE_DIR}_last_error.json"
      if [[ -f "$_WE_FILE" ]]; then
        _WE_SID=$(basename "$_WE_DIR")
        _WE_CODE=$("$JQ" -r '.error_code // "?"' "$_WE_FILE" 2>/dev/null || echo "?")
        _WE_MSG=$("$JQ" -r '.message // "?"' "$_WE_FILE" 2>/dev/null || echo "?")
        echo "  [Worker ${_WE_SID}] Last Error: [SPIRAL-E-${_WE_CODE}] ${_WE_MSG}"
      fi
    done
  fi
  if [[ -n "$SPIRAL_SKIP_STORY_IDS" ]]; then
    IFS=',' read -ra _SKIP_ARR <<<"$SPIRAL_SKIP_STORY_IDS"
    for _SID in "${_SKIP_ARR[@]}"; do
      _SID=$(echo "$_SID" | tr -d ' ')
      [[ -z "$_SID" ]] && continue
      _TITLE=$("$JQ" -r --arg sid "$_SID" '.userStories[] | select(.id == $sid) | .title' "$PRD_FILE" 2>/dev/null || echo "?")
      echo "  [MANUAL SKIP] [$_SID] $_TITLE"
    done
  fi
  exit 0
fi

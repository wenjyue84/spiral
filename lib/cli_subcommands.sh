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

# ── --clear-research-cache: flush Phase R query-level cache and exit ────────────
if [[ "$CLEAR_RESEARCH_CACHE" -eq 1 ]]; then
  "$SPIRAL_PYTHON" -c "from lib.phase_r_cache import clear_cache; count = clear_cache(); print(f'Cleared {count} cache files from .spiral/research-cache/')"
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
VALIDATE_FEDERATED_MODE="${VALIDATE_FEDERATED_MODE:-0}"
VALIDATE_FEDERATED_REPOS="${VALIDATE_FEDERATED_REPOS:-}"
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

# ── explain: display full context for a single story ─────────────────────────
EXPLAIN_MODE="${EXPLAIN_MODE:-0}"
EXPLAIN_STORY_ID="${EXPLAIN_STORY_ID:-}"
EXPLAIN_FORMAT="${EXPLAIN_FORMAT:-text}"
if [[ "$EXPLAIN_MODE" -eq 1 ]]; then
  if [[ -z "$EXPLAIN_STORY_ID" ]]; then
    echo "[spiral] ERROR: Usage: spiral explain <story-id> [--markdown|--json]" >&2
    exit 1
  fi
  _EXPLAIN_ARGS=("$PRD_FILE" "$EXPLAIN_STORY_ID" "--format" "$EXPLAIN_FORMAT")
  _RESULTS_TSV="${RESULTS_TSV:-$REPO_ROOT/results.tsv}"
  [[ -f "$_RESULTS_TSV" ]] && _EXPLAIN_ARGS+=("--results" "$_RESULTS_TSV")
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/story_formatter.py" "${_EXPLAIN_ARGS[@]}"
  exit $?
fi

# ── logs: view implementation logs for a story ──────────────────────────────────
LOGS_MODE="${LOGS_MODE:-0}"
LOGS_STORY_ID="${LOGS_STORY_ID:-}"
LOGS_LEVEL="${LOGS_LEVEL:-}"
LOGS_CONTEXT="${LOGS_CONTEXT:-}"
if [[ "$LOGS_MODE" -eq 1 ]]; then
  if [[ -z "$LOGS_STORY_ID" ]]; then
    echo "[spiral] ERROR: Usage: spiral logs <story-id> [--level LEVEL] [--context CONTEXT]" >&2
    exit 1
  fi
  _LOGS_ARGS=("$LOGS_STORY_ID")
  [[ -n "$LOGS_LEVEL" ]] && _LOGS_ARGS+=("--level" "$LOGS_LEVEL")
  [[ -n "$LOGS_CONTEXT" ]] && _LOGS_ARGS+=("--context" "$LOGS_CONTEXT")
  "$SPIRAL_PYTHON" -m lib.log_viewer "${_LOGS_ARGS[@]}"
  exit $?
fi

# ── explain-rejection: display story rejection summary ──────────────────────────
EXPLAIN_REJECTION_MODE="${EXPLAIN_REJECTION_MODE:-0}"
EXPLAIN_REJECTION_STORY_ID="${EXPLAIN_REJECTION_STORY_ID:-}"
EXPLAIN_REJECTION_FORMAT="${EXPLAIN_REJECTION_FORMAT:-text}"
if [[ "$EXPLAIN_REJECTION_MODE" -eq 1 ]]; then
  if [[ -z "$EXPLAIN_REJECTION_STORY_ID" ]]; then
    echo "[spiral] ERROR: Usage: spiral explain-rejection <story-id> [--json]" >&2
    exit 1
  fi
  _REJECT_ARGS=("$PRD_FILE" "$EXPLAIN_REJECTION_STORY_ID" "--format" "$EXPLAIN_REJECTION_FORMAT")
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/cli_explain_rejection.py" "${_REJECT_ARGS[@]}"
  exit $?
fi

# ── search: full-text fuzzy search across prd.json and prd.include ────────────
SEARCH_MODE="${SEARCH_MODE:-0}"
SEARCH_QUERY="${SEARCH_QUERY:-}"
SEARCH_FORMAT="${SEARCH_FORMAT:-table}"
SEARCH_PROJECT="${SEARCH_PROJECT:-}"
SEARCH_MIN_SCORE="${SEARCH_MIN_SCORE:-30}"
if [[ "$SEARCH_MODE" -eq 1 ]]; then
  if [[ -z "$SEARCH_QUERY" ]]; then
    echo "[spiral] ERROR: Usage: spiral search <query> [--format table|json|csv] [--project NAME]" >&2
    exit 1
  fi
  _SEARCH_ARGS=("$PRD_FILE" "$SEARCH_QUERY" "--format" "$SEARCH_FORMAT" "--min-score" "$SEARCH_MIN_SCORE")
  [[ -n "$SEARCH_PROJECT" ]] && _SEARCH_ARGS+=("--project" "$SEARCH_PROJECT")
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/cli/search_stories.py" "${_SEARCH_ARGS[@]}"
  exit $?
fi

# ── query stories: filter/sort/export prd.json + results.tsv ─────────────────
QUERY_MODE="${QUERY_MODE:-0}"
QUERY_SUBCOMMAND="${QUERY_SUBCOMMAND:-}"
QUERY_STATUS="${QUERY_STATUS:-}"
QUERY_COMPLEXITY="${QUERY_COMPLEXITY:-}"
QUERY_PROJECT="${QUERY_PROJECT:-}"
QUERY_BY_PROJECT="${QUERY_BY_PROJECT:-0}"
QUERY_FORMAT="${QUERY_FORMAT:-table}"
if [[ "$QUERY_MODE" -eq 1 ]] && [[ "$QUERY_SUBCOMMAND" == "stories" ]]; then
  _QUERY_ARGS=("$PRD_FILE" "${RESULTS_TSV:-$REPO_ROOT/results.tsv}")
  [[ -n "$QUERY_STATUS" ]] && _QUERY_ARGS+=("--status" "$QUERY_STATUS")
  [[ -n "$QUERY_COMPLEXITY" ]] && _QUERY_ARGS+=("--complexity" "$QUERY_COMPLEXITY")
  [[ -n "$QUERY_PROJECT" ]] && _QUERY_ARGS+=("--project" "$QUERY_PROJECT")
  [[ "$QUERY_BY_PROJECT" -eq 1 ]] && _QUERY_ARGS+=("--by-project")
  _QUERY_ARGS+=("--format" "$QUERY_FORMAT")
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/story_query.py" "${_QUERY_ARGS[@]}"
  exit $?
fi

# ── skills: list or install plugins ─────────────────────────────────────────
SKILLS_MODE="${SKILLS_MODE:-0}"
SKILLS_SUBCOMMAND="${SKILLS_SUBCOMMAND:-list}"
SKILLS_URL="${SKILLS_URL:-}"
if [[ "$SKILLS_MODE" -eq 1 ]]; then
  _SKILLS_ARGS=("$SKILLS_SUBCOMMAND")
  if [[ "$SKILLS_SUBCOMMAND" == "install" ]]; then
    if [[ -z "$SKILLS_URL" ]]; then
      echo "[spiral] ERROR: Usage: spiral skills install <url>" >&2
      exit 1
    fi
    _SKILLS_ARGS+=("$SKILLS_URL")
  fi
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/skills_cli.py" "${_SKILLS_ARGS[@]}"
  exit $?
fi

# ── metrics export-timeseries: export time-series JSON from results.tsv + spiral_events.jsonl
METRICS_MODE="${METRICS_MODE:-0}"
METRICS_SUBCOMMAND="${METRICS_SUBCOMMAND:-}"
METRICS_OUTPUT="${METRICS_OUTPUT:-}"
if [[ "$METRICS_MODE" -eq 1 ]] && [[ "$METRICS_SUBCOMMAND" == "export-timeseries" ]]; then
  if [[ -z "$METRICS_OUTPUT" ]]; then
    echo "[spiral] ERROR: Usage: spiral metrics export-timeseries <output.json>" >&2
    exit 1
  fi
  _RESULTS_TSV="${RESULTS_TSV:-$REPO_ROOT/results.tsv}"
  _SPIRAL_EVENTS="${REPO_ROOT}/spiral_events.jsonl"
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/metrics_export.py" "$_RESULTS_TSV" "$_SPIRAL_EVENTS" "$METRICS_OUTPUT"
  exit $?
fi

# ── cost-analysis: analyze token costs and spend from results.tsv ────────────────────
COST_ANALYSIS_MODE="${COST_ANALYSIS_MODE:-0}"
COST_ANALYSIS_DETAILED="${COST_ANALYSIS_DETAILED:-0}"
COST_ANALYSIS_JSON="${COST_ANALYSIS_JSON:-0}"
COST_ANALYSIS_COMPARE_ITERATION="${COST_ANALYSIS_COMPARE_ITERATION:-}"
if [[ "$COST_ANALYSIS_MODE" -eq 1 ]]; then
  _RESULTS_TSV="${RESULTS_TSV:-$REPO_ROOT/results.tsv}"
  _CA_ARGS=("--results" "$_RESULTS_TSV")
  [[ "$COST_ANALYSIS_DETAILED" -eq 1 ]] && _CA_ARGS+=("--detailed")
  [[ "$COST_ANALYSIS_JSON" -eq 1 ]] && _CA_ARGS+=("--json")
  [[ -n "$COST_ANALYSIS_COMPARE_ITERATION" ]] && _CA_ARGS+=("--compare-iteration" "$COST_ANALYSIS_COMPARE_ITERATION")
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/cost_analysis.py" "${_CA_ARGS[@]}"
  exit $?
fi

# ── snapshot_list_handler: format and display snapshot list output ────────────────────
snapshot_list_handler() {
  local out_dir="$1"
  local json_output=()

  # Call Python to get JSON snapshot list
  local json_data
  json_data=$("$SPIRAL_PYTHON" -c "
import sys
import json
sys.path.insert(0, '$SPIRAL_HOME')
from lib.snapshot import SnapshotManager

manager = SnapshotManager(project_root='$REPO_ROOT')
snapshots = manager.list(out_dir='$out_dir')
print(json.dumps(snapshots, indent=2))
" 2>&1)

  if [[ $? -ne 0 ]]; then
    echo "[spiral] ERROR: Failed to list snapshots: $json_data" >&2
    exit 1
  fi

  # Check if --json flag was set
  if [[ "${SNAPSHOT_JSON:-0}" -eq 1 ]]; then
    # Output raw JSON
    echo "$json_data"
  else
    # Format as ASCII table
    local snapshot_count
    snapshot_count=$(echo "$json_data" | "$JQ" 'length')

    if [[ "$snapshot_count" -eq 0 ]]; then
      echo "No snapshots found in $out_dir"
      exit 0
    fi

    # Print header
    printf "%-35s %-12s %-12s %-26s\n" "Timestamp" "Size" "Stories" "Created"
    printf "%-35s %-12s %-12s %-26s\n" "$(printf '%0.s-' {1..35})" "$(printf '%0.s-' {1..12})" "$(printf '%0.s-' {1..12})" "$(printf '%0.s-' {1..26})"

    # Print snapshot rows
    echo "$json_data" | "$JQ" -r '.[] | [.timestamp, .size_human, .story_count, .creation_time] | @tsv' | while IFS=$'\t' read -r timestamp size stories created; do
      printf "%-35s %-12s %-12s %-26s\n" "$timestamp" "$size" "$stories" "$created"
    done
  fi
}

# ── snapshot save/restore/list: create, restore, and list project state snapshots ────────
SNAPSHOT_MODE="${SNAPSHOT_MODE:-0}"
SNAPSHOT_SUBCOMMAND="${SNAPSHOT_SUBCOMMAND:-}"
SNAPSHOT_TIMESTAMP="${SNAPSHOT_TIMESTAMP:-}"
SNAPSHOT_JSON="${SNAPSHOT_JSON:-0}"
if [[ "$SNAPSHOT_MODE" -eq 1 ]]; then
  _SNAPSHOT_OUT_DIR="${SCRATCH_DIR}"
  if [[ "$SNAPSHOT_SUBCOMMAND" == "save" ]]; then
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/snapshot.py" save --out-dir "$_SNAPSHOT_OUT_DIR" --project-root "$REPO_ROOT"
    exit $?
  elif [[ "$SNAPSHOT_SUBCOMMAND" == "restore" ]]; then
    if [[ -z "$SNAPSHOT_TIMESTAMP" ]]; then
      echo "[spiral] ERROR: Usage: spiral snapshot restore <timestamp>" >&2
      exit 1
    fi
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/snapshot.py" restore "$SNAPSHOT_TIMESTAMP" --out-dir "$_SNAPSHOT_OUT_DIR" --project-root "$REPO_ROOT"
    exit $?
  elif [[ "$SNAPSHOT_SUBCOMMAND" == "list" ]]; then
    snapshot_list_handler "$_SNAPSHOT_OUT_DIR"
    exit $?
  fi
fi

# ── export-progress: bundle PRD, results, and metrics as a shareable snapshot ─
EXPORT_PROGRESS_MODE="${EXPORT_PROGRESS_MODE:-0}"
EXPORT_PROGRESS_FORMAT="${EXPORT_PROGRESS_FORMAT:-json}"
EXPORT_PROGRESS_OUTPUT="${EXPORT_PROGRESS_OUTPUT:-}"
if [[ "$EXPORT_PROGRESS_MODE" -eq 1 ]]; then
  _EP_ARGS=("--format" "$EXPORT_PROGRESS_FORMAT" "--project-root" "$REPO_ROOT")
  [[ -n "$EXPORT_PROGRESS_OUTPUT" ]] && _EP_ARGS+=("--output" "$EXPORT_PROGRESS_OUTPUT")
  _EP_ITER="${SPIRAL_ITERATION:-0}"
  _EP_ARGS+=("--iteration" "$_EP_ITER")
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/export_progress.py" "${_EP_ARGS[@]}"
  exit $?
fi

# ── batch: execute batch operations on multiple stories (mark-done, retrigger) ─
BATCH_MODE="${BATCH_MODE:-0}"
BATCH_OPERATION="${BATCH_OPERATION:-}"
BATCH_STORIES_FILE="${BATCH_STORIES_FILE:-}"
if [[ "$BATCH_MODE" -eq 1 ]]; then
  if [[ -z "$BATCH_OPERATION" ]] || [[ -z "$BATCH_STORIES_FILE" ]]; then
    echo "Error: batch requires <operation> and --stories-file <file>" >&2
    exit 1
  fi
  _BATCH_ARGS=("$BATCH_OPERATION" "--stories-file" "$BATCH_STORIES_FILE" "--project-root" "$REPO_ROOT")
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/batch_operations.py" "${_BATCH_ARGS[@]}"
  exit $?
fi

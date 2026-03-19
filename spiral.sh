#!/bin/bash
# SPIRAL — Self-iterating PRD Research and Implementation Autonomous Loop
#
# Usage:
#   bash spiral.sh [max_spiral_iterations] [--gate proceed|skip|quit] [--ralph-iters N]
#   bash ~/.ai/Skills/spiral/spiral.sh 1 --gate skip
#
# Phases per iteration:
#   R) RESEARCH    — Claude agent searches sources → _research_output.json
#   T) TEST SYNTH  — synthesize_tests.py → _test_stories_output.json
#   M) MERGE       — merge_stories.py deduplicates + patches prd.json
#   G) GATE        — human checkpoint: proceed | skip | quit
#   I) IMPLEMENT   — ralph.sh (up to 120 inner iterations)
#   V) VALIDATE    — test suite; fresh report for check_done
#   C) CHECK DONE  — exit 0 if complete, else loop
#
# Non-interactive (Claude Code / CI):
#   bash spiral.sh 1 --gate proceed          # auto-proceed at every gate
#   bash spiral.sh 1 --gate skip             # research+merge only, skip ralph
#   bash spiral.sh 3 --gate proceed --ralph-iters 60
#   bash spiral.sh 5 --gate proceed --skip-research          # impl-only (no web research)
#   bash spiral.sh 5 --gate proceed --ralph-workers 3        # 3 parallel worktree workers
#   bash spiral.sh 1 --gate proceed --dry-run                # test control flow, no API calls
#
# Crash recovery:
#   If SPIRAL is interrupted mid-iteration, re-running resumes from the
#   last completed phase of the interrupted iteration (via _checkpoint.json).

set -euo pipefail

# ── Exit code constants ───────────────────────────────────────────────────────
# Exit code 0  = full success.
# Exit code 1  = NEVER intentionally used (unclassified/unexpected shell error).
# Exit codes 2-125 are safe for scripts; 126/127 are reserved by the shell;
# 128+ indicate signal deaths (e.g. 130 = SIGINT, kept as shell standard).
# CI pipelines and the SPIRAL_ON_COMPLETE hook can branch on $? using these names.
#
# ┌─────┬─────────────────────┬──────────────────────────────────────────────┐
# │ Code│ Constant            │ Meaning                                      │
# ├─────┼─────────────────────┼──────────────────────────────────────────────┤
# │   0 │ (success)           │ All stories passed / operation completed OK  │
# │   2 │ ERR_BAD_USAGE       │ Wrong CLI arguments or unknown flag          │
# │   3 │ ERR_CONFIG          │ Missing or invalid spiral.config.sh value    │
# │   4 │ ERR_MISSING_DEP     │ Required tool not found (jq, ralph.sh, …)   │
# │   5 │ ERR_PRD_NOT_FOUND   │ prd.json file not found                      │
# │   6 │ ERR_PRD_CORRUPT     │ prd.json corrupt and unrecoverable           │
# │   7 │ ERR_SCHEMA_VERSION  │ prd.json schemaVersion too new for SPIRAL    │
# │   8 │ ERR_COST_CEILING    │ Spend cap (SPIRAL_COST_CEILING) reached      │
# │   9 │ ERR_ZERO_PROGRESS   │ Zero-progress stall — all pending blocked    │
# │  10 │ ERR_REPLAY_FAILED   │ --replay mode: story implementation failed   │
# │  11 │ ERR_STORY_NOT_FOUND │ Story ID passed to --replay not in prd.json  │
# │  12 │ ERR_ROLLBACK_FAILED │ --rollback mode: git revert or guard failed  │
# │  13 │ ERR_MAX_ITERS       │ Max spiral iterations reached; stories remain│
# │  14 │ ERR_API_DOWN        │ Claude API unreachable at startup probe      │
# │  15 │ ERR_CASCADE_ABORT   │ Consecutive story failures exceeded fan-out  │
# │ 130 │ (signal)            │ Interrupted by SIGINT (Ctrl-C) — shell std   │
# └─────┴─────────────────────┴──────────────────────────────────────────────┘
readonly ERR_BAD_USAGE=2
readonly ERR_CONFIG=3
readonly ERR_MISSING_DEP=4
readonly ERR_PRD_NOT_FOUND=5
readonly ERR_PRD_CORRUPT=6
readonly ERR_SCHEMA_VERSION=7
readonly ERR_COST_CEILING=8
readonly ERR_ZERO_PROGRESS=9
readonly ERR_REPLAY_FAILED=10
readonly ERR_STORY_NOT_FOUND=11
readonly ERR_ROLLBACK_FAILED=12
readonly ERR_MAX_ITERS=13
readonly ERR_API_DOWN=14
readonly ERR_CASCADE_ABORT=15

# ── Memory guard — cap V8 heap to prevent OOM on 16 GB machines ─────────────
# Each Claude CLI (Node.js) can consume 4 GB+ uncapped; with multiple processes
# running (research + ralph + main session), this exceeds available RAM.
# --max-old-space-size caps old generation heap. --max-semi-space-size=4 reduces
# new space (default 16MB → 4MB), trading more frequent but shorter GC pauses
# for lower total memory. Together they keep per-process RSS to ~1.3-1.5x heap.
# Note: --max-heap-size and --optimize-for-size are NOT valid in NODE_OPTIONS.
# Capture original NODE_OPTIONS before overriding (for warning below)
_ORIG_NODE_OPTIONS="${NODE_OPTIONS:-}"
SPIRAL_V8_FLAGS="--max-old-space-size=${SPIRAL_MEMORY_LIMIT:-1024} --max-semi-space-size=4"
export NODE_OPTIONS="$SPIRAL_V8_FLAGS"

# ── Warn if global NODE_OPTIONS had a high heap limit that we're overriding ──
_PREV_HEAP=$(echo "$_ORIG_NODE_OPTIONS" | grep -oP '(?<=--max-old-space-size=)\d+' || true)
if [[ -n "$_PREV_HEAP" && "$_PREV_HEAP" -gt 4096 ]]; then
  echo "  [memory] WARNING: Global NODE_OPTIONS had --max-old-space-size=${_PREV_HEAP}"
  echo "  [memory]   → This gives your main Claude Code session up to ~$(((_PREV_HEAP * 13) / 10))MB RSS"
  echo "  [memory]   → Consider reducing to 4096 in your shell profile to free RAM for workers"
fi

# ── Resolve SPIRAL_HOME (where this script + lib/ live) ─────────────────────
SPIRAL_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Generate a unique run ID for log correlation ──────────────────────────────
SPIRAL_RUN_ID=$(uuidgen 2>/dev/null || printf '%x%x' "$(date +%s)" "$RANDOM")
export SPIRAL_RUN_ID

# ── Argument parsing ─────────────────────────────────────────────────────────
source "$SPIRAL_HOME/lib/core/parse_args.sh"
parse_spiral_args "$@"

# ── Configuration ─────────────────────────────────────────────────────────────
source "$SPIRAL_HOME/lib/core/config.sh"
load_spiral_config
setup_color_output
source "$SPIRAL_HOME/lib/ui/banners.sh"

# Scratch directory in project root
SCRATCH_DIR="$REPO_ROOT/.spiral"
PRD_FILE="$REPO_ROOT/prd.json"
CHECKPOINT_FILE="$SCRATCH_DIR/_checkpoint.json"
RESEARCH_CACHE_DIR="$SCRATCH_DIR/research_cache"

# ── --prd override: resolve absolute path and update derived paths ────────────
if [[ -n "$SPIRAL_CLI_PRD" ]]; then
  _PRD_DIR="$(cd "$(dirname "$SPIRAL_CLI_PRD")" 2>/dev/null && pwd)" || {
    echo "[spiral] ERROR: --prd directory does not exist: $(dirname "$SPIRAL_CLI_PRD")"
    exit $ERR_PRD_NOT_FOUND
  }
  PRD_FILE="$_PRD_DIR/$(basename "$SPIRAL_CLI_PRD")"
  REPO_ROOT="$_PRD_DIR"
  SCRATCH_DIR="$REPO_ROOT/.spiral"
  CHECKPOINT_FILE="$SCRATCH_DIR/_checkpoint.json"
  RESEARCH_CACHE_DIR="$SCRATCH_DIR/research_cache"
fi

# ── --reset: remove checkpoint and start fresh ───────────────────────────────
if [[ "$RESET_CHECKPOINT" -eq 1 ]] && [[ -f "$CHECKPOINT_FILE" ]]; then
  echo "[spiral] --reset: Removing checkpoint, starting fresh from iteration 1"
  rm -f "$CHECKPOINT_FILE"
fi

# ── Generate SPIRAL_RUN_ID for correlation across all logs ────────────────────
# UUID for filtering entries from a single run when multiple SPIRAL runs share
# the same spiral_events.jsonl or results.tsv file.
SPIRAL_RUN_ID=$(uuidgen 2>/dev/null || printf '%x%x' "$(date +%s)" "$RANDOM")
export SPIRAL_RUN_ID

# ── OTel GenAI trace context (US-184) ────────────────────────────────────────
# Emit root invoke_agent span and set TRACEPARENT for child phase spans.
# Silently skipped if otel_spans.py is missing or Python unavailable.
_OTEL_TP=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" begin-run \
  --run-id "$SPIRAL_RUN_ID" --scratch-dir "$SCRATCH_DIR" 2>/dev/null || true)
[[ -n "$_OTEL_TP" ]] && export TRACEPARENT="$_OTEL_TP"
unset _OTEL_TP

# ── US-189: Start Prometheus metrics scrape endpoint if SPIRAL_PROM_PORT set ──
if [[ -n "${SPIRAL_PROM_PORT:-}" ]] && [[ "${SPIRAL_PROM_PORT}" =~ ^[0-9]+$ ]]; then
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_metrics.py" serve-prometheus \
    --port "$SPIRAL_PROM_PORT" --scratch-dir "$SCRATCH_DIR" &>/dev/null &
  _PROM_PID=$!
  disown "$_PROM_PID" 2>/dev/null || true
fi

# ── Source memory pressure helper library ────────────────────────────────────
export SPIRAL_SCRATCH_DIR="$SCRATCH_DIR"
source "$SPIRAL_HOME/lib/memory-pressure-check.sh"

source "$SPIRAL_HOME/lib/core/deps.sh"
resolve_jq

# ── Source structured error taxonomy (US-273) ─────────────────────────────────
source "$SPIRAL_HOME/lib/spiral_errors.sh"

# ── Prerequisite checks ───────────────────────────────────────────────────────
if [[ ! -f "$PRD_FILE" ]]; then
  spiral_exit E501 "$PRD_FILE"
fi
if [[ ! -f "$SPIRAL_RALPH" ]]; then
  spiral_exit E103 "ralph.sh not found at $SPIRAL_RALPH"
fi

# ── Early-exit mode dispatch ──────────────────────────────────────────────
source "$SPIRAL_HOME/lib/modes/mode_early_exit.sh"
dispatch_early_exit_modes

# ── Source verification libraries (before doctor check) ─────────────────────
source "$SPIRAL_HOME/lib/validate_preflight.sh"
source "$SPIRAL_HOME/lib/spiral_doctor.sh"
source "$SPIRAL_HOME/lib/spiral_assert.sh"
source "$SPIRAL_HOME/lib/spiral_retry.sh"
source "$SPIRAL_HOME/lib/phases/phase_s_story_validate.sh"
source "$SPIRAL_HOME/lib/phases/phase_e_enrich.sh"
source "$SPIRAL_HOME/lib/phases/phase_t_test_synth.sh"
source "$SPIRAL_HOME/lib/phases/phase_0_clarify.sh"
source "$SPIRAL_HOME/lib/phases/phase_m_merge.sh"
source "$SPIRAL_HOME/lib/phases/phase_i_implement.sh"
source "$SPIRAL_HOME/lib/phases/phase_v_validate.sh"
source "$SPIRAL_HOME/lib/phases/phase_c_check_done.sh"
source "$SPIRAL_HOME/lib/modes/mode_replay.sh"
source "$SPIRAL_HOME/lib/plugin_system.sh"
source "$SPIRAL_HOME/lib/crash_capture.sh"
source "$SPIRAL_HOME/lib/startup_checks.sh"
source "$SPIRAL_HOME/lib/phases/phase_r_research.sh"
source "$SPIRAL_HOME/lib/phases/phase_rt_parallel.sh"

# ── --doctor: run dependency checks and exit ────────────────────────────────
if [[ "$DOCTOR_MODE" -eq 1 ]]; then
  spiral_doctor
  exit $?
fi

# ── Tee all output to log file ──────────────────────────────────────────────
mkdir -p "$SCRATCH_DIR"

# ── US-347: Enable git rerere for automatic conflict resolution replay ───────
# rerere records conflict resolutions so identical future conflicts in worker
# branches (especially prd.json, results.tsv) are auto-replayed without manual
# intervention. autoupdate auto-stages the replayed resolution.
git -C "$REPO_ROOT" config rerere.enabled true 2>/dev/null || true
git -C "$REPO_ROOT" config rerere.autoupdate true 2>/dev/null || true
# Install post-merge hook for rerere replay logging (non-destructive: skips if
# a user-provided post-merge hook already exists)
_PM_HOOK="$REPO_ROOT/.git/hooks/post-merge"
_PM_SRC="$SPIRAL_HOME/lib/hooks/post-merge"
if [[ ! -f "$_PM_HOOK" && -f "$_PM_SRC" ]]; then
  cp "$_PM_SRC" "$_PM_HOOK"
  chmod +x "$_PM_HOOK" 2>/dev/null || true
fi

# ── US-279: Prune old crash files on startup ─────────────────────────────────
prune_old_crashes

# ── Log rotation (before opening tee fd) ─────────────────────────────────────
source "$SPIRAL_HOME/lib/util/log_rotation.sh"
rotate_spiral_log

exec > >(tee "$_LOG_FILE") 2>&1
if [[ "$_LOG_ROTATED" -eq 1 ]]; then
  echo "# [spiral] Log rotated at $(date -u +%Y-%m-%dT%H:%M:%SZ) (previous log: $(basename "${_LOG_FILE}.1"))"
fi

# ── Gemini pre-analysis cache: clean up from previous runs ──────────────────
_GEMINI_CACHE_DIR="$SCRATCH_DIR/gemini-cache"
if [[ -d "$_GEMINI_CACHE_DIR" ]]; then
  rm -rf "$_GEMINI_CACHE_DIR"
fi

# ── Pre-flight validation ──────────────────────────────────────────────────
spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"

# ── PRD acceptance-criteria lint (US-209) ─────────────────────────────────
echo "  [preflight] Linting prd.json for missing acceptanceCriteria..."
_PRD_LINT_RC=0
"$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/prd_lint.py" "$PRD_FILE" \
  --events-file "${SCRATCH_DIR}/spiral_events.jsonl" 2>&1 || _PRD_LINT_RC=$?
if [[ "$_PRD_LINT_RC" -ne 0 ]]; then
  echo "  [prd-lint] FATAL: Stories missing acceptanceCriteria (SPIRAL_STRICT_AC=true) — aborting."
  exit "$_PRD_LINT_RC"
fi

# ── Prompt injection scan ──────────────────────────────────────────────────
echo "  [preflight] Scanning story fields for prompt injection patterns..."
_INJECTION_FLAGS=("--prd" "$PRD_FILE" "--audit-log" "$SCRATCH_DIR/security-audit.jsonl" "--update-prd")
[[ "${ALLOW_UNSAFE_STORIES:-0}" -eq 1 ]] && _INJECTION_FLAGS+=("--allow-unsafe")
_INJECT_RC=0
"$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/security/injection_detector.py" "${_INJECTION_FLAGS[@]}" 2>&1 || _INJECT_RC=$?
if [[ "$_INJECT_RC" -eq 2 ]]; then
  echo "  [preflight] FATAL: Prompt injection patterns detected in story fields — aborting."
  echo "  [preflight] Use --allow-unsafe-stories to warn-only and continue (not recommended)."
  exit "$_INJECT_RC"
fi
echo "  [preflight] Injection scan: OK"

# ── Checkpoint completeness check (US-250) ────────────────────────────────
# Helper function: verify checkpoint has all required state fields
check_checkpoint_completeness() {
  local ckpt_file="$1"
  local phase story_id retry_count

  # Check that phase, storyId, retryCount are all present and non-empty
  phase=$("$JQ" -r '.phase // empty' "$ckpt_file" 2>/dev/null || true)
  story_id=$("$JQ" -r '.storyId // empty' "$ckpt_file" 2>/dev/null || true)
  retry_count=$("$JQ" -r '.retryCount // empty' "$ckpt_file" 2>/dev/null || true)

  if [[ -z "$phase" || -z "$story_id" || -z "$retry_count" ]]; then
    echo "  [checkpoint-completeness] INCOMPLETE: phase=$([[ -n "$phase" ]] && echo "✓" || echo "✗"), storyId=$([[ -n "$story_id" ]] && echo "✓" || echo "✗"), retryCount=$([[ -n "$retry_count" ]] && echo "✓" || echo "✗")"
    return 1
  fi

  return 0
}

# ── US-325: Idempotency guard — skip story if matching commit already exists ──
# Before invoking ralph for a story, check git log for a commit containing the
# story ID. If found (and not a Revert commit), mark the story passed and skip.
# Returns 0 if story should be SKIPPED (already implemented), 1 if ralph should run.
check_idempotency_guard() {
  local story_id="$1"
  local prd_file="$2"

  # Fast path: git log --grep with --max-count=1 adds <100ms overhead
  local existing_sha
  existing_sha=$(git -C "$REPO_ROOT" log --grep="$story_id" --max-count=1 --format=%H 2>/dev/null || echo "")

  if [[ -z "$existing_sha" ]]; then
    return 1 # No matching commit — proceed with ralph
  fi

  # Skip if the matching commit is a revert (avoid false positives)
  local commit_subject
  commit_subject=$(git -C "$REPO_ROOT" log -1 --format=%s "$existing_sha" 2>/dev/null || echo "")
  if [[ "$commit_subject" == Revert* ]]; then
    return 1 # Revert commit — proceed with ralph
  fi

  # Mark story as passed with _passedCommit
  echo "  [idempotency] Story $story_id already implemented in commit ${existing_sha:0:8} — skipping"
  "$JQ" --arg id "$story_id" --arg sha "$existing_sha" \
    '(.userStories[] | select(.id == $id)) |= (.passes = true | ._passedCommit = $sha)' \
    "$prd_file" >"${prd_file}.tmp" && mv "${prd_file}.tmp" "$prd_file"

  # Log to spiral_events.jsonl
  log_spiral_event "idempotency_skip" \
    "\"story_id\":\"$story_id\",\"commit_sha\":\"$existing_sha\",\"iteration\":${SPIRAL_ITER:-0}"

  return 0 # Story already implemented — skip ralph
}

# ── Checkpoint state machine coherence check ──────────────────────────────
if [[ -f "$CHECKPOINT_FILE" ]]; then
  if ! "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/core/state_machine.py" validate-phases --checkpoint "$CHECKPOINT_FILE"; then
    echo "  [checkpoint] WARNING: Corrupt checkpoint detected — removing and starting fresh from iter 1"
    rm -f "$CHECKPOINT_FILE"
  elif ! check_checkpoint_completeness "$CHECKPOINT_FILE"; then
    echo "  [checkpoint] WARNING: Incomplete checkpoint detected — removing and starting fresh from iter 1"
    rm -f "$CHECKPOINT_FILE"
  fi
fi

# ── Load SPIRAL plugin system (US-193) ─────────────────────────────────────────
echo "  [plugin] Loading SPIRAL plugin system..."
load_plugins "$SPIRAL_HOME"
if [[ ${#PLUGINS[@]} -gt 0 ]]; then
  echo "  [plugin] Loaded ${#PLUGINS[@]} plugin(s)"
fi

SESSION_START=$(date +%s)

# ── Time limit ────────────────────────────────────────────────────────────────
SESSION_DEADLINE=0
if [[ "$TIME_LIMIT_MINS" -gt 0 ]]; then
  SESSION_DEADLINE=$((SESSION_START + TIME_LIMIT_MINS * 60))
fi

# ── Signal trap state ─────────────────────────────────────────────────────────
WATCHDOG_PID=""
PHASE=""               # Current phase (R, T, M, G, I, V, C)
_ACTIVE_STORY_ID=""    # US-311: story currently being implemented (populated in Phase I)
_ACTIVE_STORY_TITLE="" # US-311: title of the active story
CHILD_PIDS=()          # Track explicitly spawned child processes

# ── Signal handlers, cleanup, and memory watchdog ─────────────────────────
source "$SPIRAL_HOME/lib/core/signal_handlers.sh"
install_signal_traps
launch_memory_watchdog

# ── Backup prd.json before any modifications ────────────────────────────────
cp "$PRD_FILE" "${PRD_FILE}.bak"
echo "[spiral] Backup: ${PRD_FILE}.bak"

source "$SPIRAL_HOME/lib/core/helpers.sh"

# write_iter_summary — moved to lib/spiral_helpers.sh

# _write_empty_test_output — moved to lib/spiral_helpers.sh

# write_checkpoint — moved to lib/spiral_helpers.sh

# ── Helper: append a structured JSONL event to .spiral/spiral_events.jsonl ──
# Provided by lib/spiral_events.sh (sourced below). See that file for details.
source "$SPIRAL_HOME/lib/spiral_events.sh"
source "$SPIRAL_HOME/lib/spiral_helpers.sh"
source "$SPIRAL_HOME/lib/modes/mode_ops.sh"

# notify_webhook — moved to lib/spiral_helpers.sh

# run_phase_hook — moved to lib/spiral_helpers.sh

# checkpoint_phase_done — moved to lib/spiral_helpers.sh

# run_sast_gate_check — moved to lib/spiral_helpers.sh

# scan_web_content — moved to lib/spiral_helpers.sh

# build_research_prompt — moved to lib/spiral_helpers.sh

# ── Startup checks (memory, dirty worktrees, cache invalidation) ──────────
run_startup_checks

source "$SPIRAL_HOME/lib/ui/splash.sh"
print_spiral_splash
register_spiral_ui

handle_replay_mode

# ── --benchmark, --rollback, --undo mode handlers (lib/modes/mode_ops.sh) ────
handle_benchmark_mode
handle_rollback_mode
handle_undo_mode


# ── Startup: initialize counters and resume from checkpoint if available ────
ZERO_PROGRESS_COUNT=0
SPIRAL_ITER=0

export SPIRAL_FOCUS
export SPIRAL_FOCUS_TAGS
export SPIRAL_ITER
export SPIRAL_MAX_RESEARCH_STORIES
export SPIRAL_SKIP_STORY_IDS
export NO_CASCADE_SKIP
export DRY_RUN
export ALLOW_UNSAFE_STORIES
export SPIRAL_ALLOW_EXEC_WRITES="${ALLOW_EXEC_WRITES}"

if [[ -f "$CHECKPOINT_FILE" ]]; then
  CKPT_ITER=$("$JQ" -r '.iter // 0' "$CHECKPOINT_FILE")
  CKPT_PHASE=$("$JQ" -r '.phase // ""' "$CHECKPOINT_FILE")
  echo "  [checkpoint] Resuming from iter=$CKPT_ITER phase=$CKPT_PHASE"
  SPIRAL_ITER=$((CKPT_ITER - 1)) # loop will increment to CKPT_ITER on first pass
  # Restore run_id from checkpoint so all events share the same correlation ID
  CKPT_RUN_ID=$("$JQ" -r '.run_id // ""' "$CHECKPOINT_FILE" 2>/dev/null || echo "")
  if [[ -n "$CKPT_RUN_ID" ]]; then
    SPIRAL_RUN_ID="$CKPT_RUN_ID"
    export SPIRAL_RUN_ID
  fi

  # ── Warn if checkpoint is older than 24 hours ────────────────────────────
  CKPT_TS=$("$JQ" -r '.ts // 0' "$CHECKPOINT_FILE" 2>/dev/null || echo 0)
  CKPT_AGE=$(($(date +%s) - ${CKPT_TS%.*}))
  if [[ "$CKPT_AGE" -gt 86400 ]]; then
    CKPT_AGE_HOURS=$((CKPT_AGE / 3600))
    echo "  [spiral] WARNING: Resuming from checkpoint written ${CKPT_AGE_HOURS}h ago. Pass --reset to start fresh." >&2
  fi

  # ── Warn if SPIRAL version changed since checkpoint was written ───────────
  CKPT_SPIRAL_VERSION=$("$JQ" -r '.spiralVersion // ""' "$CHECKPOINT_FILE" 2>/dev/null || echo "")
  if [[ -n "$CKPT_SPIRAL_VERSION" && "$CKPT_SPIRAL_VERSION" != "${SPIRAL_VERSION:-unknown}" ]]; then
    echo "  [checkpoint] WARNING: checkpoint written by SPIRAL $CKPT_SPIRAL_VERSION, current is ${SPIRAL_VERSION:-unknown}" >&2
  fi

  echo ""
fi

source "$SPIRAL_HOME/lib/util/progress_init.sh"
init_progress_file

# ── Stale story detection at loop startup (US-129) ───────────────────────────
# Warn for any pending story with last_attempted older than SPIRAL_STALE_DAYS
_STALE_DAYS_CHECK="${SPIRAL_STALE_DAYS:-7}"
_STALE_STORIES=$(
  "$SPIRAL_PYTHON" - "$PRD_FILE" "$_STALE_DAYS_CHECK" 2>/dev/null <<'_STALE_PY'
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
            age_days = age.days
            print(f"{s['id']}|{age_days}|{ts_raw[:19]}|{s.get('title', '')[:60]}")
    except (ValueError, TypeError):
        pass
_STALE_PY
) || true

if [[ -n "$_STALE_STORIES" ]]; then
  echo ""
  echo "  [spiral] WARNING: Stale stories detected (inactive > ${_STALE_DAYS_CHECK} days):"
  while IFS='|' read -r _sid _age_days _ts _title; do
    [[ -z "$_sid" ]] && continue
    echo "    [$_sid] ${_age_days}d inactive (last: $_ts) — $_title"
    log_spiral_event "story_stale_detected" \
      "\"storyId\":\"$_sid\",\"stale_days\":$_age_days,\"last_attempted\":\"$_ts\",\"threshold_days\":$_STALE_DAYS_CHECK" 2>/dev/null || true
  done <<<"$_STALE_STORIES"
  echo ""
fi

# ── Phase 0: CLARIFY — one-time interactive session before the loop ──────────
# Skipped when --gate proceed|skip is passed, or when resuming from checkpoint.
run_phase_clarify

# Recalculate session deadline in case TIME_LIMIT_MINS was set by Phase 0
if [[ "${TIME_LIMIT_MINS:-0}" -gt 0 && "$SESSION_DEADLINE" -eq 0 ]]; then
  SESSION_DEADLINE=$((SESSION_START + TIME_LIMIT_MINS * 60))
fi

# ── Main SPIRAL loop ────────────────────────────────────────────────────────
while [[ $SPIRAL_ITER -lt $MAX_SPIRAL_ITERS ]]; do
  SPIRAL_ITER=$((SPIRAL_ITER + 1))
  ITER_START=$(date +%s)

  # Compress artifacts from iterations N-2 and older (US-172)
  compress_old_artifacts "$SPIRAL_ITER"

  # Recover incomplete transactions from a prior crash (Phase 3 safety)
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/resilience/txn_journal.py" recover \
    --journal "$SCRATCH_DIR/_txn_journal.jsonl" 2>/dev/null || true

  # Validate prd.json integrity before each iteration (Idea 3)
  # If corrupted by a mid-write crash, restore from the most recent backup
  if ! "$JQ" empty "$PRD_FILE" 2>/dev/null; then
    echo "  [spiral] WARNING: prd.json is invalid JSON — attempting restore from backup"
    _LATEST_BACKUP=$(ls -t "$SCRATCH_DIR/prd-backups/prd-iter"*.json 2>/dev/null | head -1 || true)
    if [[ -n "$_LATEST_BACKUP" && -f "$_LATEST_BACKUP" ]]; then
      cp "$_LATEST_BACKUP" "$PRD_FILE"
      echo "  [spiral] Restored prd.json from: $(basename "$_LATEST_BACKUP")"
    else
      spiral_exit E502 "No backup available — cannot recover prd.json"
    fi
  fi

  prd_stats
  ADDED=0               # new stories added this iter (set in Phase M; default 0 if skipped)
  RALPH_RAN=0           # set to 1 if ralph actually executed this iter (controls Phase V)
  RALPH_PROGRESS=0      # stories completed this iter; reset each iter for accurate velocity
  PRE_RALPH_PRD_JSON="" # snapshot of prd.json before Phase I; used by Phase V incremental (US-131)
  _PASSES_BEFORE_I=-1   # passed-story count snapshot before Phase I (US-183)
  _PASSES_AFTER_I=-1    # passed-story count snapshot after Phase I (US-183)
  _PHASE_V_SKIPPED=0    # 1 when Phase V is skipped due to no new passes (US-183)
  # Phase duration tracking (US-046): reset per-iteration, updated at each phase_end
  _PHASE_DUR_R=0
  _PHASE_DUR_T=0
  _PHASE_DUR_RT_WALL=0
  _PHASE_DUR_M=0
  _PHASE_DUR_I=0
  _PHASE_DUR_V=0
  _PHASE_DUR_C=0
  echo ""
  echo "  ┌─────────────────────────────────────────────────────┐"
  echo "  │  SPIRAL Iteration $SPIRAL_ITER / $MAX_SPIRAL_ITERS"
  echo "  │  Stories: $DONE/$TOTAL complete ($PENDING pending)"
  echo "  └─────────────────────────────────────────────────────┘"

  # ── Cost ceiling guard ─────────────────────────────────────────────────────
  if [[ -n "$SPIRAL_COST_CEILING" && -f "$REPO_ROOT/results.tsv" ]]; then
    _COST_RC=0
    _COST_OUTPUT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/cost_check.py" \
      --results "$REPO_ROOT/results.tsv" --ceiling "$SPIRAL_COST_CEILING" 2>&1) || _COST_RC=$?
    echo "$_COST_OUTPUT"
    if [[ "$_COST_RC" -eq 2 ]]; then
      echo ""
      echo "  ╔══════════════════════════════════════════════════════╗"
      echo "  ║  SPIRAL stopped: cost ceiling reached (\$${SPIRAL_COST_CEILING})  ║"
      echo "  ╚══════════════════════════════════════════════════════╝"
      spiral_exit E104 "$SPIRAL_COST_CEILING"
    fi
  fi

  # ── Capacity guard → skip Phase R only when over capacity ────────────────
  OVER_CAPACITY=0
  if [[ "$PENDING" -gt "$CAPACITY_LIMIT" ]]; then
    OVER_CAPACITY=1
    echo ""
    echo "  [CAPACITY] $PENDING pending stories exceed limit of $CAPACITY_LIMIT."
    echo "  [CAPACITY] Skipping Phase R only (no web research for new stories) — T/M still run to catch regressions."
  fi

  # ── Phase A: AI STORY SUGGESTIONS ──────────────────────────────────────────
  # Runs once per iteration before Phase R.
  # Source 2: consumes Phase 0-D ai-example queue + PRD gap analysis → _ai_suggest_output.json
  # Source 5: analyzes passed stories → _test_story_candidates.json (test stories for Ralph to implement)
  AI_SUGGEST_OUTPUT="$SCRATCH_DIR/_ai_suggest_output.json"
  TEST_STORY_CANDIDATES="$SCRATCH_DIR/_test_story_candidates.json"
  AI_QUEUE_FILE="$SCRATCH_DIR/_ai_example_queue.json"
  print_phase_banner "A" "AI SUGGESTIONS — generating per-iteration story candidates..."
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research/ai_suggest.py" \
    --prd "$PRD_FILE" \
    --queue "$AI_QUEUE_FILE" \
    --out "$AI_SUGGEST_OUTPUT" \
    --focus "${SPIRAL_FOCUS:-}" \
    --max-suggest "$SPIRAL_MAX_AI_SUGGEST" \
    --clear-queue || true
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research/generate_test_stories.py" \
    --prd "$PRD_FILE" \
    --out "$TEST_STORY_CANDIDATES" \
    --min-complexity "$SPIRAL_TEST_STORY_MIN_COMPLEXITY" || true

  # ── Record goals hash before Phase R (US-323: goal-hijack detection) ──────
  _GOALS_HASH_FILE="$SCRATCH_DIR/_goals_hash"
  _GOALS_SNAPSHOT_FILE="$SCRATCH_DIR/_goals_before.json"
  _GOALS_HIJACK_ABORT=0
  if [[ -f "$PRD_FILE" ]]; then
    "$JQ" -S '.goals // []' "$PRD_FILE" >"$_GOALS_SNAPSHOT_FILE" 2>/dev/null
    sha256sum "$_GOALS_SNAPSHOT_FILE" | awk '{print $1}' >"$_GOALS_HASH_FILE"
  fi

  # ── Phase R + T: RESEARCH and TEST SYNTHESIS (parallel) ──────────────────
  run_phase_rt_parallel || continue

  run_phase_s || continue
  run_phase_enrichment

  run_phase_merge || continue

  run_phase_gate_and_implement || continue

  run_phase_validate || continue

  run_phase_check_done
  echo "  [C] Looping back to Phase R"
  echo ""
done

# ── Max iterations reached ──────────────────────────────────────────────────
prd_stats
echo ""
echo "  ╔══════════════════════════════════════════════════════╗"
echo "  ║  SPIRAL reached max iterations ($MAX_SPIRAL_ITERS)           ║"
echo "  ║  Stories: $DONE/$TOTAL complete ($PENDING pending)   ║"
echo "  ║  Run again to continue: bash spiral.sh 20            ║"
echo "  ╚══════════════════════════════════════════════════════╝"

if [[ -f "$REPO_ROOT/results.tsv" ]]; then
  echo ""
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/spiral_report.py" --results "$REPO_ROOT/results.tsv" 2>/dev/null || true
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/ui/spiral_dashboard.py" \
    --prd "$PRD_FILE" --results "$REPO_ROOT/results.tsv" \
    --retries "$REPO_ROOT/retry-counts.json" --progress "$REPO_ROOT/progress.txt" \
    --output "$SCRATCH_DIR/dashboard.html" --open 2>/dev/null || true
fi

SESSION_END=$(date +%s)
SESSION_MINUTES=$(((SESSION_END - SESSION_START) / 60))
echo "  Session: ${SESSION_MINUTES}m total, $SPIRAL_ITER iterations"

# ── Emit OTel root span on max-iters exit (US-184) ───────────────────────────
"$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-run \
  --passes "${DONE:-0}" --story-count "${TOTAL:-0}" 2>/dev/null || true

spiral_exit E404 "$MAX_SPIRAL_ITERS"

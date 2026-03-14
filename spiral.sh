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
MAX_SPIRAL_ITERS=20
GATE_DEFAULT="" # empty = interactive; "proceed"|"skip"|"quit" = auto
STATUS_ONLY=0   # 1 = print session state and exit (--status)
RALPH_MAX_ITERS=120
SKIP_RESEARCH=0       # 1 = skip Phase R (Claude web research); T and M still run
RALPH_WORKERS=1       # >1 = parallel mode (git worktrees + docker lock)
WORKERS_EXPLICIT=0    # 1 = user passed --ralph-workers explicitly
CAPACITY_LIMIT=50     # Phase R is skipped when PENDING exceeds this threshold
MONITOR_TERMINALS=1   # 1 = open a terminal window per worker to tail logs
SPIRAL_CONFIG_PATH="" # explicit --config path
SPIRAL_CLI_PRD=""     # explicit --prd path override
SPIRAL_CLI_MODEL=""   # explicit --model override (haiku|sonnet|opus)
SPIRAL_CLI_FOCUS=""   # explicit --focus override
SPIRAL_FOCUS_TAGS=""  # comma-separated tags filter (--focus-tags)
TIME_LIMIT_MINS=0     # 0 = no limit; >0 = stop after N minutes (--time-limit or --until)
DRY_RUN=0             # 1 = dry-run mode: skip API calls (R, T, I, V) but run control flow
DOCTOR_MODE=0         # 1 = run dependency check and exit (--doctor)
REPLAY_STORY_ID=""    # "" = normal mode; "US-XXX" = replay that story only (--replay)
RESET_CHECKPOINT=0    # 1 = remove _checkpoint.json and start fresh (--reset)
MIGRATE_MODE=0        # 1 = run prd.json schema migration and exit (--migrate)
ARCHIVE_MODE=0        # 1 = archive completed stories and exit (--archive-done)
CHANGELOG_MODE=0      # 1 = generate CHANGELOG.md via git-cliff and exit (--changelog)

while [[ $# -gt 0 ]]; do
  case $1 in
    --gate)
      GATE_DEFAULT="$2"
      shift 2
      ;;
    --ralph-iters)
      RALPH_MAX_ITERS="$2"
      shift 2
      ;;
    --skip-research)
      SKIP_RESEARCH=1
      shift
      ;;
    --ralph-workers)
      RALPH_WORKERS="$2"
      WORKERS_EXPLICIT=1
      shift 2
      ;;
    --capacity-limit)
      CAPACITY_LIMIT="$2"
      shift 2
      ;;
    --monitor)
      MONITOR_TERMINALS=1
      shift
      ;;
    --no-monitor)
      MONITOR_TERMINALS=0
      shift
      ;;
    --prd)
      SPIRAL_CLI_PRD="$2"
      shift 2
      ;;
    --config)
      SPIRAL_CONFIG_PATH="$2"
      shift 2
      ;;
    --model)
      SPIRAL_CLI_MODEL="$2"
      shift 2
      ;;
    --focus)
      SPIRAL_CLI_FOCUS="$2"
      shift 2
      ;;
    --focus-tags)
      SPIRAL_FOCUS_TAGS="$2"
      shift 2
      ;;
    --time-limit)
      TIME_LIMIT_MINS="$2"
      shift 2
      ;;
    --until)
      # Parse HH:MM and compute minutes remaining from now
      _TARGET="$2"
      shift 2
      _NOW_H=$(date +%-H 2>/dev/null || date +%H | sed 's/^0//')
      _NOW_M=$(date +%-M 2>/dev/null || date +%M | sed 's/^0//')
      _NOW_H=${_NOW_H:-0}
      _NOW_M=${_NOW_M:-0}
      _TARGET_H=$(echo "$_TARGET" | cut -d: -f1 | sed 's/^0*//')
      _TARGET_H=${_TARGET_H:-0}
      _TARGET_M=$(echo "$_TARGET" | cut -d: -f2 | sed 's/^0*//')
      _TARGET_M=${_TARGET_M:-0}
      _NOW_TOTAL=$((_NOW_H * 60 + _NOW_M))
      _TARGET_TOTAL=$((_TARGET_H * 60 + _TARGET_M))
      [[ "$_TARGET_TOTAL" -le "$_NOW_TOTAL" ]] && _TARGET_TOTAL=$((_TARGET_TOTAL + 1440))
      TIME_LIMIT_MINS=$((_TARGET_TOTAL - _NOW_TOTAL))
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --doctor)
      DOCTOR_MODE=1
      shift
      ;;
    --replay)
      REPLAY_STORY_ID="$2"
      shift 2
      ;;
    --reset)
      RESET_CHECKPOINT=1
      shift
      ;;
    --migrate)
      MIGRATE_MODE=1
      shift
      ;;
    --archive-done)
      ARCHIVE_MODE=1
      shift
      ;;
    --changelog)
      CHANGELOG_MODE=1
      shift
      ;;
    --version)
      _SPIRAL_VERSION_STR=$(git -C "$SPIRAL_HOME" describe --tags --always --dirty=+ 2>/dev/null || echo "")
      if [[ -z "$_SPIRAL_VERSION_STR" ]]; then
        echo "SPIRAL version unknown (not a git repository)"
      else
        echo "SPIRAL version $_SPIRAL_VERSION_STR"
      fi
      exit 0
      ;;
    --status)
      STATUS_ONLY=1
      shift
      ;;
    --help | -h)
      echo "SPIRAL — Self-iterating PRD Research & Implementation Autonomous Loop"
      echo ""
      echo "Usage: bash spiral.sh [max_iters] [options]"
      echo ""
      echo "Options:"
      echo "  --gate proceed|skip|quit   Auto-answer gate prompts (default: interactive)"
      echo "  --ralph-iters N            Max inner implementation iterations (default: 120)"
      echo "  --ralph-workers N          Parallel worktree workers (default: 1)"
      echo "  --skip-research            Skip Phase R (web research)"
      echo "  --capacity-limit N         Skip Phase R when pending > N (default: 50)"
      echo "  --monitor                  Open terminal per worker (default: on)"
      echo "  --no-monitor               Disable per-worker terminals"
      echo "  --model haiku|sonnet|opus  Claude model override (default: auto-route by story complexity)"
      echo "  --focus TEXT               Focus iteration on a theme (e.g., 'performance', 'security')"
      echo "  --focus-tags TAG,TAG       Only implement stories matching at least one tag (e.g., 'frontend,auth')"
      echo "  --prd PATH                 Path to prd.json (default: prd.json in current directory)"
      echo "  --config PATH              Path to spiral.config.sh (default: \$REPO_ROOT/spiral.config.sh)"
      echo "  --time-limit N             Stop after N minutes (e.g., 60, 90, 120)"
      echo "  --until HH:MM              Stop at a wall-clock time (e.g., 14:30, 18:00)"
      echo "  --dry-run                  Test loop control flow without API calls"
      echo "  --doctor                   Check all runtime dependencies and exit"
      echo "  --replay STORY_ID          Re-run a single story in an isolated worktree (Phases I+V only)"
      echo "  --reset                    Remove checkpoint and start fresh from iteration 1"
      echo "  --migrate                  Migrate prd.json to current schema version and exit"
      echo "  --archive-done             Archive completed stories to prd-archive.json and exit"
      echo "  --changelog                Generate CHANGELOG.md via git-cliff and exit"
      echo "  --status                   Print session state and story counts, then exit"
      echo "  --version                  Print SPIRAL version (git describe) and exit"
      echo ""
      echo "Config: Place spiral.config.sh in project root (or use --config)."
      echo "  See templates/spiral.config.example.sh for all variables."
      echo ""
      echo "Phases per iteration: R(esearch) → T(est synth) → M(erge) → G(ate) → I(mplement) → V(alidate) → C(heck done)"
      exit 0
      ;;
    --*)
      echo "[spiral] Unknown flag: $1"
      exit $ERR_BAD_USAGE
      ;;
    *)
      MAX_SPIRAL_ITERS="$1"
      shift
      ;;
  esac
done

# ── Validate integer CLI arguments ────────────────────────────────────────────
_validate_pos_int() {
  local name="$1" value="$2"
  if [[ ! "$value" =~ ^[1-9][0-9]*$ ]]; then
    echo "Error: $name requires a positive integer, got: '$value'"
    exit $ERR_BAD_USAGE
  fi
}
_validate_non_neg_int() {
  local name="$1" value="$2"
  if [[ ! "$value" =~ ^[0-9]+$ ]]; then
    echo "Error: $name requires a non-negative integer, got: '$value'"
    exit $ERR_BAD_USAGE
  fi
}
_validate_pos_int "max_iters (positional)" "$MAX_SPIRAL_ITERS"
_validate_pos_int "--ralph-iters" "$RALPH_MAX_ITERS"
_validate_pos_int "--ralph-workers" "$RALPH_WORKERS"
_validate_non_neg_int "--capacity-limit" "$CAPACITY_LIMIT"
if [[ "$TIME_LIMIT_MINS" -ne 0 ]] 2>/dev/null; then
  _validate_pos_int "--time-limit" "$TIME_LIMIT_MINS"
fi

# ── Configuration ─────────────────────────────────────────────────────────────
REPO_ROOT="$(pwd)"

# Source project config (with defaults for everything)
_SPIRAL_CONFIG="${SPIRAL_CONFIG_PATH:-$REPO_ROOT/spiral.config.sh}"

# If config doesn't exist, run the interactive setup wizard
if [[ ! -f "$_SPIRAL_CONFIG" ]]; then
  echo "[spiral] No config found. Launching setup wizard..."
  # Use 'uv run python' as a sensible default, since the wizard will configure it.
  uv run python "$SPIRAL_HOME/lib/setup.py"
  # Exit after setup so user can inspect config before first run
  exit 0
fi

if [[ -f "$_SPIRAL_CONFIG" ]]; then
  echo "[spiral] Loading config: $_SPIRAL_CONFIG"
  source "$_SPIRAL_CONFIG"
else
  echo "[spiral] No config found at $_SPIRAL_CONFIG — using defaults"
fi

# Apply config with defaults
SPIRAL_PYTHON="${SPIRAL_PYTHON:-python3}"

# ── spiral-core Rust binary (hot-path replacement for Python scripts) ─────────
# If the binary exists in $SPIRAL_HOME/lib/, use it; else fall back to Python.
# Build with: (cd $SPIRAL_HOME/lib/spiral-core && cargo build --release && cp target/release/spiral-core* $SPIRAL_HOME/lib/)
_SPIRAL_CORE_CANDIDATES=("$SPIRAL_HOME/lib/spiral-core" "$SPIRAL_HOME/lib/spiral-core.exe")
SPIRAL_CORE_BIN=""
for _sc in "${_SPIRAL_CORE_CANDIDATES[@]}"; do
  if [[ -x "$_sc" ]]; then
    SPIRAL_CORE_BIN="$_sc"
    break
  fi
done
[[ -n "$SPIRAL_CORE_BIN" ]] && echo "[spiral] spiral-core: $SPIRAL_CORE_BIN (Rust hot-path active)" || true

SPIRAL_RALPH="${SPIRAL_RALPH:-$SPIRAL_HOME/ralph/ralph.sh}"
SPIRAL_RESEARCH_PROMPT="${SPIRAL_RESEARCH_PROMPT:-$SPIRAL_HOME/templates/research_prompt.example.md}"
SPIRAL_GEMINI_PROMPT="${SPIRAL_GEMINI_PROMPT:-}"
SPIRAL_VALIDATE_CMD="${SPIRAL_VALIDATE_CMD:-$SPIRAL_PYTHON tests/run_tests.py --report-dir test-reports}"
SPIRAL_REPORTS_DIR="${SPIRAL_REPORTS_DIR:-test-reports}"
SPIRAL_STORY_PREFIX="${SPIRAL_STORY_PREFIX:-US}"
SPIRAL_VERSION="${SPIRAL_VERSION:-$(git -C "$SPIRAL_HOME" describe --tags --always --dirty=+ 2>/dev/null || echo "unknown")}"
export SPIRAL_VERSION
STREAM_FMT="${SPIRAL_STREAM_FMT:-$SPIRAL_HOME/ralph/stream-formatter.mjs}"
SPIRAL_MODEL_ROUTING="${SPIRAL_MODEL_ROUTING:-auto}"
SPIRAL_RESEARCH_MODEL="${SPIRAL_RESEARCH_MODEL:-sonnet}"
SPIRAL_FIRECRAWL_ENABLED="${SPIRAL_FIRECRAWL_ENABLED:-0}"
SPIRAL_SPECKIT_CONSTITUTION="${SPIRAL_SPECKIT_CONSTITUTION:-}"
SPIRAL_SPECKIT_SPECS_DIR="${SPIRAL_SPECKIT_SPECS_DIR:-}"
SPIRAL_FOCUS="${SPIRAL_CLI_FOCUS:-${SPIRAL_FOCUS:-}}"
SPIRAL_SKIP_STORY_IDS="${SPIRAL_SKIP_STORY_IDS:-}"              # comma-separated IDs to permanently skip without penalty
SPIRAL_MAX_STORIES="${SPIRAL_MAX_STORIES:-100}"                 # warn threshold for total story count in prd.json
SPIRAL_MAX_STORIES_ABORT="${SPIRAL_MAX_STORIES_ABORT:-0}"       # 0 = warn only; non-zero = fail hard when exceeded
SPIRAL_AUTO_INFER_DEPS="${SPIRAL_AUTO_INFER_DEPS:-false}"       # true = write inferred dep edges to prd.json after Phase M merge
SPIRAL_MAX_PENDING="${SPIRAL_MAX_PENDING:-0}"                   # 0 = unlimited
SPIRAL_MAX_RESEARCH_STORIES="${SPIRAL_MAX_RESEARCH_STORIES:-0}" # 0 = unlimited; cap research candidates per iteration
SPIRAL_STORY_BATCH_SIZE="${SPIRAL_STORY_BATCH_SIZE:-20}"        # 0 = disabled (show all)
SPIRAL_COST_CEILING="${SPIRAL_COST_CEILING:-}"                  # empty = disabled; USD amount to cap spend
SPIRAL_LOW_POWER_MODE="${SPIRAL_LOW_POWER_MODE:-1}"
SPIRAL_PRESSURE_THRESHOLDS="${SPIRAL_PRESSURE_THRESHOLDS:-40,25,18,12}"
SPIRAL_MEMORY_POLL_INTERVAL="${SPIRAL_MEMORY_POLL_INTERVAL:-15}"
SPIRAL_MEMORY_WAIT_MAX_MINS="${SPIRAL_MEMORY_WAIT_MAX_MINS:-0}" # 0 = unlimited while workers active
export SPIRAL_MEMORY_WAIT_MAX_MINS
SPIRAL_PRESSURE_HYSTERESIS="${SPIRAL_PRESSURE_HYSTERESIS:-2}"
SPIRAL_DEV_URL="${SPIRAL_DEV_URL:-}"                                     # empty = disabled; URL for Phase V screenshot
SPIRAL_PROGRESS_MAX_LINES="${SPIRAL_PROGRESS_MAX_LINES:-2000}"           # 0 = disabled; rotate progress.txt when over this limit
SPIRAL_EVENT_LOG_MAX_LINES="${SPIRAL_EVENT_LOG_MAX_LINES:-10000}"        # 0 = disabled; rotate spiral_events.jsonl when over this limit
SPIRAL_RESEARCH_CACHE_TTL_HOURS="${SPIRAL_RESEARCH_CACHE_TTL_HOURS:-24}" # 0 = disabled; cache TTL for Phase R URL responses
RESEARCH_CACHE_DIR=""                                                    # set after SCRATCH_DIR is known
SPIRAL_RESEARCH_TIMEOUT="${SPIRAL_RESEARCH_TIMEOUT:-300}"                # seconds; 0 = disabled (unlimited); Phase R LLM call
SPIRAL_RESEARCH_RETRIES="${SPIRAL_RESEARCH_RETRIES:-2}"                  # retries when _research_output.json missing/invalid after Phase R
SPIRAL_IMPL_TIMEOUT="${SPIRAL_IMPL_TIMEOUT:-600}"                        # seconds; 0 = disabled (unlimited); Phase I ralph call
SPIRAL_VALIDATE_TIMEOUT="${SPIRAL_VALIDATE_TIMEOUT:-300}"                # seconds; 0 = disabled (unlimited)
SPIRAL_TEST_SYNTH_TIMEOUT="${SPIRAL_TEST_SYNTH_TIMEOUT:-60}"             # seconds; 0 = disabled (unlimited); Phase T synthesize_tests timeout
SPIRAL_PREEMPTIVE_PRESSURE_MB="${SPIRAL_PREEMPTIVE_PRESSURE_MB:-0}"      # MB; 0 = disabled; free RAM below this triggers preemptive pressure level 1
SPIRAL_NOTIFY_WEBHOOK="${SPIRAL_NOTIFY_WEBHOOK:-}"                       # HTTPS URL; empty = disabled; POST JSON at each phase start/end
SPIRAL_NOTIFY_WEBHOOK_TIMEOUT="${SPIRAL_NOTIFY_WEBHOOK_TIMEOUT:-5}"      # seconds; max wait per POST (default 5)
SPIRAL_NOTIFY_WEBHOOK_HEADERS="${SPIRAL_NOTIFY_WEBHOOK_HEADERS:-}"       # optional HTTP header, e.g. "Authorization: Bearer TOKEN"

# ── Config validation ─────────────────────────────────────────────────────────
# Validates required keys are set and applies defaults for optional keys.
# Called after defaults block to catch explicitly-emptied required values.
validate_config() {
  local _errors=0
  for key in SPIRAL_PYTHON SPIRAL_VALIDATE_CMD; do
    if [[ -z "${!key:-}" ]]; then
      echo "[config] ERROR: $key must be set in spiral.config.sh"
      _errors=1
    fi
  done
  [[ "$_errors" -eq 1 ]] && exit $ERR_CONFIG

  # Defaults for optional keys (defense-in-depth)
  : "${SPIRAL_MODEL_ROUTING:=auto}"
  : "${SPIRAL_RESEARCH_MODEL:=sonnet}"
  : "${SPIRAL_MAX_PENDING:=50}"
  : "${SPIRAL_MEMORY_LIMIT:=1024}"

  echo "[config] OK — SPIRAL_PYTHON=$SPIRAL_PYTHON SPIRAL_VALIDATE_CMD=$SPIRAL_VALIDATE_CMD"
}
validate_config

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

# ── Source memory pressure helper library ────────────────────────────────────
export SPIRAL_SCRATCH_DIR="$SCRATCH_DIR"
source "$SPIRAL_HOME/lib/memory-pressure-check.sh"

# ── jq resolution (reuse ralph.sh pattern) ───────────────────────────────────
RALPH_JQ_DIR="$SPIRAL_HOME/ralph"
if command -v jq &>/dev/null; then
  JQ="jq"
elif [[ -f "$RALPH_JQ_DIR/jq.exe" ]]; then
  JQ="$RALPH_JQ_DIR/jq.exe"
elif [[ -f "$REPO_ROOT/scripts/ralph/jq.exe" ]]; then
  JQ="$REPO_ROOT/scripts/ralph/jq.exe"
else
  echo "[spiral] ERROR: jq not found. Install with: choco install jq"
  exit $ERR_MISSING_DEP
fi

# ── Prerequisite checks ───────────────────────────────────────────────────────
if [[ ! -f "$PRD_FILE" ]]; then
  echo "[spiral] ERROR: prd.json not found at $PRD_FILE"
  exit $ERR_PRD_NOT_FOUND
fi
if [[ ! -f "$SPIRAL_RALPH" ]]; then
  echo "[spiral] ERROR: ralph.sh not found at $SPIRAL_RALPH"
  exit $ERR_MISSING_DEP
fi

# ── --migrate: run prd.json schema migration and exit ────────────────────────
if [[ "$MIGRATE_MODE" -eq 1 ]]; then
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/migrate_prd.py" "$PRD_FILE"
  exit $?
fi

# ── --archive-done: archive completed stories and exit ───────────────────────
if [[ "$ARCHIVE_MODE" -eq 1 ]]; then
  _ARCHIVE_ARGS=("--prd" "$PRD_FILE")
  [[ "$DRY_RUN" -eq 1 ]] && _ARCHIVE_ARGS+=("--dry-run")
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/archive_prd.py" "${_ARCHIVE_ARGS[@]}"
  exit $?
fi

# ── --changelog: generate CHANGELOG.md via git-cliff and exit ───────────────
if [[ "$CHANGELOG_MODE" -eq 1 ]]; then
  if ! command -v git-cliff &>/dev/null; then
    echo "[spiral] ERROR: git-cliff not found. Install with: cargo install git-cliff" >&2
    exit $ERR_MISSING_DEP
  fi
  _CLIFF_CONFIG="$SPIRAL_HOME/cliff.toml"
  if [[ ! -f "$_CLIFF_CONFIG" ]]; then
    echo "[spiral] ERROR: cliff.toml not found at $_CLIFF_CONFIG" >&2
    exit $ERR_CONFIG
  fi
  echo "[spiral] Generating CHANGELOG.md via git-cliff..."
  git-cliff --config "$_CLIFF_CONFIG" --output "$SPIRAL_HOME/CHANGELOG.md"
  echo "[spiral] CHANGELOG.md updated at $SPIRAL_HOME/CHANGELOG.md"
  exit 0
fi

# ── Schema version check ────────────────────────────────────────────────────
_PRD_SCHEMA_VER=$("$JQ" -r '.schemaVersion // empty' "$PRD_FILE" 2>/dev/null || echo "")
if [[ -n "$_PRD_SCHEMA_VER" ]] && [[ "$_PRD_SCHEMA_VER" -gt 1 ]] 2>/dev/null; then
  echo "[spiral] ERROR: prd.json schemaVersion $_PRD_SCHEMA_VER is newer than this SPIRAL version supports (max: 1)."
  echo "         Please update SPIRAL or downgrade prd.json."
  exit $ERR_SCHEMA_VERSION
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
  # Show total run cost from story_costs.json if present
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
  # Show manually-skipped stories
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

# ── Source verification libraries (before doctor check) ─────────────────────
source "$SPIRAL_HOME/lib/validate_preflight.sh"
source "$SPIRAL_HOME/lib/spiral_doctor.sh"
source "$SPIRAL_HOME/lib/spiral_assert.sh"
source "$SPIRAL_HOME/lib/spiral_retry.sh"

# ── --doctor: run dependency checks and exit ────────────────────────────────
if [[ "$DOCTOR_MODE" -eq 1 ]]; then
  spiral_doctor
  exit $?
fi

# ── Tee all output to log file ──────────────────────────────────────────────
mkdir -p "$SCRATCH_DIR"
exec > >(tee "$SCRATCH_DIR/_last_run.log") 2>&1

# ── Pre-flight validation ──────────────────────────────────────────────────
spiral_preflight_check "$PRD_FILE" "$SCRATCH_DIR"

# ── Checkpoint state machine coherence check ──────────────────────────────
if [[ -f "$CHECKPOINT_FILE" ]]; then
  if ! "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/state_machine.py" validate-phases --checkpoint "$CHECKPOINT_FILE"; then
    echo "  [checkpoint] WARNING: Corrupt checkpoint detected — removing and starting fresh from iter 1"
    rm -f "$CHECKPOINT_FILE"
  fi
fi

SESSION_START=$(date +%s)

# ── Time limit ────────────────────────────────────────────────────────────────
SESSION_DEADLINE=0
if [[ "$TIME_LIMIT_MINS" -gt 0 ]]; then
  SESSION_DEADLINE=$((SESSION_START + TIME_LIMIT_MINS * 60))
fi

# ── Signal trap state ─────────────────────────────────────────────────────────
WATCHDOG_PID=""
PHASE=""      # Current phase (R, T, M, G, I, V, C)
CHILD_PIDS=() # Track explicitly spawned child processes

# Signal handler for graceful interrupt (SIGINT/SIGTERM)
_spiral_cleanup() {
  local sig="${1:-INT}"
  echo ""
  echo "  [SPIRAL] Interrupted (signal $sig) at iter $SPIRAL_ITER phase $PHASE"
  log_spiral_event "error" "\"message\":\"Interrupted by signal $sig\",\"context\":\"iter=$SPIRAL_ITER phase=$PHASE\"" 2>/dev/null || true

  # Kill tracked child processes (ralph, parallel workers, etc.)
  for pid in "${CHILD_PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done

  # Write checkpoint atomically if we're mid-iteration
  if [[ -n "$PHASE" && "$SPIRAL_ITER" -gt 0 ]]; then
    local _ckpt_tmp
    _ckpt_tmp=$(mktemp -p "$SCRATCH_DIR" 2>/dev/null || echo "$SCRATCH_DIR/.checkpoint.tmp")
    printf '{"iter":%d,"phase":"%s","ts":"%s"}\n' \
      "$SPIRAL_ITER" "$PHASE" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$_ckpt_tmp" 2>/dev/null || true
    mv "$_ckpt_tmp" "$CHECKPOINT_FILE" 2>/dev/null || true
    echo "  [SPIRAL] Checkpoint saved at iter=$SPIRAL_ITER phase=$PHASE"
  fi

  echo "  [SPIRAL] Interrupted at iter $SPIRAL_ITER phase $PHASE — run again to resume"

  # Call the regular cleanup for worktrees, etc.
  cleanup
  exit 130 # Standard exit code for SIGINT
}

# Regular cleanup (EXIT)
cleanup() {
  echo ""
  echo "  [cleanup] Shutting down child processes..."
  # Kill memory watchdog
  [[ -n "$WATCHDOG_PID" ]] && kill "$WATCHDOG_PID" 2>/dev/null || true
  # Two-phase kill: SIGTERM first, wait, then SIGKILL stragglers
  local child_pids
  child_pids=$(jobs -p 2>/dev/null) || true
  if [[ -n "$child_pids" ]]; then
    echo "$child_pids" | xargs kill 2>/dev/null || true
    sleep 2
    echo "$child_pids" | xargs kill -9 2>/dev/null || true
  fi
  # Clean up orphaned git worktrees
  if [[ -d "$REPO_ROOT/.spiral-workers" ]]; then
    for wt in "$REPO_ROOT/.spiral-workers"/worker-*; do
      [[ -d "$wt" ]] && git -C "$REPO_ROOT" worktree remove "$wt" --force 2>/dev/null || true
    done
    rm -rf "$REPO_ROOT/.spiral-workers" 2>/dev/null || true
  fi
  # Prune stale worktree admin records left by crashed/interrupted workers (US-080)
  git -C "$REPO_ROOT" worktree prune 2>/dev/null || true
  # Clean up docker lock dirs
  rm -rf /tmp/spiral-docker-lock-* 2>/dev/null || true
  # Clean up memory pressure signal files
  rm -f "$SCRATCH_DIR/_memory_pressure.json" "$SCRATCH_DIR/_low_power_active" 2>/dev/null || true
  rm -f "$SCRATCH_DIR"/_worker_pause_* 2>/dev/null || true
  echo "  [cleanup] Done."
}

# Set trap handlers: EXIT calls cleanup; INT/TERM call _spiral_cleanup
trap cleanup EXIT
trap '_spiral_cleanup INT' INT
trap '_spiral_cleanup TERM' TERM

# SIGCHLD trap: reap zombie worker processes as they exit (US-076)
# Uses `wait -n` (bash 4.3+) in a loop to drain all available zombies per signal delivery.
# The `true` at the end suppresses non-zero exit when no children remain.
trap 'while wait -n 2>/dev/null; do :; done; true' SIGCHLD

# ── Memory watchdog — background monitor (graduated pressure or kill-only) ────
if [[ "${SPIRAL_MEMORY_WATCHDOG:-1}" -eq 1 ]] && command -v powershell.exe &>/dev/null; then
  # Windows: use PowerShell watchdog
  # Detect the node.exe ancestor (Claude Code) to protect it from emergency kills
  _CLAUDE_NODE_PID=""
  _check_pid=$$
  for _depth in 1 2 3 4 5; do
    _ppid=$(powershell.exe -NoProfile -Command "try { (Get-Process -Id $_check_pid -ErrorAction Stop).Parent.Id } catch { '' }" 2>/dev/null | tr -d '\r\n')
    if [[ -z "$_ppid" || "$_ppid" == "0" ]]; then break; fi
    _pname=$(powershell.exe -NoProfile -Command "try { (Get-Process -Id $_ppid -ErrorAction Stop).Name } catch { '' }" 2>/dev/null | tr -d '\r\n ')
    if [[ "$_pname" == "node" ]]; then
      _CLAUDE_NODE_PID="$_ppid"
      break
    fi
    _check_pid="$_ppid"
  done

  _WATCHDOG_ARGS="-ThresholdMB ${SPIRAL_MEMORY_THRESHOLD:-1536} -ParentPID $$ -IntervalSec ${SPIRAL_MEMORY_POLL_INTERVAL}"
  _WATCHDOG_ARGS="$_WATCHDOG_ARGS -WorkerPIDDir $SCRATCH_DIR"
  if [[ -n "$_CLAUDE_NODE_PID" ]]; then
    _WATCHDOG_ARGS="$_WATCHDOG_ARGS -ProtectPIDs $_CLAUDE_NODE_PID"
  fi
  if [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]]; then
    _WATCHDOG_ARGS="$_WATCHDOG_ARGS -ScratchDir $SCRATCH_DIR -ThresholdPct $SPIRAL_PRESSURE_THRESHOLDS -Hysteresis $SPIRAL_PRESSURE_HYSTERESIS -PreemptivePressureMB ${SPIRAL_PREEMPTIVE_PRESSURE_MB:-0}"
    _WATCHDOG_MODE="graduated"
  else
    _WATCHDOG_MODE="kill-only"
  fi
  powershell.exe -ExecutionPolicy Bypass -File "$SPIRAL_HOME/lib/memory-watchdog.ps1" \
    $_WATCHDOG_ARGS &
  WATCHDOG_PID=$!
  echo "  [memory] Watchdog started (PID: $WATCHDOG_PID, mode: $_WATCHDOG_MODE, threshold: ${SPIRAL_MEMORY_THRESHOLD:-1536}MB)"
  [[ -n "$_CLAUDE_NODE_PID" ]] && echo "  [memory] Protected PIDs: $_CLAUDE_NODE_PID (Claude Code node.exe)"
elif [[ "${SPIRAL_MEMORY_WATCHDOG:-1}" -eq 1 ]] && { [[ -f /proc/meminfo ]] || command -v vm_stat &>/dev/null; }; then
  # UNIX (Linux / macOS): use bash watchdog
  _WATCHDOG_SH_ARGS="--threshold-mb ${SPIRAL_MEMORY_THRESHOLD:-1536}"
  _WATCHDOG_SH_ARGS="$_WATCHDOG_SH_ARGS --parent-pid $$"
  _WATCHDOG_SH_ARGS="$_WATCHDOG_SH_ARGS --interval-sec ${SPIRAL_MEMORY_POLL_INTERVAL}"
  _WATCHDOG_SH_ARGS="$_WATCHDOG_SH_ARGS --scratch-dir $SCRATCH_DIR"
  if [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]]; then
    _WATCHDOG_SH_ARGS="$_WATCHDOG_SH_ARGS --threshold-pct $SPIRAL_PRESSURE_THRESHOLDS"
    _WATCHDOG_SH_ARGS="$_WATCHDOG_SH_ARGS --hysteresis $SPIRAL_PRESSURE_HYSTERESIS"
    _WATCHDOG_MODE="graduated"
  else
    _WATCHDOG_MODE="graduated" # bash watchdog always uses graduated mode
  fi
  bash "$SPIRAL_HOME/lib/memory-watchdog.sh" $_WATCHDOG_SH_ARGS &
  WATCHDOG_PID=$!
  echo "  [memory] Watchdog started (PID: $WATCHDOG_PID, mode: $_WATCHDOG_MODE [UNIX], threshold: ${SPIRAL_MEMORY_THRESHOLD:-1536}MB)"
fi

# ── Backup prd.json before any modifications ────────────────────────────────
cp "$PRD_FILE" "${PRD_FILE}.bak"
echo "[spiral] Backup: ${PRD_FILE}.bak"

# ── Helper: stats from prd.json ─────────────────────────────────────────────
prd_stats() {
  TOTAL=$("$JQ" '[.userStories | length] | .[0]' "$PRD_FILE")
  DONE=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")
  # Exclude manually-skipped stories from pending count
  if [[ -n "$SPIRAL_SKIP_STORY_IDS" ]]; then
    local _manual_skip_count
    _manual_skip_count=$("$JQ" --arg ids "$SPIRAL_SKIP_STORY_IDS" \
      '[.userStories[] | select(.passes != true) | select(.id as $sid | ($ids | split(",") | map(gsub("^\\s+|\\s+$";"")) | any(. == $sid)))] | length' \
      "$PRD_FILE" 2>/dev/null || echo 0)
    PENDING=$((TOTAL - DONE - _manual_skip_count))
  else
    PENDING=$((TOTAL - DONE))
  fi
}

# ── Helper: write per-iteration summary JSON (US-039) ──────────────────────
# Writes $SCRATCH_DIR/_iteration_summary.json with compact iteration stats.
# Overwrites each iteration. Non-fatal on write failure.
write_iter_summary() {
  local _iter_end _iter_dur _attempted _failed _phases_json _sep _p _var
  _iter_end=$(date +%s)
  _iter_dur=$((_iter_end - ITER_START))

  # stories_passed = RALPH_PROGRESS (set in Phase I)
  # stories_attempted: count from results.tsv if available, else = stories_passed
  _attempted=${RALPH_PROGRESS:-0}
  if [[ -f "$REPO_ROOT/results.tsv" ]]; then
    local _tsv_count
    _tsv_count=$(awk -F'\t' -v iter="$SPIRAL_ITER" 'NR>1 && $2==iter' "$REPO_ROOT/results.tsv" | wc -l)
    _tsv_count=$((_tsv_count + 0)) # trim whitespace
    [[ "$_tsv_count" -gt "$_attempted" ]] && _attempted=$_tsv_count
  fi
  _failed=$((_attempted - ${RALPH_PROGRESS:-0}))

  # Build phases_completed from phase start timestamps
  _phases_json="["
  _sep=""
  for _p in R T M I V C; do
    _var="_PHASE_TS_${_p}"
    if [[ "${!_var:-0}" -gt 0 ]]; then
      _phases_json="${_phases_json}${_sep}\"${_p}\""
      _sep=","
    fi
  done
  _phases_json="${_phases_json}]"

  "$SPIRAL_PYTHON" -c "
import json, sys
d = {
    'iter': int(sys.argv[1]),
    'ts_start': int(sys.argv[2]),
    'ts_end': int(sys.argv[3]),
    'duration_sec': int(sys.argv[4]),
    'stories_attempted': int(sys.argv[5]),
    'stories_passed': int(sys.argv[6]),
    'stories_failed': int(sys.argv[7]),
    'phases_completed': json.loads(sys.argv[8])
}
with open(sys.argv[9], 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
" "$SPIRAL_ITER" "$ITER_START" "$_iter_end" "$_iter_dur" \
    "$_attempted" "${RALPH_PROGRESS:-0}" "$_failed" \
    "$_phases_json" "$SCRATCH_DIR/_iteration_summary.json" 2>/dev/null || {
    echo "  [C] WARNING: Failed to write _iteration_summary.json (non-fatal)"
  }
}

# ── Helper: write checkpoint ────────────────────────────────────────────────
write_checkpoint() {
  local iter="$1" phase="$2"
  printf '{"iter":%d,"phase":"%s","ts":"%s","run_id":"%s","spiralVersion":"%s","phaseDurations":{"R":%d,"T":%d,"M":%d,"I":%d,"V":%d,"C":%d}}\n' \
    "$iter" "$phase" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "${SPIRAL_RUN_ID:-}" \
    "${SPIRAL_VERSION:-unknown}" \
    "${_PHASE_DUR_R:-0}" "${_PHASE_DUR_T:-0}" "${_PHASE_DUR_M:-0}" \
    "${_PHASE_DUR_I:-0}" "${_PHASE_DUR_V:-0}" "${_PHASE_DUR_C:-0}" \
    >"$CHECKPOINT_FILE"
}

# ── Helper: append a structured JSONL event to .spiral/spiral_events.jsonl ──
# Provided by lib/spiral_events.sh (sourced below). See that file for details.
source "$SPIRAL_HOME/lib/spiral_events.sh"

# ── Helper: POST a JSON notification to SPIRAL_NOTIFY_WEBHOOK (US-100) ──────
# Usage: notify_webhook PHASE EVENT [STATUS] [EXTRA_FIELDS]
#   PHASE:        R, T, M, G, I, V, C
#   EVENT:        start | end
#   STATUS:       ok | failed | skipped  (default: ok)
#   EXTRA_FIELDS: additional jq-compatible key=value pairs (optional)
# Non-fatal: logs a warning on failure and returns 0.
notify_webhook() {
  [[ -z "${SPIRAL_NOTIFY_WEBHOOK:-}" ]] && return 0
  local phase="$1" event="$2" status="${3:-ok}" extra_arg="${4:-}"
  local ts body curl_args=()
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  # Build JSON body using jq for correct escaping
  body="$("$JQ" -n \
    --arg run_id "${SPIRAL_RUN_ID:-}" \
    --arg phase "$phase" \
    --arg event "$event" \
    --arg status "$status" \
    --arg ts "$ts" \
    --argjson iter "${SPIRAL_ITER:-0}" \
    '{run_id: $run_id, phase: $phase, event: $event, status: $status, timestamp_iso: $ts, iteration: $iter}' 2>/dev/null)" || {
    echo "  [webhook] WARNING: Failed to build JSON body (non-fatal)" >&2
    return 0
  }
  # Merge extra fields (e.g., gate_report_path) if provided
  if [[ -n "$extra_arg" ]]; then
    body="$("$JQ" --argjson x "{$extra_arg}" '. + $x' <<<"$body" 2>/dev/null || echo "$body")"
  fi
  # Build curl args
  curl_args=(-s -o /dev/null --max-time "${SPIRAL_NOTIFY_WEBHOOK_TIMEOUT:-5}"
    -X POST -H "Content-Type: application/json" -d "$body")
  if [[ -n "${SPIRAL_NOTIFY_WEBHOOK_HEADERS:-}" ]]; then
    curl_args+=(-H "$SPIRAL_NOTIFY_WEBHOOK_HEADERS")
  fi
  curl_args+=("$SPIRAL_NOTIFY_WEBHOOK")
  if ! curl "${curl_args[@]}" 2>/dev/null; then
    echo "  [webhook] WARNING: POST to SPIRAL_NOTIFY_WEBHOOK failed (non-fatal)" >&2
  fi
}

# ── Helper: returns 0 if current iter already completed this phase ───────────
checkpoint_phase_done() {
  local phase="$1"
  [[ -f "$CHECKPOINT_FILE" ]] || return 1
  local ckpt_iter ckpt_phase
  ckpt_iter=$("$JQ" -r '.iter // 0' "$CHECKPOINT_FILE")
  ckpt_phase=$("$JQ" -r '.phase // ""' "$CHECKPOINT_FILE")
  [[ "$ckpt_iter" -eq "$SPIRAL_ITER" ]] || return 1
  # Phase order: R T M G I V C
  local -A PHASE_ORDER=([R]=1 [T]=2 [M]=3 [G]=4 [I]=5 [V]=6 [C]=7)
  [[ "${PHASE_ORDER[$ckpt_phase]:-0}" -ge "${PHASE_ORDER[$phase]:-0}" ]]
}

# ── Helper: inject placeholders into research prompt ─────────────────────────
build_research_prompt() {
  local iter="$1"
  local output_path="$2"

  local next_id_num
  next_id_num=$("$JQ" "[.userStories[].id | ltrimstr(\"${SPIRAL_STORY_PREFIX}-\") | tonumber] | max + 1" "$PRD_FILE")

  local existing_titles
  existing_titles=$("$JQ" -r '[.userStories[].title] | join("\n- ")' "$PRD_FILE")

  local pending_titles
  pending_titles=$("$JQ" -r '[.userStories[] | select(.passes != true) | .title] | join("\n- ")' "$PRD_FILE")

  # Build injected prompt via sed substitutions
  local prompt_content
  prompt_content=$(cat "$SPIRAL_RESEARCH_PROMPT")
  prompt_content="${prompt_content//__SPIRAL_ITER__/$iter}"
  prompt_content="${prompt_content//__NEXT_ID_NUM__/$next_id_num}"
  prompt_content="${prompt_content//__OUTPUT_PATH__/$output_path}"
  prompt_content="${prompt_content//__STORY_PREFIX__/$SPIRAL_STORY_PREFIX}"
  local focus_section=""
  if [[ -n "$SPIRAL_FOCUS" ]]; then
    focus_section="## FOCUS DIRECTIVE\n\n**This iteration is scoped to: \"$SPIRAL_FOCUS\"**\n\nYou MUST only discover stories directly related to this theme. Skip any story that does not clearly improve or relate to \"$SPIRAL_FOCUS\". When in doubt, omit rather than include."
  fi

  # Replace __EXISTING_TITLES__, __PENDING_TITLES__, and __SPIRAL_FOCUS_SECTION__ placeholders
  printf '%s' "$prompt_content" |
    awk -v existing="$existing_titles" -v pending="$pending_titles" -v focus="$focus_section" \
      '{gsub(/__EXISTING_TITLES__/, existing); gsub(/__PENDING_TITLES__/, pending); gsub(/__SPIRAL_FOCUS_SECTION__/, focus); print}'
}

# ── Pre-flight memory check — auto-adjust workers if RAM is low ────────────
if command -v powershell.exe &>/dev/null; then
  FREE_MB=$(powershell.exe -Command \
    "[math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)" 2>/dev/null | tr -d '\r')
  if [[ -n "$FREE_MB" && "$FREE_MB" =~ ^[0-9]+$ ]]; then
    # Each Claude instance needs ~2.5GB; plus 512MB overhead
    NEEDED_MB=$(((RALPH_WORKERS + 1) * 2560 + 512))
    if [[ "$FREE_MB" -lt 3072 ]]; then
      echo "  [memory] WARNING: Only ${FREE_MB}MB free RAM — OOM risk is high"
      echo "  [memory] Consider closing applications or reducing --ralph-workers"
    fi
    if [[ "$RALPH_WORKERS" -gt 1 && "$FREE_MB" -lt "$NEEDED_MB" ]]; then
      # Auto-reduce workers to fit available memory
      MAX_SAFE_WORKERS=$(((FREE_MB - 512) / 2560))
      [[ "$MAX_SAFE_WORKERS" -lt 1 ]] && MAX_SAFE_WORKERS=1
      if [[ "$MAX_SAFE_WORKERS" -lt "$RALPH_WORKERS" ]]; then
        echo "  [memory] Auto-reducing workers: $RALPH_WORKERS → $MAX_SAFE_WORKERS (${FREE_MB}MB free, need ${NEEDED_MB}MB)"
        RALPH_WORKERS="$MAX_SAFE_WORKERS"
      fi
    fi
  fi
fi

# ── SPIRAL banner ───────────────────────────────────────────────────────────
prd_stats
echo ""
echo "  ╔══════════════════════════════════════════════╗"
echo "  ║   SPIRAL — Self-iterating PRD Loop            ║"
echo "  ╠══════════════════════════════════════════════╣"
echo "  ║  PRD:         $PRD_FILE"
echo "  ║  Stories:     $DONE/$TOTAL complete ($PENDING pending)"
echo "  ║  Max iters:   $MAX_SPIRAL_ITERS"
echo "  ║  Ralph iters: $RALPH_MAX_ITERS per phase"
if [[ -n "$SPIRAL_CLI_MODEL" ]]; then
  echo "  ║  Model:       $SPIRAL_CLI_MODEL (cli override)"
elif [[ "$SPIRAL_MODEL_ROUTING" == "auto" ]]; then
  echo "  ║  Model:       auto (haiku/sonnet/opus by complexity)"
else
  echo "  ║  Model:       $SPIRAL_MODEL_ROUTING (config fixed)"
fi
if [[ "$SPIRAL_FIRECRAWL_ENABLED" -eq 1 ]]; then
  echo "  ║  Research:    $SPIRAL_RESEARCH_MODEL model + Firecrawl MCP"
else
  echo "  ║  Research:    $SPIRAL_RESEARCH_MODEL model (WebFetch fallback)"
fi
[[ "$RALPH_WORKERS" -gt 1 ]] && echo "  ║  Workers:     $RALPH_WORKERS parallel (git worktrees)"
[[ "$SKIP_RESEARCH" -eq 1 ]] && echo "  ║  Mode:        --skip-research (Phase R skipped)"
[[ "$DRY_RUN" -eq 1 ]] && echo "  ║  Mode:        --dry-run (no API calls)"
[[ "$MONITOR_TERMINALS" -eq 1 ]] && echo "  ║  Monitor:     terminal per worker (--monitor)"
[[ -n "$SPIRAL_SPECKIT_CONSTITUTION" && -f "$REPO_ROOT/$SPIRAL_SPECKIT_CONSTITUTION" ]] &&
  echo "  ║  Spec-Kit:    constitution loaded"
[[ -n "$SPIRAL_FOCUS" ]] && echo "  ║  Focus:       $SPIRAL_FOCUS"
[[ -n "$SPIRAL_FOCUS_TAGS" ]] && echo "  ║  Focus tags:  $SPIRAL_FOCUS_TAGS"
[[ "$SPIRAL_MAX_PENDING" -gt 0 ]] && echo "  ║  Max pending: $SPIRAL_MAX_PENDING incomplete stories"
[[ "$SPIRAL_MAX_RESEARCH_STORIES" -gt 0 ]] && echo "  ║  Max research: $SPIRAL_MAX_RESEARCH_STORIES stories per iteration"
[[ "$SPIRAL_STORY_BATCH_SIZE" -gt 0 ]] && echo "  ║  Batch size:  $SPIRAL_STORY_BATCH_SIZE stories per iteration"
[[ -n "$SPIRAL_COST_CEILING" ]] && echo "  ║  Cost cap:    \$${SPIRAL_COST_CEILING} USD"
[[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && echo "  ║  Low power:   adaptive memory management enabled"
if [[ "$TIME_LIMIT_MINS" -gt 0 ]]; then
  _DEADLINE_DISPLAY=$(date -d "@$SESSION_DEADLINE" +"%H:%M" 2>/dev/null ||
    date -r "$SESSION_DEADLINE" +"%H:%M" 2>/dev/null ||
    echo "~${TIME_LIMIT_MINS}m from now")
  echo "  ║  Time limit:  ${TIME_LIMIT_MINS}m (stops ~${_DEADLINE_DISPLAY})"
fi
[[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]] && echo "  ║  Cache TTL:   ${SPIRAL_RESEARCH_CACHE_TTL_HOURS}h (research URL responses)"
echo "  ║  Capacity:    Phase R skipped when pending > $CAPACITY_LIMIT"
echo "  ║  Scratch:     $SCRATCH_DIR"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

# ── --replay: re-run a single story in an isolated worktree ──────────────────
# Runs only Phases I+V+C for the specified story ID; skips R/T/M/G entirely.
# Phase G (human gate) is automatically skipped.
# Worktree cleaned up on pass; preserved on failure for inspection.
if [[ -n "$REPLAY_STORY_ID" ]]; then
  # Validate story ID exists in prd.json
  _REPLAY_EXISTS=$("$JQ" --arg id "$REPLAY_STORY_ID" \
    '[.userStories[] | select(.id == $id)] | length' "$PRD_FILE" 2>/dev/null || echo "0")
  if [[ "$_REPLAY_EXISTS" -eq 0 ]]; then
    echo "[replay] ERROR: Story '$REPLAY_STORY_ID' not found in $PRD_FILE"
    exit $ERR_STORY_NOT_FOUND
  fi

  _REPLAY_TITLE=$("$JQ" -r --arg id "$REPLAY_STORY_ID" \
    '.userStories[] | select(.id == $id) | .title' "$PRD_FILE")

  REPLAY_WORKTREE="$REPO_ROOT/.spiral-replay-${REPLAY_STORY_ID}"
  REPLAY_BRANCH="spiral-replay-${REPLAY_STORY_ID}-$(date +%Y%m%d-%H%M%S)"
  REPLAY_LOG="$SCRATCH_DIR/replay-${REPLAY_STORY_ID}.log"
  REPLAY_START_TS=$(date +%s)

  echo ""
  echo "  ╔══════════════════════════════════════════════════════╗"
  echo "  ║  [REPLAY] $REPLAY_STORY_ID"
  echo "  ║  $_REPLAY_TITLE"
  echo "  ╠══════════════════════════════════════════════════════╣"
  echo "  ║  Worktree: $REPLAY_WORKTREE"
  echo "  ║  Log:      $REPLAY_LOG"
  echo "  ╚══════════════════════════════════════════════════════╝"
  echo ""

  # Remove existing replay worktree if present (leftover from previous failed replay)
  if [[ -d "$REPLAY_WORKTREE" ]]; then
    echo "  [replay] Removing existing replay worktree: $REPLAY_WORKTREE"
    git -C "$REPO_ROOT" worktree remove "$REPLAY_WORKTREE" --force 2>/dev/null || rm -rf "$REPLAY_WORKTREE"
  fi

  # Create isolated git worktree from current HEAD
  echo "  [replay] Creating worktree from HEAD..."
  git -C "$REPO_ROOT" worktree add -b "$REPLAY_BRANCH" "$REPLAY_WORKTREE" HEAD

  # Copy prd.json to worktree; set only the target story to pending
  REPLAY_PRD="$REPLAY_WORKTREE/prd.json"
  cp "$PRD_FILE" "$REPLAY_PRD"
  _UPDATED=$("$JQ" --arg id "$REPLAY_STORY_ID" \
    '(.userStories[] | select(.id == $id) | .passes) = false' "$REPLAY_PRD") &&
    echo "$_UPDATED" >"$REPLAY_PRD"
  echo "  [replay] Story $REPLAY_STORY_ID set to pending; all others preserved"

  # Phase I: run ralph in the worktree
  echo ""
  echo "  [replay] Phase I — running ralph on $REPLAY_STORY_ID..."
  REPLAY_I_RC=0
  _REPLAY_DRY_RUN_FLAG=""
  [[ "${DRY_RUN:-0}" -eq 1 ]] && _REPLAY_DRY_RUN_FLAG="--dry-run"
  _REPLAY_I_START=$(date +%s)
  if [[ "${SPIRAL_IMPL_TIMEOUT:-600}" -gt 0 ]] && command -v timeout &>/dev/null; then
    (cd "$REPLAY_WORKTREE" && timeout --kill-after=30 "${SPIRAL_IMPL_TIMEOUT}" bash "$SPIRAL_RALPH" \
      "$RALPH_MAX_ITERS" --prd "$REPLAY_PRD" --tool claude $_REPLAY_DRY_RUN_FLAG \
      2>&1) | tee "$REPLAY_LOG" || REPLAY_I_RC=$?
  else
    (cd "$REPLAY_WORKTREE" && bash "$SPIRAL_RALPH" \
      "$RALPH_MAX_ITERS" --prd "$REPLAY_PRD" --tool claude $_REPLAY_DRY_RUN_FLAG \
      2>&1) | tee "$REPLAY_LOG" || REPLAY_I_RC=$?
  fi
  _REPLAY_I_ELAPSED=$(($(date +%s) - _REPLAY_I_START))
  if [[ "$REPLAY_I_RC" -eq 124 ]]; then
    echo "  [replay] WARNING: Ralph timed out after ${_REPLAY_I_ELAPSED}s (limit: ${SPIRAL_IMPL_TIMEOUT}s)"
    log_spiral_event "phase_timeout" "\"phase\":\"I\",\"story_id\":\"$REPLAY_STORY_ID\",\"iteration\":0,\"duration_ms\":$((_REPLAY_I_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_IMPL_TIMEOUT}"
  fi

  # Check story pass state from worktree prd.json
  _REPLAY_STORY_PASSES=$("$JQ" -r --arg id "$REPLAY_STORY_ID" \
    '.userStories[] | select(.id == $id) | .passes' "$REPLAY_PRD" 2>/dev/null || echo "false")

  # Phase V: validate in worktree
  echo ""
  echo "  [replay] Phase V — running validation in worktree..."
  REPLAY_V_RC=0
  (cd "$REPLAY_WORKTREE" && eval "$SPIRAL_VALIDATE_CMD" 2>&1) |
    tee -a "$REPLAY_LOG" || REPLAY_V_RC=$?

  # Determine overall result
  REPLAY_RESULT="fail"
  if [[ "$_REPLAY_STORY_PASSES" == "true" && "$REPLAY_V_RC" -eq 0 ]]; then
    REPLAY_RESULT="pass"
  fi

  REPLAY_END_TS=$(date +%s)
  REPLAY_DURATION=$((REPLAY_END_TS - REPLAY_START_TS))

  # Log event to spiral_events.jsonl
  log_spiral_event "replay_complete" \
    "\"storyId\":\"$REPLAY_STORY_ID\",\"result\":\"$REPLAY_RESULT\",\"duration_s\":$REPLAY_DURATION,\"log\":\"$REPLAY_LOG\""

  echo ""
  if [[ "$REPLAY_RESULT" == "pass" ]]; then
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║  [REPLAY] PASSED: $REPLAY_STORY_ID"
    echo "  ║  Duration: ${REPLAY_DURATION}s | Log: $REPLAY_LOG"
    echo "  ╚══════════════════════════════════════════════════════╝"
    git -C "$REPO_ROOT" worktree remove "$REPLAY_WORKTREE" --force 2>/dev/null || true
    git -C "$REPO_ROOT" branch -D "$REPLAY_BRANCH" 2>/dev/null || true
    echo "  [replay] Worktree cleaned up (pass)"
    exit 0
  else
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║  [REPLAY] FAILED: $REPLAY_STORY_ID"
    echo "  ║  Duration: ${REPLAY_DURATION}s | Log: $REPLAY_LOG"
    echo "  ║  Worktree: $REPLAY_WORKTREE (preserved for inspection)"
    echo "  ╚══════════════════════════════════════════════════════╝"
    echo "  [replay] Worktree preserved for inspection"
    exit $ERR_REPLAY_FAILED
  fi
fi

# ── Startup: initialize counters and resume from checkpoint if available ────
ZERO_PROGRESS_COUNT=0
SPIRAL_ITER=0

export SPIRAL_FOCUS
export SPIRAL_FOCUS_TAGS
export SPIRAL_ITER
export SPIRAL_MAX_RESEARCH_STORIES
export SPIRAL_SKIP_STORY_IDS
export DRY_RUN

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

# ── Auto-generate progress.txt skeleton on first run ─────────────────────────
if [[ ! -f "$REPO_ROOT/progress.txt" ]]; then
  _OVERVIEW=$("$JQ" -r '.overview // "No overview provided"' "$PRD_FILE" 2>/dev/null || echo "No overview provided")
  _STACK=""
  [[ -f "$REPO_ROOT/pyproject.toml" ]] && _STACK="${_STACK}Python "
  [[ -f "$REPO_ROOT/package.json" ]] && _STACK="${_STACK}Node.js "
  [[ -f "$REPO_ROOT/Cargo.toml" ]] && _STACK="${_STACK}Rust "
  [[ -f "$REPO_ROOT/go.mod" ]] && _STACK="${_STACK}Go "
  [[ -f "$REPO_ROOT/Gemfile" ]] && _STACK="${_STACK}Ruby "
  [[ -z "$_STACK" ]] && _STACK="Unknown"
  cat >"$REPO_ROOT/progress.txt" <<PROGRESS_EOF
## Codebase Patterns

Project: $_OVERVIEW

Tech Stack: ${_STACK% }

- (patterns will be added by ralph agents as they discover them)

---

## Gotchas

- (gotchas will be added by ralph agents as they discover them)

---

PROGRESS_EOF
  echo "  [spiral] Generated progress.txt skeleton (tech stack: ${_STACK% })"
fi

# ── Main SPIRAL loop ────────────────────────────────────────────────────────
while [[ $SPIRAL_ITER -lt $MAX_SPIRAL_ITERS ]]; do
  SPIRAL_ITER=$((SPIRAL_ITER + 1))
  ITER_START=$(date +%s)

  # Validate prd.json integrity before each iteration (Idea 3)
  # If corrupted by a mid-write crash, restore from the most recent backup
  if ! "$JQ" empty "$PRD_FILE" 2>/dev/null; then
    echo "  [spiral] WARNING: prd.json is invalid JSON — attempting restore from backup"
    _LATEST_BACKUP=$(ls -t "$SCRATCH_DIR/prd-backups/prd-iter"*.json 2>/dev/null | head -1 || true)
    if [[ -n "$_LATEST_BACKUP" && -f "$_LATEST_BACKUP" ]]; then
      cp "$_LATEST_BACKUP" "$PRD_FILE"
      echo "  [spiral] Restored prd.json from: $(basename "$_LATEST_BACKUP")"
    else
      echo "  [spiral] ERROR: No backup available — cannot recover prd.json"
      exit $ERR_PRD_CORRUPT
    fi
  fi

  prd_stats
  ADDED=0          # new stories added this iter (set in Phase M; default 0 if skipped)
  RALPH_RAN=0      # set to 1 if ralph actually executed this iter (controls Phase V)
  RALPH_PROGRESS=0 # stories completed this iter; reset each iter for accurate velocity
  # Phase duration tracking (US-046): reset per-iteration, updated at each phase_end
  _PHASE_DUR_R=0
  _PHASE_DUR_T=0
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
    _COST_OUTPUT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/cost_check.py" \
      --results "$REPO_ROOT/results.tsv" --ceiling "$SPIRAL_COST_CEILING" 2>&1) || _COST_RC=$?
    echo "$_COST_OUTPUT"
    if [[ "$_COST_RC" -eq 2 ]]; then
      echo ""
      echo "  ╔══════════════════════════════════════════════════════╗"
      echo "  ║  SPIRAL stopped: cost ceiling reached (\$${SPIRAL_COST_CEILING})  ║"
      echo "  ╚══════════════════════════════════════════════════════╝"
      exit $ERR_COST_CEILING
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

  # ── Phase R: RESEARCH ──────────────────────────────────────────────────────
  PHASE="R"
  echo ""
  echo "  [Phase R] RESEARCH — searching sources..."
  log_spiral_event "phase_start" "\"phase\":\"R\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "R" "start"
  _PHASE_TS_R=$(date +%s)
  RESEARCH_OUTPUT="$SCRATCH_DIR/_research_output.json"

  if checkpoint_phase_done "R"; then
    echo "  [R] Skipping (checkpoint: already done this iter)"
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] skipping research agent — using empty output"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    write_checkpoint "$SPIRAL_ITER" "R"
  elif [[ "$SKIP_RESEARCH" -eq 1 ]]; then
    echo "  [R] Skipping (--skip-research flag set)"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    write_checkpoint "$SPIRAL_ITER" "R"
  elif [[ "$OVER_CAPACITY" -eq 1 ]]; then
    echo "  [R] Skipping (over-capacity: $PENDING pending > $CAPACITY_LIMIT)"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    write_checkpoint "$SPIRAL_ITER" "R"
  elif [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && spiral_should_skip_phase "R"; then
    _P_LVL=$(spiral_pressure_level)
    echo "  [R] Skipping (memory pressure: level $_P_LVL)"
    spiral_log_low_power "Phase R skipped (pressure level $_P_LVL, iter $SPIRAL_ITER)"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    write_checkpoint "$SPIRAL_ITER" "R"
  else
    # ── Research cache: prune expired entries ──────────────────────────────
    if [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]]; then
      mkdir -p "$RESEARCH_CACHE_DIR"
      PRUNED=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research_cache.py" prune "$RESEARCH_CACHE_DIR" --ttl-hours "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" 2>/dev/null | grep -oP '\d+' || echo "0")
      [[ "$PRUNED" -gt 0 ]] && echo "  [R] Cache: pruned $PRUNED expired entries (TTL=${SPIRAL_RESEARCH_CACHE_TTL_HOURS}h)"
    fi

    # ── Gemini web research (optional, configured via SPIRAL_GEMINI_PROMPT) ──
    GEMINI_RESEARCH=""
    if command -v gemini &>/dev/null && [[ -n "$SPIRAL_GEMINI_PROMPT" ]]; then
      echo "  [R] Running Gemini 2.5 Pro web research (-y web search enabled)..."
      GEMINI_ERR_TMP=$(mktemp)
      GEMINI_RESEARCH=$(gemini \
        -m gemini-2.5-pro \
        -p "$SPIRAL_GEMINI_PROMPT" \
        -y --output-format text 2>"$GEMINI_ERR_TMP" || true)
      if [[ -n "$GEMINI_RESEARCH" ]]; then
        echo "  [R] Gemini web research complete ($(echo "$GEMINI_RESEARCH" | wc -l) lines)"
      else
        # Diagnose failure reason from stderr
        if grep -qi '429\|RESOURCE_EXHAUSTED\|rate.limit\|quota' "$GEMINI_ERR_TMP" 2>/dev/null; then
          echo "  [R] Gemini rate-limited — Claude will browse URLs directly"
        elif grep -qi 'PERMISSION_DENIED\|API.key\|api_key\|UNAUTHENTICATED' "$GEMINI_ERR_TMP" 2>/dev/null; then
          echo "  [R] Gemini auth error — check GEMINI_API_KEY"
        elif [[ -s "$GEMINI_ERR_TMP" ]]; then
          GEMINI_ERR_FIRST=$(head -1 "$GEMINI_ERR_TMP")
          echo "  [R] Gemini web research returned empty — $GEMINI_ERR_FIRST"
        else
          echo "  [R] Gemini web research returned empty — Claude will browse URLs directly"
        fi
      fi
      rm -f "$GEMINI_ERR_TMP"
    fi

    INJECTED_PROMPT=$(build_research_prompt "$SPIRAL_ITER" "$RESEARCH_OUTPUT")
    # Prepend Gemini research context so Claude skips URL browsing and writes JSON faster
    if [[ -n "$GEMINI_RESEARCH" ]]; then
      INJECTED_PROMPT="## Pre-Research Context (Gemini 2.5 Pro — web search enabled)

The following compliance research was pre-fetched. Use this as your primary source.
You do NOT need to browse URLs already covered below. Focus on synthesizing this
into the required story JSON format as quickly as possible.

$GEMINI_RESEARCH

---

$INJECTED_PROMPT"
    fi

    # ── Inject cached URL content so agent skips re-fetching ──────────────
    if [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]]; then
      CACHE_CONTEXT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research_cache.py" inject "$RESEARCH_CACHE_DIR" --ttl-hours "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" 2>/dev/null || true)
      if [[ -n "$CACHE_CONTEXT" ]]; then
        CACHE_COUNT=$(ls "$RESEARCH_CACHE_DIR"/*.json 2>/dev/null | wc -l)
        echo "  [R] Cache: injecting $CACHE_COUNT cached URL responses into prompt"
        INJECTED_PROMPT="$CACHE_CONTEXT

---

$INJECTED_PROMPT"
      fi
    fi

    # Inject spec-kit constitution so research respects project standards
    if [[ -n "$SPIRAL_SPECKIT_CONSTITUTION" && -f "$REPO_ROOT/$SPIRAL_SPECKIT_CONSTITUTION" ]]; then
      CONSTITUTION_CONTENT=$(cat "$REPO_ROOT/$SPIRAL_SPECKIT_CONSTITUTION")
      INJECTED_PROMPT="## Project Constitution (Spec-Kit)

The following constitution defines non-negotiable project standards.
All new stories MUST comply with these principles. Do NOT suggest stories
that would violate these standards.

$CONSTITUTION_CONTENT

---

$INJECTED_PROMPT"
      echo "  [R] Spec-Kit constitution injected into research prompt"
    fi

    # Resolve research model: CLI override > config
    RESEARCH_MODEL="${SPIRAL_RESEARCH_MODEL:-sonnet}"
    [[ -n "$SPIRAL_CLI_MODEL" ]] && RESEARCH_MODEL="$SPIRAL_CLI_MODEL"

    # Build allowed tools: prefer Firecrawl MCP when configured
    if [[ "${SPIRAL_FIRECRAWL_ENABLED:-0}" -eq 1 ]]; then
      RESEARCH_TOOLS="WebSearch,mcp__firecrawl__scrape,mcp__firecrawl__search,mcp__firecrawl__crawl,Write,Read"
      echo "  [R] Firecrawl MCP enabled — using clean markdown scraping"
    else
      RESEARCH_TOOLS="WebSearch,WebFetch,Write,Read"
    fi

    # ── Retry loop for Phase R ─────────────────────────────────────────────
    _R_ATTEMPT=0
    _R_MAX_ATTEMPTS=$((SPIRAL_RESEARCH_RETRIES + 1))
    _R_SUCCESS=0

    while [[ "$_R_ATTEMPT" -lt "$_R_MAX_ATTEMPTS" ]]; do
      if [[ "$_R_ATTEMPT" -gt 0 ]]; then
        echo "  [R] Research output missing or invalid — retrying (attempt $_R_ATTEMPT/$SPIRAL_RESEARCH_RETRIES)"
      fi

      echo "  [R] Spawning Claude research agent (max 30 turns, model: $RESEARCH_MODEL)..."
      echo "  ─────── Research Agent Start ─────────────────────────"

      _R_EXIT=0
      _R_START=$(date +%s)
      if [[ "${SPIRAL_RESEARCH_TIMEOUT:-300}" -gt 0 ]] && command -v timeout &>/dev/null; then
        if command -v node &>/dev/null && [[ -f "$STREAM_FMT" ]]; then
          (
            unset CLAUDECODE
            timeout --kill-after=30 "${SPIRAL_RESEARCH_TIMEOUT}" \
              claude -p "$INJECTED_PROMPT" \
              --model "$RESEARCH_MODEL" \
              --allowedTools "$RESEARCH_TOOLS" \
              --max-turns 30 \
              --verbose \
              --output-format stream-json \
              --dangerously-skip-permissions \
              </dev/null 2>&1 | node "$STREAM_FMT"
          ) || _R_EXIT=$?
        else
          (
            unset CLAUDECODE
            timeout --kill-after=30 "${SPIRAL_RESEARCH_TIMEOUT}" \
              claude -p "$INJECTED_PROMPT" \
              --model "$RESEARCH_MODEL" \
              --allowedTools "$RESEARCH_TOOLS" \
              --max-turns 30 \
              --dangerously-skip-permissions \
              </dev/null 2>&1
          ) || _R_EXIT=$?
        fi
      else
        if command -v node &>/dev/null && [[ -f "$STREAM_FMT" ]]; then
          (
            unset CLAUDECODE
            claude -p "$INJECTED_PROMPT" \
              --model "$RESEARCH_MODEL" \
              --allowedTools "$RESEARCH_TOOLS" \
              --max-turns 30 \
              --verbose \
              --output-format stream-json \
              --dangerously-skip-permissions \
              </dev/null 2>&1 | node "$STREAM_FMT"
          ) || _R_EXIT=$?
        else
          (
            unset CLAUDECODE
            claude -p "$INJECTED_PROMPT" \
              --model "$RESEARCH_MODEL" \
              --allowedTools "$RESEARCH_TOOLS" \
              --max-turns 30 \
              --dangerously-skip-permissions \
              </dev/null 2>&1
          ) || _R_EXIT=$?
        fi
      fi
      _R_ELAPSED=$(($(date +%s) - _R_START))
      if [[ "$_R_EXIT" -eq 124 ]]; then
        echo ""
        echo "  [Phase R] WARNING: Research agent timed out after ${_R_ELAPSED}s (limit: ${SPIRAL_RESEARCH_TIMEOUT}s)"
        log_spiral_event "phase_timeout" "\"phase\":\"R\",\"story_id\":\"research\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_R_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_RESEARCH_TIMEOUT}"
      fi

      echo "  ─────── Research Agent End ───────────────────────────"

      # Validate output: file must exist and be valid JSON
      if [[ -f "$RESEARCH_OUTPUT" ]] && "$SPIRAL_PYTHON" -c "import json; json.load(open('$RESEARCH_OUTPUT'))" 2>/dev/null; then
        _R_SUCCESS=1
        break
      fi

      ((_R_ATTEMPT++)) || true
    done

    if [[ "$_R_SUCCESS" -eq 0 ]]; then
      echo "  [R] WARNING: Research output missing or invalid after all retries — using empty"
      echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    fi

    if [[ ! -f "$RESEARCH_OUTPUT" ]]; then
      echo "  [R] WARNING: Research agent did not write $RESEARCH_OUTPUT — using empty"
      echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    else
      RESEARCH_COUNT=$("$JQ" '.stories | length' "$RESEARCH_OUTPUT" 2>/dev/null || echo "?")
      echo "  [R] Research complete — $RESEARCH_COUNT story candidates found"

      # ── Cache source URLs from research output ─────────────────────────
      if [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]]; then
        CACHED_URLS=0
        while IFS= read -r src_url; do
          [[ -z "$src_url" ]] && continue
          # Extract story content referencing this source for cache value
          STORY_CONTENT=$("$JQ" -r --arg url "$src_url" \
            '[.stories[] | select(.source == $url)] | map(.title + ": " + .description) | join("\n")' \
            "$RESEARCH_OUTPUT" 2>/dev/null || true)
          if [[ -n "$STORY_CONTENT" ]]; then
            echo "$STORY_CONTENT" | "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research_cache.py" store "$RESEARCH_CACHE_DIR" "$src_url" - >/dev/null 2>&1 && ((CACHED_URLS++)) || true
          fi
        done < <("$JQ" -r '[.stories[].source // empty] | unique | .[]' "$RESEARCH_OUTPUT" 2>/dev/null || true)
        [[ "$CACHED_URLS" -gt 0 ]] && echo "  [R] Cache: stored $CACHED_URLS source URLs for future iterations"
      fi
    fi

    write_checkpoint "$SPIRAL_ITER" "R"
  fi
  _PHASE_DUR_R=$(($(date +%s) - _PHASE_TS_R))
  log_spiral_event "phase_end" "\"phase\":\"R\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_R"
  notify_webhook "R" "end"

  # ── Phase T: TEST SYNTHESIS ─────────────────────────────────────────────────
  PHASE="T"
  echo ""
  echo "  [Phase T] TEST SYNTHESIS — scanning test failures..."
  log_spiral_event "phase_start" "\"phase\":\"T\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "T" "start"
  _PHASE_TS_T=$(date +%s)
  TEST_OUTPUT="$SCRATCH_DIR/_test_stories_output.json"

  if checkpoint_phase_done "T"; then
    echo "  [T] Skipping (checkpoint: already done this iter)"
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] skipping test synthesis"
    echo '{"stories":[]}' >"$TEST_OUTPUT"
    write_checkpoint "$SPIRAL_ITER" "T"
  elif [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && spiral_should_skip_phase "T"; then
    _P_LVL=$(spiral_pressure_level)
    echo "  [T] Skipping (memory pressure: level $_P_LVL)"
    spiral_log_low_power "Phase T skipped (pressure level $_P_LVL, iter $SPIRAL_ITER)"
    echo '{"stories":[]}' >"$TEST_OUTPUT"
    write_checkpoint "$SPIRAL_ITER" "T"
  else
    _T_EXIT=0
    _T_START=$(date +%s)
    if [[ -n "$SPIRAL_CORE_BIN" ]]; then
      if [[ "${SPIRAL_TEST_SYNTH_TIMEOUT:-60}" -gt 0 ]] && command -v timeout &>/dev/null; then
        timeout --kill-after=30 "${SPIRAL_TEST_SYNTH_TIMEOUT}" \
          "$SPIRAL_CORE_BIN" synthesize \
          --prd "$PRD_FILE" \
          --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
          --output "$TEST_OUTPUT" \
          --repo-root "$REPO_ROOT" \
          ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
      else
        "$SPIRAL_CORE_BIN" synthesize \
          --prd "$PRD_FILE" \
          --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
          --output "$TEST_OUTPUT" \
          --repo-root "$REPO_ROOT" \
          ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
      fi
    else
      if [[ "${SPIRAL_TEST_SYNTH_TIMEOUT:-60}" -gt 0 ]] && command -v timeout &>/dev/null; then
        timeout --kill-after=30 "${SPIRAL_TEST_SYNTH_TIMEOUT}" \
          "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/synthesize_tests.py" \
          --prd "$PRD_FILE" \
          --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
          --output "$TEST_OUTPUT" \
          --repo-root "$REPO_ROOT" \
          ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
      else
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/synthesize_tests.py" \
          --prd "$PRD_FILE" \
          --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
          --output "$TEST_OUTPUT" \
          --repo-root "$REPO_ROOT" \
          ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
      fi
    fi
    _T_ELAPSED=$(($(date +%s) - _T_START))
    if [[ "$_T_EXIT" -eq 124 ]]; then
      echo "  [Phase T] WARNING: Test synthesis timed out after ${_T_ELAPSED}s (limit: ${SPIRAL_TEST_SYNTH_TIMEOUT}s) — using empty output"
      log_spiral_event "phase_timeout" "\"phase\":\"T\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_T_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_TEST_SYNTH_TIMEOUT}"
      echo '{"stories":[]}' >"$TEST_OUTPUT"
    elif [[ "$_T_EXIT" -ne 0 ]]; then
      echo "  [Phase T] WARNING: Test synthesis exited with status $_T_EXIT — continuing with partial/empty output"
    fi

    TEST_COUNT=$("$JQ" '.stories | length' "$TEST_OUTPUT" 2>/dev/null || echo "0")
    echo "  [T] Test synthesis complete — $TEST_COUNT story candidates from failures"

    write_checkpoint "$SPIRAL_ITER" "T"
  fi
  _PHASE_DUR_T=$(($(date +%s) - _PHASE_TS_T))
  log_spiral_event "phase_end" "\"phase\":\"T\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_T"
  notify_webhook "T" "end"

  # ── Phase M: MERGE ──────────────────────────────────────────────────────────
  PHASE="M"
  echo ""
  echo "  [Phase M] MERGE — deduplicating and patching prd.json..."
  log_spiral_event "phase_start" "\"phase\":\"M\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "M" "start"
  _PHASE_TS_M=$(date +%s)

  if checkpoint_phase_done "M"; then
    echo "  [M] Skipping (checkpoint: already done this iter)"
  else
    # ── Phase M backup: snapshot prd.json before merge ──────────────────────
    if [[ -f "$PRD_FILE" ]]; then
      mkdir -p "$SCRATCH_DIR/prd-backups"
      cp "$PRD_FILE" "$SCRATCH_DIR/prd-backups/prd-iter${SPIRAL_ITER}.json"
      # Keep only last 10 backups
      ls -t "$SCRATCH_DIR/prd-backups"/ | tail -n +11 | xargs -I{} rm -f "$SCRATCH_DIR/prd-backups/{}"
    fi

    # ── Phase M pre-check: validate _research_output.json schema ──────────
    if [[ ! -f "$RESEARCH_OUTPUT" ]]; then
      echo "  [M] WARNING: $RESEARCH_OUTPUT missing — skipping merge"
      write_checkpoint "$SPIRAL_ITER" "M"
    elif ! "$JQ" '.' "$RESEARCH_OUTPUT" >/dev/null 2>&1; then
      echo "  [M] WARNING: $RESEARCH_OUTPUT is not valid JSON — skipping merge"
      write_checkpoint "$SPIRAL_ITER" "M"
    elif ! "$JQ" -e '.stories' "$RESEARCH_OUTPUT" >/dev/null 2>&1; then
      echo "  [M] WARNING: $RESEARCH_OUTPUT missing 'stories' key — skipping merge"
      write_checkpoint "$SPIRAL_ITER" "M"
    else
      # ── Phase M validated — proceed with merge ──────────────────────────────

      OVERFLOW_FILE="$SCRATCH_DIR/_research_overflow.json"
      BEFORE_TOTAL=$("$JQ" '[.userStories | length] | .[0]' "$PRD_FILE")
      if [[ -n "$SPIRAL_CORE_BIN" ]]; then
        "$SPIRAL_CORE_BIN" merge \
          --prd "$PRD_FILE" \
          --research "$RESEARCH_OUTPUT" \
          --test-stories "$TEST_OUTPUT" \
          --overflow-in "$OVERFLOW_FILE" \
          --overflow-out "$OVERFLOW_FILE" \
          --max-new 50 \
          --max-pending "$SPIRAL_MAX_PENDING" \
          ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || true
      else
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/merge_stories.py" \
          --prd "$PRD_FILE" \
          --research "$RESEARCH_OUTPUT" \
          --test-stories "$TEST_OUTPUT" \
          --overflow-in "$OVERFLOW_FILE" \
          --overflow-out "$OVERFLOW_FILE" \
          --max-new 50 \
          --max-pending "$SPIRAL_MAX_PENDING" \
          ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || true
      fi
      AFTER_TOTAL=$("$JQ" '[.userStories | length] | .[0]' "$PRD_FILE")
      ADDED=$((AFTER_TOTAL - BEFORE_TOTAL))
      echo "  [M] Merge complete — $ADDED new stories added (total: $AFTER_TOTAL)"

      write_checkpoint "$SPIRAL_ITER" "M"

      # ── Tier 2: Post-merge assertions ──────────────────────────────────────
      spiral_assert_ids_unique "$PRD_FILE"
      spiral_assert_deps_dag "$PRD_FILE"
      spiral_assert_story_count_bounded "$PRD_FILE"
      spiral_assert_merge_no_story_loss "$BEFORE_TOTAL" "$AFTER_TOTAL"
      spiral_assert_pending_bounded "$PRD_FILE"
      spiral_assert_decomposition_integrity "$PRD_FILE"
      spiral_assert_dependency_completion_order "$PRD_FILE"

      # ── Phase M: Infer dependencies from filesTouch overlap ─────────────────
      _HINTS_FILE="$SCRATCH_DIR/_dependency_hints.json"
      echo "  [M] Inferring dependencies from filesTouch overlap..."
      SPIRAL_AUTO_INFER_DEPS="$SPIRAL_AUTO_INFER_DEPS" \
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/infer_dependencies.py" \
        --prd "$PRD_FILE" \
        --out-hints "$_HINTS_FILE" || true

    fi # end validation else
  fi

  # ── progress.txt rotation (before Phase I) ────────────────────────────────
  if [[ "$SPIRAL_PROGRESS_MAX_LINES" -gt 0 && -f "$REPO_ROOT/progress.txt" ]]; then
    _PROGRESS_LINES=$(wc -l <"$REPO_ROOT/progress.txt" 2>/dev/null || echo 0)
    if [[ "$_PROGRESS_LINES" -gt "$SPIRAL_PROGRESS_MAX_LINES" ]]; then
      _PROGRESS_ARCHIVE="$REPO_ROOT/progress-$(date +%Y%m%d-%H%M%S).txt"
      mv "$REPO_ROOT/progress.txt" "$_PROGRESS_ARCHIVE"
      touch "$REPO_ROOT/progress.txt"
      echo "  [spiral] progress.txt rotated ($_PROGRESS_LINES lines → $(basename "$_PROGRESS_ARCHIVE"))"
    fi
  fi

  _PHASE_DUR_M=$(($(date +%s) - _PHASE_TS_M))
  log_spiral_event "phase_end" "\"phase\":\"M\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_M"
  notify_webhook "M" "end"

  # ── Phase G: HUMAN GATE + Phase I: IMPLEMENT ───────────────────────────────
  PHASE="G"
  log_spiral_event "phase_start" "\"phase\":\"G\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "G" "start"
  _PHASE_TS_I=$(date +%s)
  if checkpoint_phase_done "I"; then
    echo "  [G+I] Skipping (checkpoint: gate and ralph already done this iter)"
  else
    prd_stats

    # ── Generate story review report for human gate (skip in auto-proceed mode) ──
    GATE_REPORTS_DIR="$SCRATCH_DIR/gate-reports"
    if [[ "$GATE_DEFAULT" != "proceed" ]]; then
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/story_review_report.py" \
        --prd "$PRD_FILE" \
        --iter "$SPIRAL_ITER" \
        --added "$ADDED" \
        --output "$GATE_REPORTS_DIR" \
        --open 2>/dev/null || true
    fi

    notify_webhook "G" "pending" "ok" "\"gate_report_path\":\"$GATE_REPORTS_DIR/latest-review.html\""
    echo ""
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║  [Phase G] HUMAN GATE — Iteration $SPIRAL_ITER"
    echo "  ╠══════════════════════════════════════════════════════╣"
    echo "  ║  New stories added:  $ADDED"
    echo "  ║  Total pending:      $PENDING"
    echo "  ║  Total stories:      $TOTAL ($DONE complete)"
    [[ -n "$SPIRAL_FOCUS" ]] &&
      echo "  ║  Focus:              $SPIRAL_FOCUS"
    echo "  ║  Review report:      $GATE_REPORTS_DIR/latest-review.html"
    echo "  ╠══════════════════════════════════════════════════════╣"
    echo "  ║  Options:"
    echo "  ║    proceed — run ralph to implement pending stories"
    echo "  ║    skip    — skip ralph, advance to check-done"
    echo "  ║    quit    — halt SPIRAL"
    echo "  ╚══════════════════════════════════════════════════════╝"
    echo ""
    if [[ -n "$GATE_DEFAULT" ]]; then
      GATE_INPUT="$GATE_DEFAULT"
      echo "  [G] Auto-gate: $GATE_INPUT"
    else
      printf "  Enter choice: "
      # Read from /dev/tty if available (handles piped stdin), else fall back to normal stdin
      if [[ -t 0 ]]; then
        read -r GATE_INPUT || GATE_INPUT="quit"
      else
        read -r GATE_INPUT </dev/tty 2>/dev/null || read -r GATE_INPUT || GATE_INPUT="quit"
      fi
    fi

    GATE_INPUT=$(echo "$GATE_INPUT" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')

    case "$GATE_INPUT" in
      quit | q | exit)
        echo "  [G] User quit — SPIRAL halted at iteration $SPIRAL_ITER"
        rm -f "$CHECKPOINT_FILE"
        exit 0
        ;;
      skip | s)
        echo "  [G] Skipping ralph — advancing to check-done"
        ;;
      proceed | p | "")
        echo "  [G] Proceeding to implementation..."

        # NEW ROUTING STEP
        echo "  [I-Pre] Routing stories to optimal models..."
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/route_stories.py" --prd "$PRD_FILE" --profile "$SPIRAL_MODEL_ROUTING"

        # ── DAG cycle detection ──────────────────────────────────────────
        DAG_SKIP_IMPL=0
        DAG_OUTPUT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/check_dag.py" "$PRD_FILE" 2>&1) || {
          echo "  [Phase I] WARNING: Dependency cycle detected — skipping implementation" >&2
          echo "$DAG_OUTPUT" >&2
          DAG_SKIP_IMPL=1
        }

        # ── Phase I: IMPLEMENT (Ralph) ──────────────────────────────────
        PHASE="I"
        log_spiral_event "phase_start" "\"phase\":\"I\",\"iteration\":$SPIRAL_ITER"
        notify_webhook "I" "start"
        echo ""

        # Short-circuit if nothing to implement
        prd_stats
        if [[ "$PENDING" -eq 0 ]]; then
          echo "  [Phase I] IMPLEMENT — skipping (no pending stories)"
        elif [[ "$DAG_SKIP_IMPL" -eq 1 ]]; then
          echo "  [Phase I] IMPLEMENT — skipping (dependency cycles detected — fix prd.json dependencies)"
        else
          # ── Adaptive memory: reduce workers and override model under pressure ──
          if [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]]; then
            _PRESSURE_LVL=$(spiral_pressure_level)
            if [[ "$_PRESSURE_LVL" -ge 2 ]]; then
              _REC_WORKERS=$(spiral_recommended_workers)
              if [[ -n "$_REC_WORKERS" && "$_REC_WORKERS" -lt "$RALPH_WORKERS" ]]; then
                spiral_log_low_power "Workers reduced: $RALPH_WORKERS -> $_REC_WORKERS (pressure level $_PRESSURE_LVL, iter $SPIRAL_ITER)"
                echo "  [memory] Pressure level $_PRESSURE_LVL — reducing workers: $RALPH_WORKERS -> $_REC_WORKERS"
                RALPH_WORKERS="$_REC_WORKERS"
              fi
              _REC_MODEL=$(spiral_recommended_model)
              if [[ -n "$_REC_MODEL" && -z "$SPIRAL_CLI_MODEL" ]]; then
                spiral_log_low_power "Model capped: $_REC_MODEL (pressure level $_PRESSURE_LVL, iter $SPIRAL_ITER)"
                echo "  [memory] Pressure level $_PRESSURE_LVL — model cap: $_REC_MODEL"
                SPIRAL_CLI_MODEL="$_REC_MODEL"
              fi
            fi
          fi

          # ── Dynamic worker recommendation (if not explicitly set) ─────────
          if [[ "$WORKERS_EXPLICIT" -eq 0 ]]; then
            _REC_OUTPUT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/recommend_workers.py" "$PRD_FILE" 2>/dev/null) || true
            if [[ -n "$_REC_OUTPUT" ]]; then
              # Log line is first, recommended count is last line
              echo "  $_REC_OUTPUT" | head -1
              _AUTO_WORKERS=$(echo "$_REC_OUTPUT" | tail -1)
              if [[ "$_AUTO_WORKERS" =~ ^[1-3]$ ]]; then
                RALPH_WORKERS="$_AUTO_WORKERS"
              fi
            fi
          fi

          # ── Tier 2: Save passes baseline before implementation ────────────
          spiral_assert_passes_save_baseline "$PRD_FILE"

          echo "  [Phase I] IMPLEMENT — running ralph ($RALPH_MAX_ITERS inner iterations)..."

          # ── Batch slicing: cap stories visible to ralph ──────────────────
          _BATCH_ACTIVE=0
          _FULL_PRD_BACKUP="$SCRATCH_DIR/_full_prd_backup.json"
          if [[ "$SPIRAL_STORY_BATCH_SIZE" -gt 0 && "$PENDING" -gt "$SPIRAL_STORY_BATCH_SIZE" ]]; then
            cp "$PRD_FILE" "$_FULL_PRD_BACKUP"
            "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/slice_prd.py" slice \
              "$PRD_FILE" "$SPIRAL_STORY_BATCH_SIZE" -o "$PRD_FILE" 2>/dev/null && {
              _BATCH_ACTIVE=1
              _SLICED_PENDING=$("$JQ" '[.userStories[] | select(.passes != true)] | length' "$PRD_FILE" 2>/dev/null || echo "?")
              echo "  [I] Batch: $PENDING pending → sliced to $_SLICED_PENDING (batch_size=$SPIRAL_STORY_BATCH_SIZE)"
            } || {
              echo "  [I] Batch: slice failed — using full PRD"
              cp "$_FULL_PRD_BACKUP" "$PRD_FILE"
            }
          fi

          echo "  [I] Pending stories ($PENDING):"
          if [[ -n "$SPIRAL_SKIP_STORY_IDS" ]]; then
            "$JQ" -r --arg ids "$SPIRAL_SKIP_STORY_IDS" \
              '.userStories[] | select(.passes != true) | select(.id as $sid | ($ids | split(",") | map(gsub("^\\s+|\\s+$";"")) | any(. == $sid)) | not) | "    [\(.id)] \(.title)"' \
              "$PRD_FILE" 2>/dev/null | head -20 || true
          else
            "$JQ" -r '.userStories[] | select(.passes != true) | "    [\(.id)] \(.title)"' "$PRD_FILE" \
              2>/dev/null | head -20 || true
          fi
          PENDING_SHOWN=$("$JQ" '[.userStories[] | select(.passes != true)] | length' "$PRD_FILE" 2>/dev/null || echo "$PENDING")
          [[ "$PENDING_SHOWN" -gt 20 ]] && echo "    ... and $((PENDING_SHOWN - 20)) more"
          echo ""

          # Note: model is now assigned per-story by lib/route_stories.py

          # Build --dry-run flag for ralph invocations
          _DRY_RUN_FLAG=""
          [[ "$DRY_RUN" -eq 1 ]] && _DRY_RUN_FLAG="--dry-run"

          RALPH_RAN=1
          PRE_RALPH_PRD_JSON=$(cat "$PRD_FILE")
          DONE_BEFORE=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")

          if [[ "$RALPH_WORKERS" -gt 1 ]]; then
            # ── Parallel mode with wave dispatch ───────────────────────────────
            # Pre-populate filesTouch hints from git history (best-effort)
            "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/populate_hints.py" \
              --prd "$PRD_FILE" --repo-root "$REPO_ROOT" 2>/dev/null || true

            _PARTITION_CMD="${SPIRAL_CORE_BIN:+$SPIRAL_CORE_BIN partition}"
            _PARTITION_CMD="${_PARTITION_CMD:-$SPIRAL_PYTHON $SPIRAL_HOME/lib/partition_prd.py}"
            TOTAL_WAVES=$($_PARTITION_CMD \
              --prd "$PRD_FILE" --list-waves 2>/dev/null || echo "1")
            echo "  [I] Parallel mode: $RALPH_WORKERS workers, $TOTAL_WAVES wave(s)"

            WAVE=0
            while true; do
              # Get story count for this wave level (recomputed from current prd.json)
              WAVE_STORY_COUNT=$($_PARTITION_CMD \
                --prd "$PRD_FILE" --wave-count "$WAVE" 2>/dev/null || echo "0")

              # No stories at this level — check if higher levels exist
              if [[ "$WAVE_STORY_COUNT" -eq 0 ]]; then
                REMAINING=$($_PARTITION_CMD \
                  --prd "$PRD_FILE" --list-waves 2>/dev/null || echo "0")
                if [[ "$WAVE" -ge "$REMAINING" ]]; then
                  echo "  [I] All waves processed — no more actionable stories"
                  break
                fi
                echo "  [I] Wave $((WAVE + 1)): 0 stories — skipping"
                WAVE=$((WAVE + 1))
                continue
              fi

              echo "  [I] ── Wave $((WAVE + 1)): $WAVE_STORY_COUNT stories ──"

              if [[ "$WAVE_STORY_COUNT" -eq 1 ]]; then
                # Single story — sequential fallback, skip worktree overhead entirely
                echo "  [I] Wave $((WAVE + 1)): 1 story — sequential fallback (no worktrees)"
                # Auto-detect tool: UT-* test stories → Codex; others → Claude
                _NEXT_SID=$("$JQ" -r '[.userStories[] | select(.passes != true)] | sort_by(.priority) | first | .id // ""' "$PRD_FILE" 2>/dev/null || echo "")
                if [[ "$_NEXT_SID" == UT-* ]]; then
                  _RALPH_TOOL="codex"
                  echo "  [I] Story $_NEXT_SID is a test story → routing to Codex"
                else
                  _RALPH_TOOL="claude"
                fi
                _I_EXIT=0
                _I_START=$(date +%s)
                if [[ "${SPIRAL_IMPL_TIMEOUT:-600}" -gt 0 ]] && command -v timeout &>/dev/null; then
                  timeout --kill-after=30 "${SPIRAL_IMPL_TIMEOUT}" bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" $_DRY_RUN_FLAG || _I_EXIT=$?
                else
                  bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" $_DRY_RUN_FLAG || _I_EXIT=$?
                fi
                _I_ELAPSED=$(($(date +%s) - _I_START))
                if [[ "$_I_EXIT" -eq 124 ]]; then
                  echo "  [I] WARNING: Ralph timed out after ${_I_ELAPSED}s (limit: ${SPIRAL_IMPL_TIMEOUT}s)"
                  log_spiral_event "phase_timeout" "\"phase\":\"I\",\"story_id\":\"$_NEXT_SID\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_I_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_IMPL_TIMEOUT}"
                fi
              else
                # Cap workers to story count so no worker sits idle
                WAVE_WORKERS="$RALPH_WORKERS"
                if [[ "$WAVE_STORY_COUNT" -lt "$RALPH_WORKERS" ]]; then
                  WAVE_WORKERS="$WAVE_STORY_COUNT"
                  echo "  [I] Wave $((WAVE + 1)): capping to $WAVE_WORKERS workers (only $WAVE_STORY_COUNT stories)"
                fi

                bash "$SPIRAL_HOME/lib/run_parallel_ralph.sh" \
                  "$WAVE_WORKERS" "$RALPH_MAX_ITERS" "$REPO_ROOT" "$PRD_FILE" \
                  "$SCRATCH_DIR" "$SPIRAL_RALPH" "$JQ" "$SPIRAL_PYTHON" \
                  "$MONITOR_TERMINALS" "$SPIRAL_HOME" "" || true
              fi

              WAVE=$((WAVE + 1))
            done
          else
            # ── Sequential mode (default) ────────────────────────────────────
            # Auto-detect tool: UT-* test stories → Codex; others → Claude
            _NEXT_SID=$("$JQ" -r '[.userStories[] | select(.passes != true)] | sort_by(.priority) | first | .id // ""' "$PRD_FILE" 2>/dev/null || echo "")
            if [[ "$_NEXT_SID" == UT-* ]]; then
              _RALPH_TOOL="codex"
              echo "  [I] Story $_NEXT_SID is a test story → routing to Codex"
            else
              _RALPH_TOOL="claude"
            fi
            _I_EXIT=0
            _I_START=$(date +%s)
            if [[ "${SPIRAL_IMPL_TIMEOUT:-600}" -gt 0 ]] && command -v timeout &>/dev/null; then
              timeout --kill-after=30 "${SPIRAL_IMPL_TIMEOUT}" bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" $_DRY_RUN_FLAG || _I_EXIT=$?
            else
              bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" $RALPH_MODEL_FLAG $_DRY_RUN_FLAG || _I_EXIT=$?
            fi
            _I_ELAPSED=$(($(date +%s) - _I_START))
            if [[ "$_I_EXIT" -eq 124 ]]; then
              echo "  [I] WARNING: Ralph timed out after ${_I_ELAPSED}s (limit: ${SPIRAL_IMPL_TIMEOUT}s) — partial progress saved"
              log_spiral_event "phase_timeout" "\"phase\":\"I\",\"story_id\":\"$_NEXT_SID\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_I_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_IMPL_TIMEOUT}"
            fi
          fi

          # ── Batch merge: restore full PRD with ralph's updates ─────────
          if [[ "$_BATCH_ACTIVE" -eq 1 && -f "$_FULL_PRD_BACKUP" ]]; then
            "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/slice_prd.py" merge \
              "$_FULL_PRD_BACKUP" "$PRD_FILE" -o "$PRD_FILE" 2>/dev/null && {
              echo "  [I] Batch: merged results back into full PRD"
            } || {
              echo "  [I] Batch: merge failed — keeping ralph's PRD as-is"
            }
            rm -f "$_FULL_PRD_BACKUP"
          fi

          DONE_AFTER=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")
          RALPH_PROGRESS=$((DONE_AFTER - DONE_BEFORE))

          if [[ "$RALPH_PROGRESS" -gt 0 ]]; then
            if [[ "$RALPH_WORKERS" -gt 1 ]]; then
              # run_parallel_ralph.sh already committed prd.json + per-worker code patches
              echo "  [I] Git: parallel mode — commits already applied by run_parallel_ralph.sh"
            else
              # Sequential mode: atomic commit per completed story
              POST_RALPH_PRD="$SCRATCH_DIR/_prd_post_ralph.json"
              cp "$PRD_FILE" "$POST_RALPH_PRD"

              # Identify newly completed stories vs pre-ralph baseline
              mapfile -t NEW_STORY_RECORDS < <(
                "$JQ" -r --argjson before "$PRE_RALPH_PRD_JSON" \
                  '[.userStories[] | . as $s |
                  select(.passes == true) |
                  select(($before.userStories | map(select(.id == $s.id and (.passes // false) == true)) | length) == 0)
                ] | .[] | "\(.id)|\(.title)"' "$PRD_FILE" 2>/dev/null
              ) || true

              if [[ ${#NEW_STORY_RECORDS[@]} -eq 0 ]]; then
                # Fallback: no story breakdown available — single bulk commit
                if git -C "$REPO_ROOT" add -A 2>/dev/null &&
                  git -C "$REPO_ROOT" commit -m "feat(spiral): complete $RALPH_PROGRESS stories (iter $SPIRAL_ITER)" 2>/dev/null; then
                  echo "  [I] Git: committed $RALPH_PROGRESS stories (fallback single commit)"
                else
                  echo "  [I] Git: commit skipped (nothing staged or git unavailable)"
                fi
              else
                # Restore prd.json to pre-ralph state; code changes remain as unstaged diffs
                # Use atomic temp+mv to avoid corruption if interrupted mid-write (Idea 3)
                printf '%s\n' "$PRE_RALPH_PRD_JSON" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE"

                # Stage all code changes except prd.json (goes into first story's commit)
                git -C "$REPO_ROOT" add -A 2>/dev/null || true
                git -C "$REPO_ROOT" restore --staged "$PRD_FILE" 2>/dev/null ||
                  git -C "$REPO_ROOT" reset HEAD "$PRD_FILE" 2>/dev/null || true

                ATOMIC_COUNT=0
                for record in "${NEW_STORY_RECORDS[@]}"; do
                  STORY_ID="${record%%|*}"
                  STORY_TITLE="${record#*|}"

                  # Merge this story's final record from post-ralph into current prd.json
                  UPDATED=$("$JQ" --arg id "$STORY_ID" \
                    --slurpfile full "$POST_RALPH_PRD" \
                    '(.userStories[] | select(.id == $id)) |= ([$full[0].userStories[] | select(.id == $id)] | .[0] // .)' \
                    "$PRD_FILE" 2>/dev/null) || true
                  # Use atomic temp+mv to avoid corruption if interrupted mid-write (Idea 3)
                  [[ -n "$UPDATED" ]] && { printf '%s\n' "$UPDATED" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE"; } || true

                  git -C "$REPO_ROOT" add "$PRD_FILE" 2>/dev/null || true
                  if git -C "$REPO_ROOT" commit -m "feat: $STORY_ID - $STORY_TITLE" 2>/dev/null; then
                    echo "  [I] Git: feat: $STORY_ID - $STORY_TITLE"
                    ATOMIC_COUNT=$((ATOMIC_COUNT + 1))
                  fi
                done

                # Ensure prd.json is fully synced to post-ralph final state
                cp "$POST_RALPH_PRD" "$PRD_FILE"
                git -C "$REPO_ROOT" add "$PRD_FILE" 2>/dev/null || true
                git -C "$REPO_ROOT" diff --cached --quiet 2>/dev/null ||
                  git -C "$REPO_ROOT" commit -m "chore: sync prd.json final state (spiral iter $SPIRAL_ITER)" 2>/dev/null || true

                echo "  [I] Git: $ATOMIC_COUNT atomic commits created"
              fi
            fi
            ZERO_PROGRESS_COUNT=0
            echo "  [I] Ralph completed $RALPH_PROGRESS new stories"
          else
            ZERO_PROGRESS_COUNT=$((ZERO_PROGRESS_COUNT + 1))
            echo "  [I] WARNING: Ralph made zero progress (streak: $ZERO_PROGRESS_COUNT)"
            if [[ "$ZERO_PROGRESS_COUNT" -ge 2 ]]; then
              echo ""
              echo "  ╔══════════════════════════════════════════════════════╗"
              echo "  ║  SPIRAL HALTED — 2 consecutive zero-progress iters  ║"
              echo "  ║  Pending stories may be blocked or require manual   ║"
              echo "  ║  intervention. Review prd.json and re-run.          ║"
              echo "  ╚══════════════════════════════════════════════════════╝"
              prd_stats
              echo ""
              "$JQ" -r '.userStories[] | select(.passes != true) | "  [PENDING] [\(.id)] \(.title)"' "$PRD_FILE" 2>/dev/null || true
              rm -f "$CHECKPOINT_FILE"
              exit $ERR_ZERO_PROGRESS
            fi
            echo "  [I] Continuing to check-done phase..."
          fi
          # ── Adaptive ralph budget based on velocity ─────────────────────────────
          if [[ "$RALPH_PROGRESS" -ge 5 ]]; then
            RALPH_MAX_ITERS=$((RALPH_MAX_ITERS + 20))
            echo "  [velocity] High ($RALPH_PROGRESS stories/iter) — ralph budget → $RALPH_MAX_ITERS"
          elif [[ "$RALPH_PROGRESS" -eq 0 ]]; then
            NEW_BUDGET=$((RALPH_MAX_ITERS / 2))
            [[ "$NEW_BUDGET" -lt 30 ]] && NEW_BUDGET=30
            RALPH_MAX_ITERS="$NEW_BUDGET"
            echo "  [velocity] Zero — ralph budget → $RALPH_MAX_ITERS"
          fi
        fi # end PENDING > 0 block
        ;;
      *)
        echo "  [G] Unrecognized input '$GATE_INPUT' — treating as skip"
        ;;
    esac

    write_checkpoint "$SPIRAL_ITER" "I"

    # ── Tier 2: Verify passes didn't regress during implementation ────────
    spiral_assert_passes_monotonic "$PRD_FILE"
    spiral_assert_decomposition_integrity "$PRD_FILE"
    spiral_assert_dependency_completion_order "$PRD_FILE"
  fi
  _PHASE_DUR_I=$(($(date +%s) - _PHASE_TS_I))
  log_spiral_event "phase_end" "\"phase\":\"I\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_I"
  notify_webhook "I" "end"
  log_spiral_event "phase_end" "\"phase\":\"G\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_I"
  notify_webhook "G" "end"

  # ── Phase V: VALIDATE (test suite) ────────────────────────────────────────
  PHASE="V"
  echo ""
  echo "  [Phase V] VALIDATE — running test suite..."
  log_spiral_event "phase_start" "\"phase\":\"V\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "V" "start"
  _PHASE_TS_V=$(date +%s)

  if checkpoint_phase_done "V"; then
    echo "  [V] Skipping (checkpoint: already done this iter)"
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] skipping validate — assuming pass"
    VALIDATE_EXIT=0
    write_checkpoint "$SPIRAL_ITER" "V"
  elif [[ "$RALPH_RAN" -eq 0 ]]; then
    echo "  [V] Skipping (ralph did not run — test results unchanged)"
    write_checkpoint "$SPIRAL_ITER" "V"
  else
    # Run the project's validation command (with optional timeout)
    _VALIDATE_EXIT=0
    if [[ "${SPIRAL_VALIDATE_TIMEOUT:-300}" -gt 0 ]] && command -v timeout &>/dev/null; then
      _VALIDATE_START=$(date +%s)
      (cd "$REPO_ROOT" && timeout --kill-after=30 "${SPIRAL_VALIDATE_TIMEOUT}" bash -c "eval \"\$SPIRAL_VALIDATE_CMD\"" 2>&1) || _VALIDATE_EXIT=$?
      _VALIDATE_ELAPSED=$(($(date +%s) - _VALIDATE_START))
      if [[ "$_VALIDATE_EXIT" -eq 124 ]]; then
        echo ""
        echo "  [Phase V] WARNING: Phase V timed out after ${_VALIDATE_ELAPSED}s — treating as validation failure"
        log_spiral_event "phase_timeout" "\"phase\":\"V\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_VALIDATE_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_VALIDATE_TIMEOUT}"
        _VALIDATE_EXIT=1
      fi
    else
      (cd "$REPO_ROOT" && eval "$SPIRAL_VALIDATE_CMD" 2>&1) || _VALIDATE_EXIT=$?
    fi

    # Print summary from the freshest report
    "$SPIRAL_PYTHON" - <<PYEOF
import os, json, sys
d = '$SPIRAL_REPORTS_DIR'
if not os.path.isdir(d):
    print("  [V] No test-reports directory found")
    sys.exit(0)
subdirs = sorted([x for x in os.listdir(d) if os.path.isdir(os.path.join(d,x))], reverse=True)
for s in subdirs:
    p = os.path.join(d, s, 'report.json')
    if os.path.isfile(p):
        r = json.load(open(p, encoding='utf-8'))
        sm = r.get('summary', {})
        print(f"  [V] {s}: {sm.get('passed',0)}/{sm.get('total',0)} pass, {sm.get('failed',0)} failed, {sm.get('errored',0)} errored")
        sys.exit(0)
print("  [V] No report found")
PYEOF

    # ── Optional: Lighthouse audit ──────────────────────────────────────────
    if [[ "${SPIRAL_LIGHTHOUSE:-0}" == "1" ]] && command -v npx &>/dev/null; then
      LIGHTHOUSE_URL="${SPIRAL_LIGHTHOUSE_URL:-http://localhost:5173}"
      LIGHTHOUSE_OUT="$REPO_ROOT/$SPIRAL_REPORTS_DIR/lighthouse-iter-${SPIRAL_ITER}.json"
      echo "  [V] Running Lighthouse audit on $LIGHTHOUSE_URL..."
      npx lighthouse "$LIGHTHOUSE_URL" \
        --output=json --output-path="$LIGHTHOUSE_OUT" \
        --chrome-flags="--headless --no-sandbox" \
        --only-categories=performance,accessibility,best-practices \
        --quiet 2>/dev/null || true

      # Extract and print scores
      if [[ -f "$LIGHTHOUSE_OUT" ]]; then
        "$SPIRAL_PYTHON" - <<PYEOF
import json, sys
try:
    r = json.load(open('$LIGHTHOUSE_OUT', encoding='utf-8'))
    cats = r.get('categories', {})
    scores = {k: int(v.get('score', 0) * 100) for k, v in cats.items()}
    parts = ' | '.join(f'{k}: {v}%' for k, v in scores.items())
    print(f'  [V] Lighthouse: {parts}')
    # Warn on low scores
    for k, v in scores.items():
        if v < ${SPIRAL_LIGHTHOUSE_THRESHOLD:-50}:
            print(f'  [V] WARNING: {k} score {v}% below threshold')
except Exception as e:
    print(f'  [V] Lighthouse parse error: {e}')
PYEOF
      fi
    fi

    # ── Optional: Chrome DevTools screenshot ───────────────────────────────
    if [[ -n "${SPIRAL_DEV_URL:-}" ]]; then
      _SCREENSHOT_DIR="$SCRATCH_DIR/screenshots"
      mkdir -p "$_SCREENSHOT_DIR"
      _SCREENSHOT_TS=$(date +%Y%m%d-%H%M%S)
      _SCREENSHOT_PATH="$_SCREENSHOT_DIR/iter-${SPIRAL_ITER}-${_SCREENSHOT_TS}.png"
      echo "  [V] Taking screenshot of $SPIRAL_DEV_URL..."

      # Use Claude agent with Chrome DevTools MCP to navigate + screenshot
      _SCREENSHOT_PROMPT="Navigate to $SPIRAL_DEV_URL using mcp__chrome-devtools__navigate_page, wait for it to load, then take a screenshot using mcp__chrome-devtools__take_screenshot and save the result. Output only the word DONE when finished."
      if (
        unset CLAUDECODE
        claude -p "$_SCREENSHOT_PROMPT" \
          --allowedTools "Bash,mcp__chrome-devtools__navigate_page,mcp__chrome-devtools__take_screenshot,mcp__chrome-devtools__wait_for" \
          --max-turns 5 \
          --dangerously-skip-permissions \
          2>/dev/null
      ) | grep -qi "done"; then
        # Chrome DevTools saves screenshots via its own mechanism;
        # check if a screenshot was produced in the scratch dir
        if ls "$_SCREENSHOT_DIR"/iter-${SPIRAL_ITER}-*.png 1>/dev/null 2>&1; then
          echo "  [V] Screenshot saved to $_SCREENSHOT_DIR/"
        else
          echo "  [V] Screenshot command ran but no file was saved (Chrome DevTools MCP may not be available)"
        fi
      else
        echo "  [V] Screenshot skipped (Chrome DevTools MCP not available or failed)"
      fi
    fi

    # ── Optional: Pinchtab shell-driven E2E assertions ──────────────────────
    # Runs AFTER pytest and after the optional Chrome DevTools screenshot.
    # Pinchtab is a persistent HTTP browser server — called from shell, not
    # from inside a Claude agent turn. Text mode is 5-13x cheaper in tokens.
    if [[ -n "${SPIRAL_PINCHTAB_URL:-}" ]]; then
      _PINCHTAB_EXIT=0
      if [[ -n "${SPIRAL_PINCHTAB_E2E_CMD:-}" ]]; then
        # User-supplied E2E script (login flows, multi-step assertions)
        echo "  [V] Running pinchtab E2E: $SPIRAL_PINCHTAB_E2E_CMD"
        (cd "$REPO_ROOT" && eval "$SPIRAL_PINCHTAB_E2E_CMD" 2>&1) || _PINCHTAB_EXIT=$?
      elif [[ -n "${SPIRAL_DEV_URL:-}" ]] && command -v pinchtab &>/dev/null; then
        # Default: nav to dev URL, extract text, print first 20 lines
        echo "  [V] Pinchtab E2E: navigating to $SPIRAL_DEV_URL..."
        pinchtab --server "$SPIRAL_PINCHTAB_URL" nav "$SPIRAL_DEV_URL" 2>/dev/null || _PINCHTAB_EXIT=$?
        if [[ "$_PINCHTAB_EXIT" -eq 0 ]]; then
          _PINCHTAB_TEXT=$(pinchtab --server "$SPIRAL_PINCHTAB_URL" text 2>/dev/null || true)
          if [[ -n "$_PINCHTAB_TEXT" ]]; then
            echo "  [V] Pinchtab page text (first 20 lines):"
            echo "$_PINCHTAB_TEXT" | head -20 | sed 's/^/    /'
          else
            echo "  [V] Pinchtab: page loaded (no text content extracted)"
          fi
        else
          echo "  [V] WARNING: pinchtab nav failed (exit $_PINCHTAB_EXIT) — E2E step skipped"
        fi
      elif ! command -v pinchtab &>/dev/null; then
        echo "  [V] Pinchtab E2E skipped (pinchtab CLI not found — install with: npm install -g pinchtab)"
      else
        echo "  [V] Pinchtab E2E skipped (SPIRAL_DEV_URL not set — set it to enable nav+text assertions)"
      fi

      if [[ "$_PINCHTAB_EXIT" -ne 0 ]]; then
        echo "  [V] WARNING: Pinchtab E2E step failed (exit $_PINCHTAB_EXIT) — does not affect validation result"
      fi
    fi

    write_checkpoint "$SPIRAL_ITER" "V"
  fi
  _PHASE_DUR_V=$(($(date +%s) - _PHASE_TS_V))
  log_spiral_event "phase_end" "\"phase\":\"V\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_V"
  notify_webhook "V" "end"

  # ── Phase P: PUSH ──────────────────────────────────────────────────────────
  echo ""
  echo "  [Phase P] PUSH — pushing commits to origin/main..."
  if git -C "$REPO_ROOT" push origin main 2>&1; then
    echo "  [P] Pushed to origin/main successfully"
  else
    echo "  [P] WARNING: Push to origin/main failed (check remote/connectivity)"
  fi

  # ── Phase C: CHECK DONE ─────────────────────────────────────────────────────
  PHASE="C"
  echo ""
  echo "  [Phase C] CHECK DONE..."
  log_spiral_event "phase_start" "\"phase\":\"C\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "C" "start"
  _PHASE_TS_C=$(date +%s)

  _CHECK_DONE_RC=0
  if [[ -n "$SPIRAL_CORE_BIN" ]]; then
    "$SPIRAL_CORE_BIN" check-done \
      --prd "$PRD_FILE" \
      --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" || _CHECK_DONE_RC=$?
  else
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/check_done.py" \
      --prd "$PRD_FILE" \
      --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
      --skip-ids "${SPIRAL_SKIP_STORY_IDS:-}" || _CHECK_DONE_RC=$?
  fi
  if [[ "$_CHECK_DONE_RC" -eq 0 ]]; then
    rm -f "$CHECKPOINT_FILE"
    echo ""
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║   *** SPIRAL COMPLETE! ***                           ║"
    echo "  ║   All stories implemented and tests passing.         ║"
    echo "  ║   Iterations: $SPIRAL_ITER / $MAX_SPIRAL_ITERS"
    echo "  ╚══════════════════════════════════════════════════════╝"

    if [[ -f "$REPO_ROOT/results.tsv" ]]; then
      echo ""
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/spiral_report.py" --results "$REPO_ROOT/results.tsv" 2>/dev/null || true
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/spiral_dashboard.py" \
        --prd "$PRD_FILE" --results "$REPO_ROOT/results.tsv" \
        --retries "$REPO_ROOT/retry-counts.json" --progress "$REPO_ROOT/progress.txt" \
        --output "$SCRATCH_DIR/dashboard.html" --open 2>/dev/null || true
    fi

    SESSION_END=$(date +%s)
    SESSION_MINUTES=$(((SESSION_END - SESSION_START) / 60))
    echo "  Session: ${SESSION_MINUTES}m total, $SPIRAL_ITER iterations"

    # ── Write iteration summary (US-039) ──────────────────────────────────
    write_iter_summary

    # ── Run SPIRAL_ON_COMPLETE hook (US-049) ──────────────────────────────
    if [[ -n "${SPIRAL_ON_COMPLETE:-}" ]]; then
      _HOOK_PREVIEW="${SPIRAL_ON_COMPLETE:0:80}"
      echo "  [hook] Running SPIRAL_ON_COMPLETE: ${_HOOK_PREVIEW}..."
      if eval "$SPIRAL_ON_COMPLETE"; then
        echo "  [hook] SPIRAL_ON_COMPLETE succeeded"
      else
        echo "  [hook] WARNING: SPIRAL_ON_COMPLETE exited with code $? (ignored)"
      fi
    fi

    exit 0
  fi

  # Clear checkpoint before next iteration (crash in next iter starts that iter fresh)
  rm -f "$CHECKPOINT_FILE"
  prd_stats
  echo "  [C] Not done yet — $PENDING stories remaining"
  if [[ "${RALPH_PROGRESS:-0}" -gt 0 ]]; then
    ITERS_LEFT=$(((PENDING + RALPH_PROGRESS - 1) / RALPH_PROGRESS))
    echo "  [C] Velocity: ~${RALPH_PROGRESS} stories/iter | ~${ITERS_LEFT} more iters to completion"
  fi

  # ── Tier 2: Full re-validation between iterations ──────────────────────
  spiral_assert_prd_valid "$PRD_FILE"
  spiral_assert_no_orphan_tmpfiles
  spiral_assert_iteration_progress "${ZERO_PROGRESS_COUNT:-0}" "${SPIRAL_MAX_ZERO_PROGRESS:-3}"
  spiral_assert_checkpoint_coherent "$SPIRAL_ITER"
  spiral_assert_pending_bounded "$PRD_FILE"

  # Reset phase order tracker for next iteration
  rm -f "${SCRATCH_DIR:-/tmp}/_last_phase"

  # ── Write iteration summary (US-039) ──────────────────────────────────
  write_iter_summary

  # ── Iteration dashboard ─────────────────────────────────────────────────
  ITER_END=$(date +%s)
  ITER_DURATION=$((ITER_END - ITER_START))
  ITER_MINUTES=$((ITER_DURATION / 60))
  echo ""
  echo "  ┌─ Iteration $SPIRAL_ITER Summary ─────────────────┐"
  echo "  │  Stories:   +${RALPH_PROGRESS:-0} completed, $PENDING remaining"
  echo "  │  Duration:  ${ITER_MINUTES}m (${ITER_DURATION}s)"
  echo "  │  Phases:    R=${_PHASE_DUR_R}s T=${_PHASE_DUR_T}s M=${_PHASE_DUR_M}s I=${_PHASE_DUR_I}s V=${_PHASE_DUR_V}s C=${_PHASE_DUR_C}s"
  if [[ "${RALPH_PROGRESS:-0}" -gt 0 && "$ITER_DURATION" -gt 0 ]]; then
    VEL=$(awk "BEGIN {printf \"%.1f\", ${RALPH_PROGRESS} / ($ITER_DURATION / 3600.0)}")
    echo "  │  Velocity:  ${VEL} stories/hour"
  fi
  if [[ -f "$REPO_ROOT/results.tsv" ]]; then
    _ITER_COST=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/cost_check.py" \
      --results "$REPO_ROOT/results.tsv" 2>/dev/null | head -1) || true
    [[ -n "$_ITER_COST" ]] && echo "  │  ${_ITER_COST#*] }"
  fi
  echo "  └──────────────────────────────────────────────────┘"

  # ── Generate & open iteration dashboard ─────────────────────────────────────
  if [[ -f "$REPO_ROOT/results.tsv" ]]; then
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/spiral_dashboard.py" \
      --prd "$PRD_FILE" --results "$REPO_ROOT/results.tsv" \
      --retries "$REPO_ROOT/retry-counts.json" --progress "$REPO_ROOT/progress.txt" \
      --output "$SCRATCH_DIR/dashboard.html" --open 2>/dev/null || true
  fi

  # ── Adaptive cooldown under memory pressure ─────────────────────────────────
  if [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]]; then
    _PRESSURE_LVL=$(spiral_pressure_level)
    if [[ "$_PRESSURE_LVL" -ge 2 ]]; then
      _COOLDOWN=$((_PRESSURE_LVL * 15))
      echo "  [memory] Pressure cooldown: ${_COOLDOWN}s (level $_PRESSURE_LVL)"
      spiral_log_low_power "Inter-iteration cooldown: ${_COOLDOWN}s (level $_PRESSURE_LVL, iter $SPIRAL_ITER)"
      sleep "$_COOLDOWN"
    fi
  fi

  # ── Time limit check — stop cleanly after completing this iteration ────────
  if [[ "$SESSION_DEADLINE" -gt 0 ]]; then
    _NOW_TS=$(date +%s)
    _REMAINING_SECS=$((SESSION_DEADLINE - _NOW_TS))
    if [[ "$_REMAINING_SECS" -le 0 ]]; then
      echo "  [time] Time limit of ${TIME_LIMIT_MINS}m reached — stopping after iteration $SPIRAL_ITER"
      echo ""
      prd_stats
      SESSION_END=$(date +%s)
      SESSION_MINUTES=$(((SESSION_END - SESSION_START) / 60))
      echo ""
      echo "  ╔══════════════════════════════════════════════════════╗"
      echo "  ║  SPIRAL stopped: time limit reached (${TIME_LIMIT_MINS}m)         ║"
      echo "  ║  Stories: $DONE/$TOTAL complete ($PENDING pending)   ║"
      echo "  ║  Session: ${SESSION_MINUTES}m, $SPIRAL_ITER iterations              ║"
      echo "  ╚══════════════════════════════════════════════════════╝"
      if [[ -f "$REPO_ROOT/results.tsv" ]]; then
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/spiral_report.py" --results "$REPO_ROOT/results.tsv" 2>/dev/null || true
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/spiral_dashboard.py" \
          --prd "$PRD_FILE" --results "$REPO_ROOT/results.tsv" \
          --retries "$REPO_ROOT/retry-counts.json" --progress "$REPO_ROOT/progress.txt" \
          --output "$SCRATCH_DIR/dashboard.html" --open 2>/dev/null || true
      fi
      exit 0
    else
      _REM_MINS=$(((_REMAINING_SECS + 59) / 60))
      echo "  [time] ~${_REM_MINS}m remaining"
    fi
  fi

  _PHASE_DUR_C=$(($(date +%s) - _PHASE_TS_C))
  log_spiral_event "phase_end" "\"phase\":\"C\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_C"
  notify_webhook "C" "end"
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
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/spiral_report.py" --results "$REPO_ROOT/results.tsv" 2>/dev/null || true
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/spiral_dashboard.py" \
    --prd "$PRD_FILE" --results "$REPO_ROOT/results.tsv" \
    --retries "$REPO_ROOT/retry-counts.json" --progress "$REPO_ROOT/progress.txt" \
    --output "$SCRATCH_DIR/dashboard.html" --open 2>/dev/null || true
fi

SESSION_END=$(date +%s)
SESSION_MINUTES=$(((SESSION_END - SESSION_START) / 60))
echo "  Session: ${SESSION_MINUTES}m total, $SPIRAL_ITER iterations"

exit 0

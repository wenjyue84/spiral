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
MAX_SPIRAL_ITERS=20
GATE_DEFAULT="" # empty = interactive; "proceed"|"skip"|"quit" = auto
STATUS_ONLY=0   # 1 = print session state and exit (--status)
RALPH_MAX_ITERS=120
SKIP_RESEARCH=1                              # 1 = skip Phase R (Claude web research); T and M still run (default off; enable via UI toggle or SKIP_RESEARCH=0 in spiral.config.sh)
RALPH_WORKERS=1                              # >1 = parallel mode (git worktrees + docker lock)
WORKERS_EXPLICIT=0                           # 1 = user passed --ralph-workers explicitly
CAPACITY_LIMIT=50                            # Phase R is skipped when PENDING exceeds this threshold
MONITOR_TERMINALS=1                          # 1 = open a terminal window per worker to tail logs
SPIRAL_CONFIG_PATH=""                        # explicit --config path
SPIRAL_CLI_PRD=""                            # explicit --prd path override
SPIRAL_CLI_MODEL=""                          # explicit --model override (haiku|sonnet|opus)
SPIRAL_CLI_FOCUS=""                          # explicit --focus override
SPIRAL_FOCUS_TAGS=""                         # comma-separated tags filter (--focus-tags)
TIME_LIMIT_MINS=0                            # 0 = no limit; >0 = stop after N minutes (--time-limit or --until)
DRY_RUN=0                                    # 1 = dry-run mode: skip API calls (R, T, I, V) but run control flow
SKIP_CONFLICT_PREFLIGHT=0                    # 1 = bypass pre-flight cross-story conflict detection (--skip-conflict-preflight)
ALLOW_UNSAFE_STORIES=0                       # 1 = log injection warnings but do not block stories (--allow-unsafe-stories)
ALLOW_EXEC_WRITES=0                          # 1 = allow LLM to write executable files outside src/ and tests/ (--allow-exec-writes)
NO_CASCADE_SKIP=0                            # 1 = disable dependency cascade skip (--no-cascade-skip)
DOCTOR_MODE=0                                # 1 = run dependency check and exit (--doctor)
REPLAY_STORY_ID=""                           # "" = normal mode; "US-XXX" = replay that story only (--replay)
REPLAY_FROM_PHASE=""                         # "" = start from Phase I; "V" = skip Phase I (--from-phase)
REPLAY_HINT=""                               # extra context injected into Phase I system prompt (--hint)
ROLLBACK_STORY_ID=""                         # "" = normal mode; "US-XXX" = rollback that story's commit (--rollback)
UNDO_STORY_ID=""                             # "" = normal mode; "US-XXX" = replay undo log for that story (--undo)
BENCHMARK_STORY_ID=""                        # "" = normal mode; "US-XXX" = benchmark that story (--benchmark)
BENCHMARK_MODELS=""                          # comma-separated model names for --models (e.g., "claude-opus-4-6,claude-sonnet-4-6")
RESET_CHECKPOINT=0                           # 1 = remove _checkpoint.json and start fresh (--reset)
MIGRATE_MODE=0                               # 1 = run prd.json schema migration and exit (--migrate)
ARCHIVE_MODE=0                               # 1 = archive completed stories and exit (--archive-done)
CHANGELOG_MODE=0                             # 1 = generate CHANGELOG.md via git-cliff and exit
SHOW_DOCS_MODE=0                             # 1 = list generated API docs and exit (--changelog)
STALE_REPORT_MODE=0                          # 1 = print stale stories and exit (--stale-report)
FLAKY_REPORT_MODE=0                          # 1 = print flaky test quarantine report and exit (--flaky-tests report)
CALIBRATION_REPORT_MODE=0                    # 1 = print calibration report and exit (--calibration-report)
SPIRAL_LOG_LEVEL="${SPIRAL_LOG_LEVEL:-INFO}" # DEBUG|INFO|WARN|ERROR (case-insensitive)

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
    --no-cascade-skip)
      NO_CASCADE_SKIP=1
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
    --skip-conflict-preflight)
      SKIP_CONFLICT_PREFLIGHT=1
      shift
      ;;
    --allow-unsafe-stories)
      ALLOW_UNSAFE_STORIES=1
      shift
      ;;
    --allow-exec-writes)
      ALLOW_EXEC_WRITES=1
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
    --from-phase)
      REPLAY_FROM_PHASE="$2"
      shift 2
      ;;
    --hint)
      REPLAY_HINT="$2"
      shift 2
      ;;
    --rollback)
      ROLLBACK_STORY_ID="$2"
      shift 2
      ;;
    --undo)
      UNDO_STORY_ID="$2"
      shift 2
      ;;
    --benchmark)
      BENCHMARK_STORY_ID="$2"
      shift 2
      ;;
    --models)
      BENCHMARK_MODELS="$2"
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
    --show-docs)
      SHOW_DOCS_MODE=1
      shift
      ;;
    --stale-report)
      STALE_REPORT_MODE=1
      shift
      ;;
    --flaky-tests)
      # Accept: --flaky-tests report
      if [[ "${2:-}" == "report" ]]; then
        FLAKY_REPORT_MODE=1
        shift 2
      else
        echo "[spiral] ERROR: --flaky-tests requires a subcommand (e.g. 'report')" >&2
        exit 1
      fi
      ;;
    --calibration-report)
      CALIBRATION_REPORT_MODE=1
      shift
      ;;
    --log-level)
      SPIRAL_LOG_LEVEL="${2^^}" # normalise to upper-case
      shift 2
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
    --list-plugins)
      # Load and list all plugins, then exit
      source "$SPIRAL_HOME/lib/plugin_system.sh"
      load_plugins "$SPIRAL_HOME"
      list_plugins
      exit 0
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
      echo "  --no-cascade-skip          Disable dependency cascade skip propagation (debug)"
      echo "  --model haiku|sonnet|opus  Claude model override (default: auto-route by story complexity)"
      echo "  --focus TEXT               Focus iteration on a theme (e.g., 'performance', 'security')"
      echo "  --focus-tags TAG,TAG       Only implement stories matching at least one tag (e.g., 'frontend,auth')"
      echo "  --prd PATH                 Path to prd.json (default: prd.json in current directory)"
      echo "  --config PATH              Path to spiral.config.sh (default: \$REPO_ROOT/spiral.config.sh)"
      echo "  --time-limit N             Stop after N minutes (e.g., 60, 90, 120)"
      echo "  --until HH:MM              Stop at a wall-clock time (e.g., 14:30, 18:00)"
      echo "  --dry-run                  Test loop control flow without API calls"
      echo "  --skip-conflict-preflight  Bypass pre-flight cross-story conflict detection (parallel mode)"
      echo "  --allow-unsafe-stories     Warn but do NOT block stories with prompt injection patterns (use with caution)"
      echo "  --allow-exec-writes        Allow LLM to write executable files outside src/ and tests/ (sets SPIRAL_ALLOW_EXEC_WRITES=1)"
      echo "  --doctor                   Check all runtime dependencies and exit"
      echo "  --replay STORY_ID          Re-run a single story in an isolated worktree (Phases I+V only)"
      echo "  --from-phase PHASE_LETTER  Used with --replay: start from this phase (I or V); reuses existing worktree"
      echo "  --hint TEXT                Used with --replay: inject extra context into Phase I system prompt"
      echo "  --rollback STORY_ID        Revert a passed story's git commit and reset its prd.json status"
      echo "  --undo STORY_ID            Replay undo log in reverse, restoring worktree to pre-attempt state"
      echo "  --reset                    Remove checkpoint and start fresh from iteration 1"
      echo "  --migrate                  Migrate prd.json to current schema version and exit"
      echo "  --archive-done             Archive completed stories to prd-archive.json and exit"
      echo "  --changelog                Generate CHANGELOG.md via git-cliff and exit"
      echo "  --show-docs                List generated API documentation with story ID mappings and exit"
      echo "  --stale-report             Print stories inactive beyond SPIRAL_STALE_DAYS (default: 7) and exit"
      echo "  --flaky-tests report       Print quarantined flaky test registry and exit"
      echo "  --calibration-report       Print actual vs estimated complexity calibration data and exit"
      echo "  --list-plugins             List all loaded plugins and their hooks, then exit"
      echo "  --log-level DEBUG|INFO|WARN|ERROR  Output verbosity (default: INFO; can also set SPIRAL_LOG_LEVEL env var)"
      echo "  --status                   Print session state and story counts, then exit"
      echo "  --version                  Print SPIRAL version (git describe) and exit"
      echo ""
      echo "Config: Place spiral.config.sh in project root (or use --config)."
      echo "  See templates/spiral.config.example.sh for all variables."
      echo ""
      echo "Phases per iteration: R(esearch) → T(est synth) → M(erge) → G(ate) → I(mplement) → V(alidate) → C(heck done)"
      echo ""
      echo "Exit Codes:"
      echo "   0  Success — all stories passed or operation completed OK"
      echo "   2  ERR_BAD_USAGE       — wrong CLI arguments or unknown flag"
      echo "   3  ERR_CONFIG          — missing or invalid spiral.config.sh value"
      echo "   4  ERR_MISSING_DEP     — required tool not found (jq, ralph.sh, …)"
      echo "   5  ERR_PRD_NOT_FOUND   — prd.json file not found"
      echo "   6  ERR_PRD_CORRUPT     — prd.json corrupt and unrecoverable"
      echo "   7  ERR_SCHEMA_VERSION  — prd.json schemaVersion too new for SPIRAL"
      echo "   8  ERR_COST_CEILING    — spend cap (SPIRAL_COST_CEILING) reached"
      echo "   9  ERR_ZERO_PROGRESS   — zero-progress stall; all pending blocked"
      echo "  10  ERR_REPLAY_FAILED   — --replay: story implementation failed"
      echo "  11  ERR_STORY_NOT_FOUND — story ID passed to --replay not in prd.json"
      echo "  12  ERR_ROLLBACK_FAILED — --rollback: git revert or guard failed"
      echo "  13  ERR_MAX_ITERS       — max iterations reached; stories remain"
      echo "  14  ERR_API_DOWN        — Claude API unreachable at startup probe"
      echo "  15  ERR_CASCADE_ABORT   — consecutive story failures exceeded fan-out cap"
      echo " 130  (signal)            — interrupted by SIGINT (Ctrl-C)"
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
  uv run python "$SPIRAL_HOME/lib/tools/setup.py"
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
  if [[ -f "$_sc" && -x "$_sc" ]]; then
    SPIRAL_CORE_BIN="$_sc"
    break
  fi
done
[[ -n "$SPIRAL_CORE_BIN" ]] && echo "[spiral] spiral-core: $SPIRAL_CORE_BIN (Rust hot-path active)" || true

SPIRAL_RALPH="${SPIRAL_RALPH:-$SPIRAL_HOME/ralph/ralph.sh}"
SPIRAL_RESEARCH_PROMPT="${SPIRAL_RESEARCH_PROMPT:-$SPIRAL_HOME/templates/research_prompt.example.md}"
SPIRAL_GEMINI_PROMPT="${SPIRAL_GEMINI_PROMPT:-}"
SPIRAL_VALIDATE_CMD="${SPIRAL_VALIDATE_CMD:-$SPIRAL_PYTHON tests/run_tests.py --report-dir test-reports}"
SPIRAL_MAX_AI_SUGGEST="${SPIRAL_MAX_AI_SUGGEST:-5}"                            # Phase A: max AI-generated story suggestions per iteration (gap analysis)
SPIRAL_TEST_STORY_MIN_COMPLEXITY="${SPIRAL_TEST_STORY_MIN_COMPLEXITY:-medium}" # Source 5: min story complexity to generate test stories
SPIRAL_REPORTS_DIR="${SPIRAL_REPORTS_DIR:-test-reports}"
SPIRAL_STORY_PREFIX="${SPIRAL_STORY_PREFIX:-US}"
SPIRAL_VERSION="${SPIRAL_VERSION:-$(git -C "$SPIRAL_HOME" describe --tags --always --dirty=+ 2>/dev/null || echo "unknown")}"
export SPIRAL_VERSION
STREAM_FMT="${SPIRAL_STREAM_FMT:-$SPIRAL_HOME/ralph/stream-formatter.mjs}"
SPIRAL_MODEL_ROUTING="${SPIRAL_MODEL_ROUTING:-auto}"
SPIRAL_RESEARCH_MODEL="${SPIRAL_RESEARCH_MODEL:-haiku}"
SPIRAL_VALIDATION_MODEL="${SPIRAL_VALIDATION_MODEL:-haiku}"
SPIRAL_MERGE_MODEL="${SPIRAL_MERGE_MODEL:-haiku}"
# ── US-354: SPIRAL_PHASE_MODEL_OVERRIDE bulk per-phase model override ─────────
if [[ -n "${SPIRAL_PHASE_MODEL_OVERRIDE:-}" ]]; then
  IFS=',' read -ra _PMO <<<"$SPIRAL_PHASE_MODEL_OVERRIDE"
  for _e in "${_PMO[@]}"; do
    case "${_e%%:*}" in
      R) SPIRAL_RESEARCH_MODEL="${_e#*:}" ;;
      S) SPIRAL_VALIDATION_MODEL="${_e#*:}" ;;
      M) SPIRAL_MERGE_MODEL="${_e#*:}" ;;
    esac
  done
fi
export SPIRAL_RESEARCH_MODEL SPIRAL_VALIDATION_MODEL SPIRAL_MERGE_MODEL SPIRAL_MODEL_ROUTING
SPIRAL_FIRECRAWL_ENABLED="${SPIRAL_FIRECRAWL_ENABLED:-0}"
SPIRAL_SPECKIT_CONSTITUTION="${SPIRAL_SPECKIT_CONSTITUTION:-}"
SPIRAL_SPECKIT_SPECS_DIR="${SPIRAL_SPECKIT_SPECS_DIR:-}"
SPIRAL_FOCUS="${SPIRAL_CLI_FOCUS:-${SPIRAL_FOCUS:-}}"
SPIRAL_SKIP_STORY_IDS="${SPIRAL_SKIP_STORY_IDS:-}"              # comma-separated IDs to permanently skip without penalty
SPIRAL_SKIP_PHASES="${SPIRAL_SKIP_PHASES:-}"                    # comma-separated phase letters to skip (e.g. "R,T"); UI-managed via .spiral/ui-phase-config.json
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
SPIRAL_DEV_URL="${SPIRAL_DEV_URL:-}"                                                      # empty = disabled; URL for Phase V screenshot
SPIRAL_PROGRESS_MAX_LINES="${SPIRAL_PROGRESS_MAX_LINES:-2000}"                            # 0 = disabled; rotate progress.txt when over this limit
SPIRAL_EVENT_LOG_MAX_LINES="${SPIRAL_EVENT_LOG_MAX_LINES:-10000}"                         # 0 = disabled; rotate spiral_events.jsonl when over this limit
SPIRAL_LOG_MAX_MB="${SPIRAL_LOG_MAX_MB:-50}"                                              # 0 = disabled; rotate _last_run.log when size exceeds this value in MB
SPIRAL_LOG_KEEP_ROTATIONS="${SPIRAL_LOG_KEEP_ROTATIONS:-3}"                               # number of rotated _last_run.log files to keep (.log.1 ... .log.N)
SPIRAL_RESEARCH_CACHE_TTL_HOURS="${SPIRAL_RESEARCH_CACHE_TTL_HOURS:-0}"                   # 0 = disabled; cache TTL for Phase R URL responses AND Phase R output file reuse across iterations
SPIRAL_CACHE_SIM_THRESHOLD="${SPIRAL_CACHE_SIM_THRESHOLD:-0.92}"                          # US-403: cosine-similarity threshold for embedding-based cache lookup (1.0 = exact match only)
SPIRAL_RESEARCH_SUMMARY_THRESHOLD="${SPIRAL_RESEARCH_SUMMARY_THRESHOLD:-4000}"            # US-254: token threshold for hierarchical summarization of Phase R output (0 = disabled)
SPIRAL_USE_FULL_RESEARCH="${SPIRAL_USE_FULL_RESEARCH:-0}"                                 # US-254: 1 = pass full research to downstream phases (skip summarization)
SPIRAL_INJECTION_THRESHOLD="${SPIRAL_INJECTION_THRESHOLD:-0.8}"                           # US-198: LLM Guard PromptInjection scan threshold for Phase R web content (0.0–1.0)
RESEARCH_CACHE_DIR=""                                                                     # set after SCRATCH_DIR is known
SPIRAL_RESEARCH_TIMEOUT="${SPIRAL_RESEARCH_TIMEOUT:-300}"                                 # seconds; 0 = disabled (unlimited); Phase R LLM call
SPIRAL_RESEARCH_RETRIES="${SPIRAL_RESEARCH_RETRIES:-2}"                                   # retries when _research_output.json missing/invalid after Phase R
SPIRAL_GEMINI_FALLBACK_MODEL="${SPIRAL_GEMINI_FALLBACK_MODEL:-claude-haiku-4-5-20251001}" # Claude model for Gemini 503 fallback (US-206)
SPIRAL_IMPL_TIMEOUT="${SPIRAL_IMPL_TIMEOUT:-600}"                                         # seconds; 0 = disabled (unlimited); Phase I ralph call (fallback when complexity unknown)
SPIRAL_STORY_TIMEOUT_SMALL="${SPIRAL_STORY_TIMEOUT_SMALL:-600}"                           # seconds; per-story timeout for small complexity  (~10 min)
SPIRAL_STORY_TIMEOUT_MEDIUM="${SPIRAL_STORY_TIMEOUT_MEDIUM:-900}"                         # seconds; per-story timeout for medium complexity (~15 min)
SPIRAL_STORY_TIMEOUT_LARGE="${SPIRAL_STORY_TIMEOUT_LARGE:-1200}"                          # seconds; per-story timeout for large complexity  (~20 min)
SPIRAL_VALIDATE_TIMEOUT="${SPIRAL_VALIDATE_TIMEOUT:-300}"                                 # seconds; 0 = disabled (unlimited)
SPIRAL_INCREMENTAL_VALIDATE="${SPIRAL_INCREMENTAL_VALIDATE:-false}"                       # true = run only tests covering files touched by current story (Phase V)
SPIRAL_PARALLEL_TESTS="${SPIRAL_PARALLEL_TESTS:-false}"                                   # true = run Phase V tests in parallel (pytest-xdist or bats --jobs)
SPIRAL_TEST_WORKERS="${SPIRAL_TEST_WORKERS:-}"                                            # parallelism level; empty = nproc/2 (minimum 1)
SPIRAL_TEST_PREFIX="${SPIRAL_TEST_PREFIX:-tests/test_}"                                   # pytest: prefix for deriving test file from filesTouch entry basename
SPIRAL_TEST_SYNTH_TIMEOUT="${SPIRAL_TEST_SYNTH_TIMEOUT:-60}"                              # seconds; 0 = disabled (unlimited); Phase T synthesize_tests timeout
SPIRAL_TEST_OUTPUT_FORMAT="${SPIRAL_TEST_OUTPUT_FORMAT:-json}"                            # 'json' (default) or 'yaml'; YAML output is ~40% more token-efficient for Phase T (US-367)
SPIRAL_PREEMPTIVE_PRESSURE_MB="${SPIRAL_PREEMPTIVE_PRESSURE_MB:-0}"                       # MB; 0 = disabled; free RAM below this triggers preemptive pressure level 1
SPIRAL_NOTIFY_WEBHOOK="${SPIRAL_NOTIFY_WEBHOOK:-}"                                        # HTTPS URL; empty = disabled; POST JSON at each phase start/end
SPIRAL_NOTIFY_WEBHOOK_TIMEOUT="${SPIRAL_NOTIFY_WEBHOOK_TIMEOUT:-5}"                       # seconds; max wait per POST (default 5)
SPIRAL_NOTIFY_WEBHOOK_HEADERS="${SPIRAL_NOTIFY_WEBHOOK_HEADERS:-}"                        # optional HTTP header, e.g. "Authorization: Bearer TOKEN"
SPIRAL_NOTIFY_WEBHOOK_SECRET="${SPIRAL_NOTIFY_WEBHOOK_SECRET:-}"                          # HMAC-SHA256 signing key; adds X-Spiral-Signature-256 header when set (US-207)
SPIRAL_PRE_PHASE_HOOK="${SPIRAL_PRE_PHASE_HOOK:-}"                                        # path to executable; called before each phase; non-zero exit aborts story attempt
SPIRAL_POST_PHASE_HOOK="${SPIRAL_POST_PHASE_HOOK:-}"                                      # path to executable; called after each phase; non-zero exit is logged as warning (non-fatal)
SPIRAL_HOOK_TIMEOUT="${SPIRAL_HOOK_TIMEOUT:-30}"                                          # seconds; wall-clock limit per hook execution (default 30)
SPIRAL_MAX_FILES_PER_STORY="${SPIRAL_MAX_FILES_PER_STORY:-10}"                            # warn/abort when Phase I touches more files than this; 0 = disabled
SPIRAL_SCOPE_CREEP_ACTION="${SPIRAL_SCOPE_CREEP_ACTION:-warn}"                            # warn (default) = log only; abort = mark _failureReason and skip Phase V
SPIRAL_DRIFT_CHECK="${SPIRAL_DRIFT_CHECK:-false}"                                         # US-260: true = run post-Phase-I drift check against acceptance criteria
SPIRAL_DRIFT_PASS_THRESHOLD="${SPIRAL_DRIFT_PASS_THRESHOLD:-70}"                          # US-260: drift score >= this → pass (0-100, default 70)
SPIRAL_DRIFT_FAIL_THRESHOLD="${SPIRAL_DRIFT_FAIL_THRESHOLD:-40}"                          # US-260: drift score <  this → fail; 40-69 = warn (default 40)
export SPIRAL_DRIFT_PASS_THRESHOLD SPIRAL_DRIFT_FAIL_THRESHOLD
SPIRAL_FORCE_VALIDATE="${SPIRAL_FORCE_VALIDATE:-false}" # true = always run Phase V even when Phase I produced no new passes (CI bypass)
SPIRAL_CREATE_PRS="${SPIRAL_CREATE_PRS:-false}"         # true = push story commit to spiral/<ID> branch and open GitHub PR via gh CLI
SPIRAL_PR_BASE_BRANCH="${SPIRAL_PR_BASE_BRANCH:-main}"  # base branch for PRs created by SPIRAL_CREATE_PRS (default: main)
SPIRAL_PR_DRAFT="${SPIRAL_PR_DRAFT:-false}"             # true = create draft PRs (prevents auto-merge triggers)
export SPIRAL_CREATE_PRS SPIRAL_PR_BASE_BRANCH SPIRAL_PR_DRAFT
SPIRAL_AUTO_STASH="${SPIRAL_AUTO_STASH:-false}"                     # true = auto-stash dirty working tree before Phase I and pop after (US-177)
SPIRAL_CASCADE_FAN_OUT_LIMIT="${SPIRAL_CASCADE_FAN_OUT_LIMIT:-5}"   # US-322: max consecutive story failures before Phase I aborts; 0 = disabled
SPIRAL_CONSECUTIVE_FAIL_ABORT="${SPIRAL_CONSECUTIVE_FAIL_ABORT:-3}" # US-400: stop loop after N zero-progress iterations; 0 = disabled
SPIRAL_QUALITY_THRESHOLD="${SPIRAL_QUALITY_THRESHOLD:-3}"           # US-248: LLM-as-Judge score threshold (1-5); below this emits a warning (non-blocking)
SPIRAL_QUALITY_JUDGE_DISABLE="${SPIRAL_QUALITY_JUDGE_DISABLE:-0}"   # US-248: set to 1 to skip all LLM quality judge calls
export SPIRAL_QUALITY_THRESHOLD SPIRAL_QUALITY_JUDGE_DISABLE
SPIRAL_CREATE_TAGS="${SPIRAL_CREATE_TAGS:-false}"                                                        # true = create annotated git tag on successful run completion (US-137)
SPIRAL_AUTO_PUSH_TAGS="${SPIRAL_AUTO_PUSH_TAGS:-false}"                                                  # true = push run-complete tag to origin after creation (US-137)
SPIRAL_WORKSPACE_CLEANUP="${SPIRAL_WORKSPACE_CLEANUP:-false}"                                            # true = prune transient artifacts after 100% completion (US-136)
SPIRAL_CACHE_TTL="${SPIRAL_CACHE_TTL:-7}"                                                                # days; research_cache entries older than this are pruned (US-136)
SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE="${SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE:-true}" # US-302: clear research_cache when constitution.md SHA-256 changes
SPIRAL_AUTO_RELEASE="${SPIRAL_AUTO_RELEASE:-false}"                                                      # true = auto SemVer bump from conventional commits on run completion (US-190)
SPIRAL_PLAN_CACHE_ENABLED="${SPIRAL_PLAN_CACHE_ENABLED:-true}"                                           # US-353: true = cache/reuse decomposition plans across similar stories
SPIRAL_PLAN_CACHE_TTL_HOURS="${SPIRAL_PLAN_CACHE_TTL_HOURS:-168}"                                        # US-353: hours before cached plans expire (default 168 = 7 days)
SPIRAL_GIT_PUSH="${SPIRAL_GIT_PUSH:-false}"                                                              # true = push vX.Y.Z tag to origin after auto-release (US-190)
SPIRAL_GIT_AUTHOR="${SPIRAL_GIT_AUTHOR:-}"                                                               # fallback git identity "Name <email>" when git config user.name/email is missing (US-211)
SPIRAL_SAST_ENABLED="${SPIRAL_SAST_ENABLED:-true}"                                                       # US-262: run Semgrep SAST scan in Phase G; false = disabled
SPIRAL_SNAPSHOT_RETENTION="${SPIRAL_SNAPSHOT_RETENTION:-7}"                                              # US-362: prune invocation snapshots older than N iterations; 0 = keep all
SPIRAL_COMPRESS_ARTIFACTS="${SPIRAL_COMPRESS_ARTIFACTS:-false}"                                          # US-362: gzip-compress invocation snapshots after completion

# ── Propagate SPIRAL_SKIP_PHASES to phase-specific flags ──────────────────────
# SPIRAL_SKIP_PHASES is written by the Spiral UI phase toggles (.spiral/ui-phase-config.json).
# If it contains "R", force SKIP_RESEARCH=1 regardless of what spiral.config.sh says.
[[ "${SPIRAL_SKIP_PHASES:-}" == *"R"* ]] && SKIP_RESEARCH=1

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
  : "${SPIRAL_VALIDATION_MODEL:=haiku}"
  : "${SPIRAL_MERGE_MODEL:=haiku}"
  : "${SPIRAL_MAX_PENDING:=50}"
  : "${SPIRAL_MEMORY_LIMIT:=1024}"

  echo "[config] OK — SPIRAL_PYTHON=$SPIRAL_PYTHON SPIRAL_VALIDATE_CMD=$SPIRAL_VALIDATE_CMD"
}
validate_config

# ── US-264: Startup env var schema validation ─────────────────────────────────
# Reads env_schema.json, validates all SPIRAL env vars, prints colour-coded
# table, and exits with code 1 if any required var is missing or invalid.
validate_env() {
  local _schema="$SPIRAL_HOME/env_schema.json"
  if [[ ! -f "$_schema" ]]; then
    echo "[validate_env] WARNING: env_schema.json not found at $_schema — skipping validation" >&2
    return 0
  fi
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/tools/validate_env.py" --schema "$_schema"
  local _rc=$?
  if [[ "$_rc" -ne 0 ]]; then
    exit "$_rc"
  fi
}
validate_env

# ── US-354: Phase-specific model override parsing ────────────────────────────
# SPIRAL_PHASE_MODEL_OVERRIDE=R:haiku,S:haiku,M:sonnet  → per-phase overrides
if [[ -n "${SPIRAL_PHASE_MODEL_OVERRIDE:-}" ]]; then
  IFS=',' read -ra _PMO_ENTRIES <<<"$SPIRAL_PHASE_MODEL_OVERRIDE"
  for _pmo in "${_PMO_ENTRIES[@]}"; do
    _pmo_phase="${_pmo%%:*}"
    _pmo_model="${_pmo#*:}"
    case "$_pmo_phase" in
      R) SPIRAL_RESEARCH_MODEL="$_pmo_model" ;;
      S) SPIRAL_VALIDATION_MODEL="$_pmo_model" ;;
      M) SPIRAL_MERGE_MODEL="$_pmo_model" ;;
      *) echo "[config] WARNING: unknown phase '$_pmo_phase' in SPIRAL_PHASE_MODEL_OVERRIDE — ignored" ;;
    esac
  done
  echo "[config] Phase model overrides applied: $SPIRAL_PHASE_MODEL_OVERRIDE"
fi

# ── US-312: ANSI color output for phase section banners ──────────────────────
# SPIRAL_COLOR_OUTPUT: auto (default) | 1 (force on) | 0 (force off)
SPIRAL_COLOR_OUTPUT="${SPIRAL_COLOR_OUTPUT:-auto}"
_USE_COLOR=0
if [[ "$SPIRAL_COLOR_OUTPUT" == "1" ]]; then
  _USE_COLOR=1
elif [[ "$SPIRAL_COLOR_OUTPUT" == "auto" ]]; then
  # Enable when stdout is a TTY and TERM is not dumb
  [[ -t 1 && "${TERM:-}" != "dumb" ]] && _USE_COLOR=1
fi
if [[ "$_USE_COLOR" -eq 1 ]]; then
  _C_BLUE='\033[1;34m'
  _C_YELLOW='\033[1;33m'
  _C_GREEN='\033[1;32m'
  _C_RED='\033[1;31m'
  _C_CYAN='\033[1;36m'
  _C_RESET='\033[0m'
else
  _C_BLUE='' _C_YELLOW='' _C_GREEN='' _C_RED='' _C_CYAN='' _C_RESET=''
fi
# Helper: print a colored phase banner to stdout
# Usage: print_phase_banner "R" "RESEARCH"
print_phase_banner() {
  local phase="$1" label="$2"
  local color=""
  case "$phase" in
    R | T) color="$_C_BLUE" ;;
    I) color="$_C_YELLOW" ;;
    V) color="$_C_GREEN" ;;
    S | M | C | A | G) color="$_C_CYAN" ;;
    *) color="" ;;
  esac
  if [[ "$_USE_COLOR" -eq 1 ]]; then
    printf "\n  ${color}▓▓ Phase %s: %s ▓▓${_C_RESET}\n" "$phase" "$label"
  else
    echo ""
    echo "  [Phase $phase] $label"
  fi
}

# ── US-313: Print iteration summary banner after Phase C ────────────────────
# Usage: print_iter_summary_banner <iter> <done> <pending> <total> <iter_minutes> <iter_duration>
# Prints a bordered ASCII box with story stats, cost, and next action.
print_iter_summary_banner() {
  local iter="$1" done="$2" pending="$3" total="$4"
  local iter_minutes="${5:-0}" iter_duration="${6:-0}"
  local failed=0 actual_pending="$pending"
  # Count exhausted stories (retry count >= max retries)
  if [[ -f "$REPO_ROOT/retry-counts.json" ]]; then
    failed=$("$JQ" "[to_entries[] | select(.value >= ${SPIRAL_MAX_RETRIES:-3})] | length" \
      "$REPO_ROOT/retry-counts.json" 2>/dev/null || echo "0")
    actual_pending=$((pending > failed ? pending - failed : 0))
  fi
  # Extract cumulative cost from results.tsv
  local cost_str=""
  if [[ -f "$REPO_ROOT/results.tsv" ]]; then
    local _raw_cost
    _raw_cost=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/cost_check.py" \
      --results "$REPO_ROOT/results.tsv" 2>/dev/null | head -1) || true
    cost_str=$(echo "$_raw_cost" | sed -nE 's/.*(\$[0-9]+\.[0-9]+).*/\1/p') || true
  fi
  echo ""
  if [[ "$_USE_COLOR" -eq 1 ]]; then
    printf "  ${_C_CYAN}┌─── Iteration %d complete ─────────────────────────────${_C_RESET}\n" "$iter"
    printf "  ${_C_CYAN}│${_C_RESET}  Stories: ${_C_GREEN}✓ %d passed${_C_RESET}  ${_C_RED}✗ %d failed${_C_RESET}  ${_C_YELLOW}⏳ %d pending${_C_RESET}\n" \
      "$done" "$failed" "$actual_pending"
    [[ -n "$cost_str" ]] && printf "  ${_C_CYAN}│${_C_RESET}  Est. cost: %s\n" "$cost_str"
    printf "  ${_C_CYAN}│${_C_RESET}  Duration:  %dm (%ds)\n" "$iter_minutes" "$iter_duration"
    if [[ "$pending" -eq 0 ]]; then
      printf "  ${_C_CYAN}│${_C_RESET}  ${_C_GREEN}COMPLETE: All stories passed${_C_RESET}\n"
    else
      printf "  ${_C_CYAN}│${_C_RESET}  Next: %d stories remain → starting iteration %d\n" \
        "$pending" "$((iter + 1))"
    fi
    printf "  ${_C_CYAN}└───────────────────────────────────────────────────────${_C_RESET}\n"
  else
    echo "  ┌─── Iteration $iter complete ─────────────────────────────"
    echo "  │  Stories: ✓ $done passed  ✗ $failed failed  ⏳ $actual_pending pending"
    [[ -n "$cost_str" ]] && echo "  │  Est. cost: $cost_str"
    echo "  │  Duration:  ${iter_minutes}m (${iter_duration}s)"
    if [[ "$pending" -eq 0 ]]; then
      echo "  │  COMPLETE: All stories passed"
    else
      echo "  │  Next: $pending stories remain → starting iteration $((iter + 1))"
    fi
    echo "  └───────────────────────────────────────────────────────"
  fi
  echo ""
}

# ── Structured logging: SPIRAL_LOG_LEVEL filtering (US-130) ──────────────────
# Accepts DEBUG / INFO / WARN / ERROR (case-insensitive; normalised to upper on read).
# Requires bash 4.0+ for associative arrays (already required by spiral.sh).
declare -A LOG_LEVELS=([DEBUG]=0 [INFO]=1 [WARN]=2 [ERROR]=3)

# Normalise SPIRAL_LOG_LEVEL to upper-case and validate.
SPIRAL_LOG_LEVEL="${SPIRAL_LOG_LEVEL^^}"
if [[ -z "${LOG_LEVELS[$SPIRAL_LOG_LEVEL]+x}" ]]; then
  echo "[spiral] WARNING: Unknown SPIRAL_LOG_LEVEL='$SPIRAL_LOG_LEVEL', defaulting to INFO" >&2
  SPIRAL_LOG_LEVEL="INFO"
fi
export SPIRAL_LOG_LEVEL

# log_msg LEVEL MESSAGE...
# Emits the message to stderr only when LEVEL >= SPIRAL_LOG_LEVEL.
# DEBUG messages include caller context (file:line) for traceability.
log_msg() {
  local lvl="${1^^}"
  shift
  # Default to INFO if level is unrecognised
  local lvl_num="${LOG_LEVELS[$lvl]:-1}"
  local threshold="${LOG_LEVELS[$SPIRAL_LOG_LEVEL]:-1}"
  if [[ "$lvl_num" -ge "$threshold" ]]; then
    if [[ "$lvl" == "DEBUG" ]]; then
      local caller_ctx="${BASH_SOURCE[1]:-spiral.sh}:${BASH_LINENO[0]:-0}"
      echo "[DEBUG] ($caller_ctx) $*" >&2
    elif [[ "$lvl" == "ERROR" && "$_USE_COLOR" -eq 1 ]]; then
      printf "${_C_RED}[ERROR]${_C_RESET} %s\n" "$*" >&2
    else
      echo "[$lvl] $*" >&2
    fi
  fi
}

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

# ── Source structured error taxonomy (US-273) ─────────────────────────────────
source "$SPIRAL_HOME/lib/spiral_errors.sh"

# ── Prerequisite checks ───────────────────────────────────────────────────────
if [[ ! -f "$PRD_FILE" ]]; then
  spiral_exit E501 "$PRD_FILE"
fi
if [[ ! -f "$SPIRAL_RALPH" ]]; then
  spiral_exit E103 "ralph.sh not found at $SPIRAL_RALPH"
fi

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

# ── --calibration-report: print calibration report and exit ────────────────
if [[ "$CALIBRATION_REPORT_MODE" -eq 1 ]]; then
  _CALIB_FILE="calibration.jsonl"
  if [[ ! -f "$_CALIB_FILE" ]]; then
    echo "[spiral] ERROR: calibration.jsonl not found. Run SPIRAL first to generate calibration data." >&2
    exit 1
  fi
  echo "📊 CALIBRATION REPORT — Actual vs Estimated Complexity"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/calibration_tracker.py" report --calibration-file "$_CALIB_FILE"
  exit 0
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
  # Report orphaned spiral-worker worktrees (US-176)
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
  # Show last error from _last_error.json (US-273)
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
  # Show per-worker last errors if available
  _WORKER_ERR_DIR="$SCRATCH_DIR/workers"
  if [[ -d "$_WORKER_ERR_DIR" ]]; then
    _HAS_WORKER_ERRORS=0
    for _WE_DIR in "$_WORKER_ERR_DIR"/*/; do
      _WE_FILE="${_WE_DIR}_last_error.json"
      if [[ -f "$_WE_FILE" ]]; then
        _HAS_WORKER_ERRORS=1
        _WE_SID=$(basename "$_WE_DIR")
        _WE_CODE=$("$JQ" -r '.error_code // "?"' "$_WE_FILE" 2>/dev/null || echo "?")
        _WE_MSG=$("$JQ" -r '.message // "?"' "$_WE_FILE" 2>/dev/null || echo "?")
        echo "  [Worker ${_WE_SID}] Last Error: [SPIRAL-E-${_WE_CODE}] ${_WE_MSG}"
      fi
    done
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
source "$SPIRAL_HOME/lib/phases/phase_s_story_validate.sh"
source "$SPIRAL_HOME/lib/phases/phase_e_enrich.sh"
source "$SPIRAL_HOME/lib/phases/phase_t_test_synth.sh"
source "$SPIRAL_HOME/lib/phases/phase_0_clarify.sh"
source "$SPIRAL_HOME/lib/phases/phase_m_merge.sh"
source "$SPIRAL_HOME/lib/phases/phase_i_implement.sh"
source "$SPIRAL_HOME/lib/phases/phase_v_validate.sh"
source "$SPIRAL_HOME/lib/phases/phase_c_check_done.sh"
source "$SPIRAL_HOME/lib/phases/phase_r_research.sh"
source "$SPIRAL_HOME/lib/phases/phase_rt_parallel.sh"
source "$SPIRAL_HOME/lib/modes/mode_replay.sh"
source "$SPIRAL_HOME/lib/plugin_system.sh"
source "$SPIRAL_HOME/lib/crash_capture.sh"

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

source "$SPIRAL_HOME/lib/spiral_cleanup.sh"
# ── Signal trap state ─────────────────────────────────────────────────────────
WATCHDOG_PID=""
PHASE=""               # Current phase (R, T, M, G, I, V, C)
_ACTIVE_STORY_ID=""    # US-311: story currently being implemented (populated in Phase I)
_ACTIVE_STORY_TITLE="" # US-311: title of the active story
CHILD_PIDS=()          # Track explicitly spawned child processes




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
  # Resolve Windows PID: Git Bash $$ is MSYS2 PID, invisible to PowerShell
  _check_pid=$(cat /proc/$$/winpid 2>/dev/null || echo "$$")
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

  _SPIRAL_WIN_PID=$(cat /proc/$$/winpid 2>/dev/null || echo "$$")
  _WATCHDOG_ARGS="-ThresholdMB ${SPIRAL_MEMORY_THRESHOLD:-1536} -ParentPID $_SPIRAL_WIN_PID -IntervalSec ${SPIRAL_MEMORY_POLL_INTERVAL}"
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






# ── Helper: append a structured JSONL event to .spiral/spiral_events.jsonl ──
# Provided by lib/spiral_events.sh (sourced below). See that file for details.
source "$SPIRAL_HOME/lib/spiral_events.sh"
source "$SPIRAL_HOME/lib/spiral_helpers.sh"
source "$SPIRAL_HOME/lib/modes/mode_ops.sh"

# -- Startup initialization (sourced from lib/spiral_startup.sh) --
source "$SPIRAL_HOME/lib/spiral_startup.sh"

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
  # Clean stale endtime files from prior runs to prevent negative phase durations
  rm -f "$SCRATCH_DIR/_phase_R_${SPIRAL_ITER}.endtime" "$SCRATCH_DIR/_phase_T_${SPIRAL_ITER}.endtime" 2>/dev/null || true
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
  # US-182: R and T are independent — launch as background jobs and await both.
  run_phase_rt_parallel || continue

  run_phase_s || continue
  log_spiral_event "phase_end" "\"phase\":\"S\",\"iteration\":$SPIRAL_ITER,\"model\":\"$SPIRAL_VALIDATION_MODEL\""
  run_phase_enrichment

  run_phase_merge || continue
  log_spiral_event "phase_end" "\"phase\":\"M\",\"iteration\":$SPIRAL_ITER,\"model\":\"$SPIRAL_MERGE_MODEL\""

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
  if [[ "${SPIRAL_DASHBOARD_HTML:-false}" == "true" ]]; then
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/ui/spiral_dashboard.py" \
      --prd "$PRD_FILE" --results "$REPO_ROOT/results.tsv" \
      --retries "$REPO_ROOT/retry-counts.json" --progress "$REPO_ROOT/progress.txt" \
      --output "$SCRATCH_DIR/dashboard.html" --open 2>/dev/null || true
  fi
fi

SESSION_END=$(date +%s)
SESSION_MINUTES=$(((SESSION_END - SESSION_START) / 60))
echo "  Session: ${SESSION_MINUTES}m total, $SPIRAL_ITER iterations"

# ── Emit OTel root span on max-iters exit (US-184) ───────────────────────────
"$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-run \
  --passes "${DONE:-0}" --story-count "${TOTAL:-0}" 2>/dev/null || true

spiral_exit E404 "$MAX_SPIRAL_ITERS"

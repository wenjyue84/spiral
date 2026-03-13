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
#
# Crash recovery:
#   If SPIRAL is interrupted mid-iteration, re-running resumes from the
#   last completed phase of the interrupted iteration (via _checkpoint.json).

set -euo pipefail

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

# ── Argument parsing ─────────────────────────────────────────────────────────
MAX_SPIRAL_ITERS=20
GATE_DEFAULT=""        # empty = interactive; "proceed"|"skip"|"quit" = auto
RALPH_MAX_ITERS=120
SKIP_RESEARCH=0        # 1 = skip Phase R (Claude web research); T and M still run
RALPH_WORKERS=1        # >1 = parallel mode (git worktrees + docker lock)
WORKERS_EXPLICIT=0     # 1 = user passed --ralph-workers explicitly
CAPACITY_LIMIT=50      # Phase R is skipped when PENDING exceeds this threshold
MONITOR_TERMINALS=1    # 1 = open a terminal window per worker to tail logs
SPIRAL_CONFIG_PATH=""  # explicit --config path
SPIRAL_CLI_MODEL=""    # explicit --model override (haiku|sonnet|opus)
SPIRAL_CLI_FOCUS=""    # explicit --focus override
TIME_LIMIT_MINS=0      # 0 = no limit; >0 = stop after N minutes (--time-limit or --until)

while [[ $# -gt 0 ]]; do
  case $1 in
    --gate)
      GATE_DEFAULT="$2"; shift 2 ;;
    --ralph-iters)
      RALPH_MAX_ITERS="$2"; shift 2 ;;
    --skip-research)
      SKIP_RESEARCH=1; shift ;;
    --ralph-workers)
      RALPH_WORKERS="$2"; WORKERS_EXPLICIT=1; shift 2 ;;
    --capacity-limit)
      CAPACITY_LIMIT="$2"; shift 2 ;;
    --monitor)
      MONITOR_TERMINALS=1; shift ;;
    --no-monitor)
      MONITOR_TERMINALS=0; shift ;;
    --config)
      SPIRAL_CONFIG_PATH="$2"; shift 2 ;;
    --model)
      SPIRAL_CLI_MODEL="$2"; shift 2 ;;
    --focus)
      SPIRAL_CLI_FOCUS="$2"; shift 2 ;;
    --time-limit)
      TIME_LIMIT_MINS="$2"; shift 2 ;;
    --until)
      # Parse HH:MM and compute minutes remaining from now
      _TARGET="$2"; shift 2
      _NOW_H=$(date +%-H 2>/dev/null || date +%H | sed 's/^0//')
      _NOW_M=$(date +%-M 2>/dev/null || date +%M | sed 's/^0//')
      _NOW_H=${_NOW_H:-0}; _NOW_M=${_NOW_M:-0}
      _TARGET_H=$(echo "$_TARGET" | cut -d: -f1 | sed 's/^0*//' ); _TARGET_H=${_TARGET_H:-0}
      _TARGET_M=$(echo "$_TARGET" | cut -d: -f2 | sed 's/^0*//' ); _TARGET_M=${_TARGET_M:-0}
      _NOW_TOTAL=$(( _NOW_H * 60 + _NOW_M ))
      _TARGET_TOTAL=$(( _TARGET_H * 60 + _TARGET_M ))
      [[ "$_TARGET_TOTAL" -le "$_NOW_TOTAL" ]] && _TARGET_TOTAL=$(( _TARGET_TOTAL + 1440 ))
      TIME_LIMIT_MINS=$(( _TARGET_TOTAL - _NOW_TOTAL ))
      ;;
    --help|-h)
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
      echo "  --config PATH              Path to spiral.config.sh (default: \$REPO_ROOT/spiral.config.sh)"
      echo "  --time-limit N             Stop after N minutes (e.g., 60, 90, 120)"
      echo "  --until HH:MM              Stop at a wall-clock time (e.g., 14:30, 18:00)"
      echo ""
      echo "Config: Place spiral.config.sh in project root (or use --config)."
      echo "  See templates/spiral.config.example.sh for all variables."
      echo ""
      echo "Phases per iteration: R(esearch) → T(est synth) → M(erge) → G(ate) → I(mplement) → V(alidate) → C(heck done)"
      exit 0
      ;;
    --*)
      echo "[spiral] Unknown flag: $1"; exit 1 ;;
    *)
      MAX_SPIRAL_ITERS="$1"; shift ;;
  esac
done

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
STREAM_FMT="${SPIRAL_STREAM_FMT:-$SPIRAL_HOME/ralph/stream-formatter.mjs}"
SPIRAL_MODEL_ROUTING="${SPIRAL_MODEL_ROUTING:-auto}"
SPIRAL_RESEARCH_MODEL="${SPIRAL_RESEARCH_MODEL:-sonnet}"
SPIRAL_FIRECRAWL_ENABLED="${SPIRAL_FIRECRAWL_ENABLED:-0}"
SPIRAL_SPECKIT_CONSTITUTION="${SPIRAL_SPECKIT_CONSTITUTION:-}"
SPIRAL_SPECKIT_SPECS_DIR="${SPIRAL_SPECKIT_SPECS_DIR:-}"
SPIRAL_FOCUS="${SPIRAL_CLI_FOCUS:-${SPIRAL_FOCUS:-}}"
SPIRAL_MAX_PENDING="${SPIRAL_MAX_PENDING:-0}"  # 0 = unlimited
SPIRAL_STORY_BATCH_SIZE="${SPIRAL_STORY_BATCH_SIZE:-20}"  # 0 = disabled (show all)
SPIRAL_COST_CEILING="${SPIRAL_COST_CEILING:-}"  # empty = disabled; USD amount to cap spend
SPIRAL_LOW_POWER_MODE="${SPIRAL_LOW_POWER_MODE:-1}"
SPIRAL_PRESSURE_THRESHOLDS="${SPIRAL_PRESSURE_THRESHOLDS:-40,25,15,8}"
SPIRAL_MEMORY_POLL_INTERVAL="${SPIRAL_MEMORY_POLL_INTERVAL:-15}"
SPIRAL_PRESSURE_HYSTERESIS="${SPIRAL_PRESSURE_HYSTERESIS:-2}"

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
  [[ "$_errors" -eq 1 ]] && exit 1

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
  exit 1
fi

# ── Prerequisite checks ───────────────────────────────────────────────────────
if [[ ! -f "$PRD_FILE" ]]; then
  echo "[spiral] ERROR: prd.json not found at $PRD_FILE"
  exit 1
fi
if [[ ! -f "$SPIRAL_RALPH" ]]; then
  echo "[spiral] ERROR: ralph.sh not found at $SPIRAL_RALPH"
  exit 1
fi

# ── Tee all output to log file ──────────────────────────────────────────────
mkdir -p "$SCRATCH_DIR"
exec > >(tee "$SCRATCH_DIR/_last_run.log") 2>&1

# ── Source verification libraries ──────────────────────────────────────────
source "$SPIRAL_HOME/lib/validate_preflight.sh"
source "$SPIRAL_HOME/lib/spiral_assert.sh"

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
  SESSION_DEADLINE=$(( SESSION_START + TIME_LIMIT_MINS * 60 ))
fi

# ── Graceful cleanup trap — kill orphaned processes on exit/interrupt ───────
WATCHDOG_PID=""
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
  # Clean up docker lock dirs
  rm -rf /tmp/spiral-docker-lock-* 2>/dev/null || true
  # Clean up memory pressure signal files
  rm -f "$SCRATCH_DIR/_memory_pressure.json" "$SCRATCH_DIR/_low_power_active" 2>/dev/null || true
  rm -f "$SCRATCH_DIR"/_worker_pause_* 2>/dev/null || true
  echo "  [cleanup] Done."
}
trap cleanup EXIT INT TERM

# ── Memory watchdog — background monitor (graduated pressure or kill-only) ────
if [[ "${SPIRAL_MEMORY_WATCHDOG:-1}" -eq 1 ]] && command -v powershell.exe &>/dev/null; then
  _WATCHDOG_ARGS="-ThresholdMB ${SPIRAL_MEMORY_THRESHOLD:-1536} -ParentPID $$ -IntervalSec ${SPIRAL_MEMORY_POLL_INTERVAL}"
  if [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]]; then
    _WATCHDOG_ARGS="$_WATCHDOG_ARGS -ScratchDir $SCRATCH_DIR -ThresholdPct $SPIRAL_PRESSURE_THRESHOLDS -Hysteresis $SPIRAL_PRESSURE_HYSTERESIS"
    _WATCHDOG_MODE="graduated"
  else
    _WATCHDOG_MODE="kill-only"
  fi
  powershell.exe -ExecutionPolicy Bypass -File "$SPIRAL_HOME/lib/memory-watchdog.ps1" \
    $_WATCHDOG_ARGS &
  WATCHDOG_PID=$!
  echo "  [memory] Watchdog started (PID: $WATCHDOG_PID, mode: $_WATCHDOG_MODE, threshold: ${SPIRAL_MEMORY_THRESHOLD:-1536}MB)"
fi

# ── Backup prd.json before any modifications ────────────────────────────────
cp "$PRD_FILE" "${PRD_FILE}.bak"
echo "[spiral] Backup: ${PRD_FILE}.bak"

# ── Helper: stats from prd.json ─────────────────────────────────────────────
prd_stats() {
  TOTAL=$("$JQ" '[.userStories | length] | .[0]' "$PRD_FILE")
  DONE=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")
  PENDING=$((TOTAL - DONE))
}

# ── Helper: write checkpoint ────────────────────────────────────────────────
write_checkpoint() {
  local iter="$1" phase="$2"
  printf '{"iter":%d,"phase":"%s","ts":"%s"}\n' \
    "$iter" "$phase" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    > "$CHECKPOINT_FILE"
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
  printf '%s' "$prompt_content" | \
    awk -v existing="$existing_titles" -v pending="$pending_titles" -v focus="$focus_section" \
      '{gsub(/__EXISTING_TITLES__/, existing); gsub(/__PENDING_TITLES__/, pending); gsub(/__SPIRAL_FOCUS_SECTION__/, focus); print}'
}

# ── Pre-flight memory check — auto-adjust workers if RAM is low ────────────
if command -v powershell.exe &>/dev/null; then
  FREE_MB=$(powershell.exe -Command \
    "[math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)" 2>/dev/null | tr -d '\r')
  if [[ -n "$FREE_MB" && "$FREE_MB" =~ ^[0-9]+$ ]]; then
    # Each Claude instance needs ~2.5GB; plus 512MB overhead
    NEEDED_MB=$(( (RALPH_WORKERS + 1) * 2560 + 512 ))
    if [[ "$FREE_MB" -lt 3072 ]]; then
      echo "  [memory] WARNING: Only ${FREE_MB}MB free RAM — OOM risk is high"
      echo "  [memory] Consider closing applications or reducing --ralph-workers"
    fi
    if [[ "$RALPH_WORKERS" -gt 1 && "$FREE_MB" -lt "$NEEDED_MB" ]]; then
      # Auto-reduce workers to fit available memory
      MAX_SAFE_WORKERS=$(( (FREE_MB - 512) / 2560 ))
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
[[ "$MONITOR_TERMINALS" -eq 1 ]] && echo "  ║  Monitor:     terminal per worker (--monitor)"
[[ -n "$SPIRAL_SPECKIT_CONSTITUTION" && -f "$REPO_ROOT/$SPIRAL_SPECKIT_CONSTITUTION" ]] && \
  echo "  ║  Spec-Kit:    constitution loaded"
[[ -n "$SPIRAL_FOCUS" ]] && echo "  ║  Focus:       $SPIRAL_FOCUS"
[[ "$SPIRAL_MAX_PENDING" -gt 0 ]] && echo "  ║  Max pending: $SPIRAL_MAX_PENDING incomplete stories"
[[ "$SPIRAL_STORY_BATCH_SIZE" -gt 0 ]] && echo "  ║  Batch size:  $SPIRAL_STORY_BATCH_SIZE stories per iteration"
[[ -n "$SPIRAL_COST_CEILING" ]] && echo "  ║  Cost cap:    \$${SPIRAL_COST_CEILING} USD"
[[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && echo "  ║  Low power:   adaptive memory management enabled"
if [[ "$TIME_LIMIT_MINS" -gt 0 ]]; then
  _DEADLINE_DISPLAY=$(date -d "@$SESSION_DEADLINE" +"%H:%M" 2>/dev/null \
    || date -r "$SESSION_DEADLINE" +"%H:%M" 2>/dev/null \
    || echo "~${TIME_LIMIT_MINS}m from now")
  echo "  ║  Time limit:  ${TIME_LIMIT_MINS}m (stops ~${_DEADLINE_DISPLAY})"
fi
echo "  ║  Capacity:    Phase R skipped when pending > $CAPACITY_LIMIT"
echo "  ║  Scratch:     $SCRATCH_DIR"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

# ── Startup: initialize counters and resume from checkpoint if available ────
ZERO_PROGRESS_COUNT=0
SPIRAL_ITER=0

export SPIRAL_FOCUS
export SPIRAL_ITER

if [[ -f "$CHECKPOINT_FILE" ]]; then
  CKPT_ITER=$("$JQ" -r '.iter // 0' "$CHECKPOINT_FILE")
  CKPT_PHASE=$("$JQ" -r '.phase // ""' "$CHECKPOINT_FILE")
  echo "  [checkpoint] Resuming from iter=$CKPT_ITER phase=$CKPT_PHASE"
  SPIRAL_ITER=$((CKPT_ITER - 1))  # loop will increment to CKPT_ITER on first pass
  echo ""
fi

# ── Main SPIRAL loop ────────────────────────────────────────────────────────
while [[ $SPIRAL_ITER -lt $MAX_SPIRAL_ITERS ]]; do
  SPIRAL_ITER=$((SPIRAL_ITER + 1))
  ITER_START=$(date +%s)

  prd_stats
  ADDED=0           # new stories added this iter (set in Phase M; default 0 if skipped)
  RALPH_RAN=0       # set to 1 if ralph actually executed this iter (controls Phase V)
  RALPH_PROGRESS=0  # stories completed this iter; reset each iter for accurate velocity
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
      exit 2
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
  echo ""
  echo "  [Phase R] RESEARCH — searching sources..."
  RESEARCH_OUTPUT="$SCRATCH_DIR/_research_output.json"

  if checkpoint_phase_done "R"; then
    echo "  [R] Skipping (checkpoint: already done this iter)"
  elif [[ "$SKIP_RESEARCH" -eq 1 ]]; then
    echo "  [R] Skipping (--skip-research flag set)"
    echo '{"stories":[]}' > "$RESEARCH_OUTPUT"
    write_checkpoint "$SPIRAL_ITER" "R"
  elif [[ "$OVER_CAPACITY" -eq 1 ]]; then
    echo "  [R] Skipping (over-capacity: $PENDING pending > $CAPACITY_LIMIT)"
    echo '{"stories":[]}' > "$RESEARCH_OUTPUT"
    write_checkpoint "$SPIRAL_ITER" "R"
  elif [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && spiral_should_skip_phase "R"; then
    _P_LVL=$(spiral_pressure_level)
    echo "  [R] Skipping (memory pressure: level $_P_LVL)"
    spiral_log_low_power "Phase R skipped (pressure level $_P_LVL, iter $SPIRAL_ITER)"
    echo '{"stories":[]}' > "$RESEARCH_OUTPUT"
    write_checkpoint "$SPIRAL_ITER" "R"
  else
    # ── Gemini web research (optional, configured via SPIRAL_GEMINI_PROMPT) ──
    GEMINI_RESEARCH=""
    if command -v gemini &>/dev/null && [[ -n "$SPIRAL_GEMINI_PROMPT" ]]; then
      echo "  [R] Running Gemini 2.5 Pro web research (-y web search enabled)..."
      GEMINI_RESEARCH=$(gemini \
        -m gemini-2.5-pro \
        -p "$SPIRAL_GEMINI_PROMPT" \
        -y --output-format text 2>/dev/null || true)
      if [[ -n "$GEMINI_RESEARCH" ]]; then
        echo "  [R] Gemini web research complete ($(echo "$GEMINI_RESEARCH" | wc -l) lines)"
      else
        echo "  [R] Gemini web research returned empty — Claude will browse URLs directly"
      fi
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

    echo "  [R] Spawning Claude research agent (max 30 turns, model: $RESEARCH_MODEL)..."
    echo "  ─────── Research Agent Start ─────────────────────────"

    if command -v node &>/dev/null && [[ -f "$STREAM_FMT" ]]; then
      (unset CLAUDECODE; claude -p "$INJECTED_PROMPT" \
        --model "$RESEARCH_MODEL" \
        --allowedTools "$RESEARCH_TOOLS" \
        --max-turns 30 \
        --verbose \
        --output-format stream-json \
        --dangerously-skip-permissions \
        </dev/null 2>&1 | node "$STREAM_FMT") || true
    else
      (unset CLAUDECODE; claude -p "$INJECTED_PROMPT" \
        --model "$RESEARCH_MODEL" \
        --allowedTools "$RESEARCH_TOOLS" \
        --max-turns 30 \
        --dangerously-skip-permissions \
        </dev/null 2>&1) || true
    fi

    echo "  ─────── Research Agent End ───────────────────────────"

    if [[ ! -f "$RESEARCH_OUTPUT" ]]; then
      echo "  [R] WARNING: Research agent did not write $RESEARCH_OUTPUT — using empty"
      echo '{"stories":[]}' > "$RESEARCH_OUTPUT"
    else
      RESEARCH_COUNT=$("$JQ" '.stories | length' "$RESEARCH_OUTPUT" 2>/dev/null || echo "?")
      echo "  [R] Research complete — $RESEARCH_COUNT story candidates found"
    fi

    write_checkpoint "$SPIRAL_ITER" "R"
  fi

  # ── Phase T: TEST SYNTHESIS ─────────────────────────────────────────────────
  echo ""
  echo "  [Phase T] TEST SYNTHESIS — scanning test failures..."
  TEST_OUTPUT="$SCRATCH_DIR/_test_stories_output.json"

  if checkpoint_phase_done "T"; then
    echo "  [T] Skipping (checkpoint: already done this iter)"
  elif [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && spiral_should_skip_phase "T"; then
    _P_LVL=$(spiral_pressure_level)
    echo "  [T] Skipping (memory pressure: level $_P_LVL)"
    spiral_log_low_power "Phase T skipped (pressure level $_P_LVL, iter $SPIRAL_ITER)"
    echo '{"stories":[]}' > "$TEST_OUTPUT"
    write_checkpoint "$SPIRAL_ITER" "T"
  else
    if [[ -n "$SPIRAL_CORE_BIN" ]]; then
      "$SPIRAL_CORE_BIN" synthesize \
        --prd "$PRD_FILE" \
        --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
        --output "$TEST_OUTPUT" \
        --repo-root "$REPO_ROOT" \
        ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || true
    else
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/synthesize_tests.py" \
        --prd "$PRD_FILE" \
        --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
        --output "$TEST_OUTPUT" \
        --repo-root "$REPO_ROOT" \
        ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || true
    fi

    TEST_COUNT=$("$JQ" '.stories | length' "$TEST_OUTPUT" 2>/dev/null || echo "0")
    echo "  [T] Test synthesis complete — $TEST_COUNT story candidates from failures"

    write_checkpoint "$SPIRAL_ITER" "T"
  fi

  # ── Phase M: MERGE ──────────────────────────────────────────────────────────
  echo ""
  echo "  [Phase M] MERGE — deduplicating and patching prd.json..."

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

    OVERFLOW_FILE="$SCRATCH_DIR/_research_overflow.json"
    BEFORE_TOTAL=$("$JQ" '[.userStories | length] | .[0]' "$PRD_FILE")
    if [[ -n "$SPIRAL_CORE_BIN" ]]; then
      "$SPIRAL_CORE_BIN" merge \
        --prd "$PRD_FILE" \
        --research "$RESEARCH_OUTPUT" \
        --test-stories "$TEST_OUTPUT" \
        --overflow-in  "$OVERFLOW_FILE" \
        --overflow-out "$OVERFLOW_FILE" \
        --max-new 50 \
        --max-pending "$SPIRAL_MAX_PENDING" \
        ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || true
    else
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/merge_stories.py" \
        --prd "$PRD_FILE" \
        --research "$RESEARCH_OUTPUT" \
        --test-stories "$TEST_OUTPUT" \
        --overflow-in  "$OVERFLOW_FILE" \
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
  fi

  # ── Phase G: HUMAN GATE + Phase I: IMPLEMENT ───────────────────────────────
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

    echo ""
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║  [Phase G] HUMAN GATE — Iteration $SPIRAL_ITER"
    echo "  ╠══════════════════════════════════════════════════════╣"
    echo "  ║  New stories added:  $ADDED"
    echo "  ║  Total pending:      $PENDING"
    echo "  ║  Total stories:      $TOTAL ($DONE complete)"
    [[ -n "$SPIRAL_FOCUS" ]] && \
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
      quit|q|exit)
        echo "  [G] User quit — SPIRAL halted at iteration $SPIRAL_ITER"
        rm -f "$CHECKPOINT_FILE"
        exit 0
        ;;
      skip|s)
        echo "  [G] Skipping ralph — advancing to check-done"
        ;;
      proceed|p|"")
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
        "$JQ" -r '.userStories[] | select(.passes != true) | "    [\(.id)] \(.title)"' "$PRD_FILE" \
          2>/dev/null | head -20 || true
        PENDING_SHOWN=$("$JQ" '[.userStories[] | select(.passes != true)] | length' "$PRD_FILE" 2>/dev/null || echo "$PENDING")
        [[ "$PENDING_SHOWN" -gt 20 ]] && echo "    ... and $((PENDING_SHOWN - 20)) more"
        echo ""

        # Note: model is now assigned per-story by lib/route_stories.py

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
              echo "  [I] Wave $((WAVE+1)): 0 stories — skipping"
              WAVE=$((WAVE + 1))
              continue
            fi

            echo "  [I] ── Wave $((WAVE+1)): $WAVE_STORY_COUNT stories ──"

            if [[ "$WAVE_STORY_COUNT" -eq 1 ]]; then
              # Single story — sequential fallback, skip worktree overhead entirely
              echo "  [I] Wave $((WAVE+1)): 1 story — sequential fallback (no worktrees)"
              # Auto-detect tool: UT-* test stories → Codex; others → Claude
              _NEXT_SID=$("$JQ" -r '[.userStories[] | select(.passes != true)] | sort_by(.priority) | first | .id // ""' "$PRD_FILE" 2>/dev/null || echo "")
              if [[ "$_NEXT_SID" == UT-* ]]; then
                _RALPH_TOOL="codex"
                echo "  [I] Story $_NEXT_SID is a test story → routing to Codex"
              else
                _RALPH_TOOL="claude"
              fi
              RALPH_TIMEOUT=3600
              if command -v timeout &>/dev/null; then
                timeout "$RALPH_TIMEOUT" bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" || {
                  RC=$?
                  [[ "$RC" -eq 124 ]] && echo "  [I] WARNING: Ralph timed out after ${RALPH_TIMEOUT}s"
                }
              else
                bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" || true
              fi
            else
              # Cap workers to story count so no worker sits idle
              WAVE_WORKERS="$RALPH_WORKERS"
              if [[ "$WAVE_STORY_COUNT" -lt "$RALPH_WORKERS" ]]; then
                WAVE_WORKERS="$WAVE_STORY_COUNT"
                echo "  [I] Wave $((WAVE+1)): capping to $WAVE_WORKERS workers (only $WAVE_STORY_COUNT stories)"
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
          RALPH_TIMEOUT=3600  # 1 hour
          if command -v timeout &>/dev/null; then
            timeout "$RALPH_TIMEOUT" bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" || {
              RC=$?
              if [[ "$RC" -eq 124 ]]; then
                echo "  [I] WARNING: Ralph timed out after ${RALPH_TIMEOUT}s — partial progress saved"
              fi
            }
          else
            bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" $RALPH_MODEL_FLAG || true
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
              if git -C "$REPO_ROOT" add -A 2>/dev/null && \
                 git -C "$REPO_ROOT" commit -m "feat(spiral): complete $RALPH_PROGRESS stories (iter $SPIRAL_ITER)" 2>/dev/null; then
                echo "  [I] Git: committed $RALPH_PROGRESS stories (fallback single commit)"
              else
                echo "  [I] Git: commit skipped (nothing staged or git unavailable)"
              fi
            else
              # Restore prd.json to pre-ralph state; code changes remain as unstaged diffs
              echo "$PRE_RALPH_PRD_JSON" > "$PRD_FILE"

              # Stage all code changes except prd.json (goes into first story's commit)
              git -C "$REPO_ROOT" add -A 2>/dev/null || true
              git -C "$REPO_ROOT" restore --staged "$PRD_FILE" 2>/dev/null || \
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
                [[ -n "$UPDATED" ]] && echo "$UPDATED" > "$PRD_FILE"

                git -C "$REPO_ROOT" add "$PRD_FILE" 2>/dev/null || true
                if git -C "$REPO_ROOT" commit -m "feat: $STORY_ID - $STORY_TITLE" 2>/dev/null; then
                  echo "  [I] Git: feat: $STORY_ID - $STORY_TITLE"
                  ATOMIC_COUNT=$((ATOMIC_COUNT + 1))
                fi
              done

              # Ensure prd.json is fully synced to post-ralph final state
              cp "$POST_RALPH_PRD" "$PRD_FILE"
              git -C "$REPO_ROOT" add "$PRD_FILE" 2>/dev/null || true
              git -C "$REPO_ROOT" diff --cached --quiet 2>/dev/null || \
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
            exit 2
          fi
          echo "  [I] Continuing to check-done phase..."
        fi
        # ── Adaptive ralph budget based on velocity ─────────────────────────────
        if [[ "$RALPH_PROGRESS" -ge 5 ]]; then
          RALPH_MAX_ITERS=$(( RALPH_MAX_ITERS + 20 ))
          echo "  [velocity] High ($RALPH_PROGRESS stories/iter) — ralph budget → $RALPH_MAX_ITERS"
        elif [[ "$RALPH_PROGRESS" -eq 0 ]]; then
          NEW_BUDGET=$(( RALPH_MAX_ITERS / 2 ))
          [[ "$NEW_BUDGET" -lt 30 ]] && NEW_BUDGET=30
          RALPH_MAX_ITERS="$NEW_BUDGET"
          echo "  [velocity] Zero — ralph budget → $RALPH_MAX_ITERS"
        fi
        fi  # end PENDING > 0 block
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

  # ── Phase V: VALIDATE (test suite) ────────────────────────────────────────
  echo ""
  echo "  [Phase V] VALIDATE — running test suite..."

  if checkpoint_phase_done "V"; then
    echo "  [V] Skipping (checkpoint: already done this iter)"
  elif [[ "$RALPH_RAN" -eq 0 ]]; then
    echo "  [V] Skipping (ralph did not run — test results unchanged)"
    write_checkpoint "$SPIRAL_ITER" "V"
  else
    # Run the project's validation command
    (cd "$REPO_ROOT" && eval "$SPIRAL_VALIDATE_CMD" 2>&1) || true

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

    write_checkpoint "$SPIRAL_ITER" "V"
  fi

  # ── Phase P: PUSH ──────────────────────────────────────────────────────────
  echo ""
  echo "  [Phase P] PUSH — pushing commits to origin/main..."
  if git -C "$REPO_ROOT" push origin main 2>&1; then
    echo "  [P] Pushed to origin/main successfully"
  else
    echo "  [P] WARNING: Push to origin/main failed (check remote/connectivity)"
  fi

  # ── Phase C: CHECK DONE ─────────────────────────────────────────────────────
  echo ""
  echo "  [Phase C] CHECK DONE..."

  _CHECK_DONE_RC=0
  if [[ -n "$SPIRAL_CORE_BIN" ]]; then
    "$SPIRAL_CORE_BIN" check-done \
      --prd "$PRD_FILE" \
      --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" || _CHECK_DONE_RC=$?
  else
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/check_done.py" \
      --prd "$PRD_FILE" \
      --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" || _CHECK_DONE_RC=$?
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
    SESSION_MINUTES=$(( (SESSION_END - SESSION_START) / 60 ))
    echo "  Session: ${SESSION_MINUTES}m total, $SPIRAL_ITER iterations"

    exit 0
  fi

  # Clear checkpoint before next iteration (crash in next iter starts that iter fresh)
  rm -f "$CHECKPOINT_FILE"
  prd_stats
  echo "  [C] Not done yet — $PENDING stories remaining"
  if [[ "${RALPH_PROGRESS:-0}" -gt 0 ]]; then
    ITERS_LEFT=$(( (PENDING + RALPH_PROGRESS - 1) / RALPH_PROGRESS ))
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

  # ── Iteration dashboard ─────────────────────────────────────────────────
  ITER_END=$(date +%s)
  ITER_DURATION=$(( ITER_END - ITER_START ))
  ITER_MINUTES=$(( ITER_DURATION / 60 ))
  echo ""
  echo "  ┌─ Iteration $SPIRAL_ITER Summary ─────────────────┐"
  echo "  │  Stories:   +${RALPH_PROGRESS:-0} completed, $PENDING remaining"
  echo "  │  Duration:  ${ITER_MINUTES}m (${ITER_DURATION}s)"
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
      _COOLDOWN=$(( _PRESSURE_LVL * 15 ))
      echo "  [memory] Pressure cooldown: ${_COOLDOWN}s (level $_PRESSURE_LVL)"
      spiral_log_low_power "Inter-iteration cooldown: ${_COOLDOWN}s (level $_PRESSURE_LVL, iter $SPIRAL_ITER)"
      sleep "$_COOLDOWN"
    fi
  fi

  # ── Time limit check — stop cleanly after completing this iteration ────────
  if [[ "$SESSION_DEADLINE" -gt 0 ]]; then
    _NOW_TS=$(date +%s)
    _REMAINING_SECS=$(( SESSION_DEADLINE - _NOW_TS ))
    if [[ "$_REMAINING_SECS" -le 0 ]]; then
      echo "  [time] Time limit of ${TIME_LIMIT_MINS}m reached — stopping after iteration $SPIRAL_ITER"
      echo ""
      prd_stats
      SESSION_END=$(date +%s)
      SESSION_MINUTES=$(( (SESSION_END - SESSION_START) / 60 ))
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
      _REM_MINS=$(( (_REMAINING_SECS + 59) / 60 ))
      echo "  [time] ~${_REM_MINS}m remaining"
    fi
  fi

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
SESSION_MINUTES=$(( (SESSION_END - SESSION_START) / 60 ))
echo "  Session: ${SESSION_MINUTES}m total, $SPIRAL_ITER iterations"

exit 0

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

# ── Resolve SPIRAL_HOME (where this script + lib/ live) ─────────────────────
SPIRAL_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Argument parsing ─────────────────────────────────────────────────────────
MAX_SPIRAL_ITERS=20
GATE_DEFAULT=""        # empty = interactive; "proceed"|"skip"|"quit" = auto
RALPH_MAX_ITERS=120
SKIP_RESEARCH=0        # 1 = skip Phase R (Claude web research); T and M still run
RALPH_WORKERS=1        # >1 = parallel mode (git worktrees + docker lock)
CAPACITY_LIMIT=50      # Phase R is skipped when PENDING exceeds this threshold
MONITOR_TERMINALS=1    # 1 = open a terminal window per worker to tail logs
SPIRAL_CONFIG_PATH=""  # explicit --config path

while [[ $# -gt 0 ]]; do
  case $1 in
    --gate)
      GATE_DEFAULT="$2"; shift 2 ;;
    --ralph-iters)
      RALPH_MAX_ITERS="$2"; shift 2 ;;
    --skip-research)
      SKIP_RESEARCH=1; shift ;;
    --ralph-workers)
      RALPH_WORKERS="$2"; shift 2 ;;
    --capacity-limit)
      CAPACITY_LIMIT="$2"; shift 2 ;;
    --monitor)
      MONITOR_TERMINALS=1; shift ;;
    --no-monitor)
      MONITOR_TERMINALS=0; shift ;;
    --config)
      SPIRAL_CONFIG_PATH="$2"; shift 2 ;;
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
      echo "  --config PATH              Path to spiral.config.sh (default: \$REPO_ROOT/spiral.config.sh)"
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
if [[ -f "$_SPIRAL_CONFIG" ]]; then
  echo "[spiral] Loading config: $_SPIRAL_CONFIG"
  source "$_SPIRAL_CONFIG"
else
  echo "[spiral] No config found at $_SPIRAL_CONFIG — using defaults"
fi

# Apply config with defaults
SPIRAL_PYTHON="${SPIRAL_PYTHON:-python3}"
SPIRAL_RALPH="${SPIRAL_RALPH:-$HOME/.ai/Skills/ralph/ralph.sh}"
SPIRAL_RESEARCH_PROMPT="${SPIRAL_RESEARCH_PROMPT:-$SPIRAL_HOME/templates/research_prompt.example.md}"
SPIRAL_GEMINI_PROMPT="${SPIRAL_GEMINI_PROMPT:-}"
SPIRAL_VALIDATE_CMD="${SPIRAL_VALIDATE_CMD:-$SPIRAL_PYTHON tests/run_tests.py --report-dir test-reports}"
SPIRAL_REPORTS_DIR="${SPIRAL_REPORTS_DIR:-test-reports}"
SPIRAL_STORY_PREFIX="${SPIRAL_STORY_PREFIX:-US}"
STREAM_FMT="${SPIRAL_STREAM_FMT:-$HOME/.ai/Skills/ralph/stream-formatter.mjs}"

# Scratch directory in project root
SCRATCH_DIR="$REPO_ROOT/.spiral"
PRD_FILE="$REPO_ROOT/prd.json"
CHECKPOINT_FILE="$SCRATCH_DIR/_checkpoint.json"

# ── jq resolution (reuse ralph.sh pattern) ───────────────────────────────────
RALPH_JQ_DIR="$HOME/.ai/Skills/ralph"
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
  # Replace __EXISTING_TITLES__ and __PENDING_TITLES__ placeholders
  printf '%s' "$prompt_content" | \
    awk -v existing="$existing_titles" -v pending="$pending_titles" \
      '{gsub(/__EXISTING_TITLES__/, existing); gsub(/__PENDING_TITLES__/, pending); print}'
}

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
[[ "$RALPH_WORKERS" -gt 1 ]] && echo "  ║  Workers:     $RALPH_WORKERS parallel (git worktrees)"
[[ "$SKIP_RESEARCH" -eq 1 ]] && echo "  ║  Mode:        --skip-research (Phase R skipped)"
[[ "$MONITOR_TERMINALS" -eq 1 ]] && echo "  ║  Monitor:     terminal per worker (--monitor)"
echo "  ║  Capacity:    Phase R skipped when pending > $CAPACITY_LIMIT"
echo "  ║  Scratch:     $SCRATCH_DIR"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

# ── Startup: initialize counters and resume from checkpoint if available ────
ZERO_PROGRESS_COUNT=0
SPIRAL_ITER=0

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

  prd_stats
  ADDED=0           # new stories added this iter (set in Phase M; default 0 if skipped)
  RALPH_RAN=0       # set to 1 if ralph actually executed this iter (controls Phase V)
  RALPH_PROGRESS=0  # stories completed this iter; reset each iter for accurate velocity
  echo ""
  echo "  ┌─────────────────────────────────────────────────────┐"
  echo "  │  SPIRAL Iteration $SPIRAL_ITER / $MAX_SPIRAL_ITERS"
  echo "  │  Stories: $DONE/$TOTAL complete ($PENDING pending)"
  echo "  └─────────────────────────────────────────────────────┘"

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

    echo "  [R] Spawning Claude research agent (max 30 turns)..."
    echo "  ─────── Research Agent Start ─────────────────────────"

    if command -v node &>/dev/null && [[ -f "$STREAM_FMT" ]]; then
      (unset CLAUDECODE; claude -p "$INJECTED_PROMPT" \
        --allowedTools "WebSearch,WebFetch,Write,Read" \
        --max-turns 30 \
        --verbose \
        --output-format stream-json \
        --dangerously-skip-permissions \
        </dev/null 2>&1 | node "$STREAM_FMT") || true
    else
      (unset CLAUDECODE; claude -p "$INJECTED_PROMPT" \
        --allowedTools "WebSearch,WebFetch,Write,Read" \
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
  else
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/synthesize_tests.py" \
      --prd "$PRD_FILE" \
      --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
      --output "$TEST_OUTPUT" \
      --repo-root "$REPO_ROOT" || true

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
    OVERFLOW_FILE="$SCRATCH_DIR/_research_overflow.json"
    BEFORE_TOTAL=$("$JQ" '[.userStories | length] | .[0]' "$PRD_FILE")
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/merge_stories.py" \
      --prd "$PRD_FILE" \
      --research "$RESEARCH_OUTPUT" \
      --test-stories "$TEST_OUTPUT" \
      --overflow-in  "$OVERFLOW_FILE" \
      --overflow-out "$OVERFLOW_FILE" \
      --max-new 50 || true
    AFTER_TOTAL=$("$JQ" '[.userStories | length] | .[0]' "$PRD_FILE")
    ADDED=$((AFTER_TOTAL - BEFORE_TOTAL))
    echo "  [M] Merge complete — $ADDED new stories added (total: $AFTER_TOTAL)"

    write_checkpoint "$SPIRAL_ITER" "M"
  fi

  # ── Phase G: HUMAN GATE + Phase I: IMPLEMENT ───────────────────────────────
  if checkpoint_phase_done "I"; then
    echo "  [G+I] Skipping (checkpoint: gate and ralph already done this iter)"
  else
    prd_stats
    echo ""
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║  [Phase G] HUMAN GATE — Iteration $SPIRAL_ITER"
    echo "  ╠══════════════════════════════════════════════════════╣"
    echo "  ║  New stories added:  $ADDED"
    echo "  ║  Total pending:      $PENDING"
    echo "  ║  Total stories:      $TOTAL ($DONE complete)"
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
        # ── Phase I: IMPLEMENT (Ralph) ──────────────────────────────────
        echo ""

        # Short-circuit if nothing to implement
        prd_stats
        if [[ "$PENDING" -eq 0 ]]; then
          echo "  [Phase I] IMPLEMENT — skipping (no pending stories)"
        else
        echo "  [Phase I] IMPLEMENT — running ralph ($RALPH_MAX_ITERS inner iterations)..."
        echo "  [I] Pending stories ($PENDING):"
        "$JQ" -r '.userStories[] | select(.passes != true) | "    [\(.id)] \(.title)"' "$PRD_FILE" \
          2>/dev/null | head -20 || true
        PENDING_SHOWN=$("$JQ" '[.userStories[] | select(.passes != true)] | length' "$PRD_FILE" 2>/dev/null || echo "$PENDING")
        [[ "$PENDING_SHOWN" -gt 20 ]] && echo "    ... and $((PENDING_SHOWN - 20)) more"
        echo ""

        RALPH_RAN=1
        PRE_RALPH_PRD_JSON=$(cat "$PRD_FILE")
        DONE_BEFORE=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")

        if [[ "$RALPH_WORKERS" -gt 1 ]]; then
          # ── Parallel mode with wave dispatch ───────────────────────────────
          # Pre-populate filesTouch hints from git history (best-effort)
          "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/populate_hints.py" \
            --prd "$PRD_FILE" --repo-root "$REPO_ROOT" 2>/dev/null || true

          TOTAL_WAVES=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/partition_prd.py" \
            --prd "$PRD_FILE" --list-waves 2>/dev/null || echo "1")
          echo "  [I] Parallel mode: $RALPH_WORKERS workers, $TOTAL_WAVES wave(s)"

          WAVE=0
          while true; do
            # Get story count for this wave level (recomputed from current prd.json)
            WAVE_STORY_COUNT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/partition_prd.py" \
              --prd "$PRD_FILE" --wave-count "$WAVE" 2>/dev/null || echo "0")

            # No stories at this level — check if higher levels exist
            if [[ "$WAVE_STORY_COUNT" -eq 0 ]]; then
              REMAINING=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/partition_prd.py" \
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
                "$MONITOR_TERMINALS" "$SPIRAL_HOME" || true
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
            bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" || true
          fi
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

  if "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/check_done.py" \
    --prd "$PRD_FILE" \
    --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR"; then
    rm -f "$CHECKPOINT_FILE"
    echo ""
    echo "  ╔══════════════════════════════════════════════════════╗"
    echo "  ║   *** SPIRAL COMPLETE! ***                           ║"
    echo "  ║   All stories implemented and tests passing.         ║"
    echo "  ║   Iterations: $SPIRAL_ITER / $MAX_SPIRAL_ITERS"
    echo "  ╚══════════════════════════════════════════════════════╝"
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
exit 0

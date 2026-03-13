#!/bin/bash
# run_parallel_ralph.sh — Orchestrate N parallel Ralph workers via git worktrees
#
# Each worker:
#   - Runs in its own git worktree (isolated source files + git history)
#   - Uses its own prd.json slice (subset of pending stories)
#   - Routes docker cp/bench calls through a mkdir lock wrapper (shared container safety)
#
# After all workers finish:
#   - prd.json pass results are merged back into main
#   - Code diffs are applied via git patch
#   - Optional deploy command runs
#   - Worktrees and branches are cleaned up
#
# Usage: bash run_parallel_ralph.sh WORKERS MAX_ITERS REPO_ROOT PRD_FILE SCRATCH_DIR RALPH_SKILL JQ PYTHON MONITOR SPIRAL_HOME [RALPH_MODEL]
#
# Environment variables (from spiral.config.sh):
#   SPIRAL_PATCH_DIRS           — space-separated dirs for git diff patches (default: all)
#   SPIRAL_DEPLOY_CMD           — post-merge deploy command (default: skip)
#   SPIRAL_TERMINAL             — terminal emulator path (default: auto-detect)
#   SPIRAL_GEMINI_ANNOTATE_PROMPT — gemini prompt for filesTouch annotation (default: skip)

set -euo pipefail

RALPH_WORKERS="$1"
RALPH_MAX_ITERS="$2"
REPO_ROOT="$3"
PRD_FILE="$4"
SCRATCH_DIR="$5"
RALPH_SKILL="$6"
JQ="$7"
PYTHON="$8"
MONITOR_TERMINALS="${9:-0}"
SPIRAL_HOME="${10:-}"
RALPH_MODEL="${11:-}"

# ── Source memory pressure helper (if available) ──────────────────────────────
SPIRAL_SCRATCH_DIR="${SPIRAL_SCRATCH_DIR:-$SCRATCH_DIR}"
export SPIRAL_SCRATCH_DIR
_PRESSURE_HELPER="$SPIRAL_HOME/lib/memory-pressure-check.sh"
if [[ -f "$_PRESSURE_HELPER" ]]; then
  source "$_PRESSURE_HELPER"
fi

WORKER_DIR="$SCRATCH_DIR/workers"
WORKTREE_BASE="$REPO_ROOT/.spiral-workers"
# Unique lock dir per invocation (using PID avoids collisions if SPIRAL is re-run)
LOCK_DIR="/tmp/spiral-docker-lock-$$"
TIMESTAMP=$(date +%s)
ITER_PER_WORKER=$(( (RALPH_MAX_ITERS + RALPH_WORKERS - 1) / RALPH_WORKERS ))

# Read config from environment (set by spiral.config.sh → sourced by spiral.sh)
PATCH_DIRS="${SPIRAL_PATCH_DIRS:-}"
DEPLOY_CMD="${SPIRAL_DEPLOY_CMD:-}"
TERMINAL_EMU="${SPIRAL_TERMINAL:-}"
GEMINI_ANNOTATE="${SPIRAL_GEMINI_ANNOTATE_PROMPT:-}"

# ── Graceful cleanup trap — kill orphaned workers on exit/interrupt ─────────
cleanup_parallel() {
  echo ""
  echo "  [parallel] Cleaning up workers..."
  # Two-phase kill: SIGTERM first, wait, then SIGKILL stragglers
  local child_pids
  child_pids=$(jobs -p 2>/dev/null) || true
  if [[ -n "$child_pids" ]]; then
    echo "$child_pids" | xargs kill 2>/dev/null || true
    sleep 2
    echo "$child_pids" | xargs kill -9 2>/dev/null || true
  fi
  # Clean up lock dir and pause files
  rm -rf "$LOCK_DIR" 2>/dev/null || true
  for n in $(seq 1 "$RALPH_WORKERS"); do
    rm -f "${SPIRAL_SCRATCH_DIR}/_worker_pause_${n}" 2>/dev/null || true
  done
  # Clean up worktrees and branches
  for i in $(seq 1 "$RALPH_WORKERS"); do
    local branch="${WORKER_BRANCHES[$((i-1))]:-}"
    local wtree="${WORKER_DIRS[$((i-1))]:-}"
    [[ -n "$wtree" && -d "$wtree" ]] && git -C "$REPO_ROOT" worktree remove "$wtree" --force 2>/dev/null || true
    [[ -n "$branch" ]] && git -C "$REPO_ROOT" branch -D "$branch" 2>/dev/null || true
  done
  rm -rf "$WORKTREE_BASE" 2>/dev/null || true
  echo "  [parallel] Cleanup done."
}
trap cleanup_parallel EXIT INT TERM

REAL_DOCKER="$(command -v docker 2>/dev/null || echo docker)"

# ── Pre-flight memory check — auto-reduce workers if RAM is low ────────────
# Per-worker budget: ~1536MB (1024 heap + ~512 non-heap overhead for Zones, JIT, etc.)
_PER_WORKER_MB=1536
if command -v powershell.exe &>/dev/null; then
  FREE_MB=$(powershell.exe -Command \
    "[math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)" 2>/dev/null | tr -d '\r')
  if [[ -n "$FREE_MB" && "$FREE_MB" =~ ^[0-9]+$ ]]; then
    NEEDED_MB=$(( RALPH_WORKERS * _PER_WORKER_MB + 512 ))
    if [[ "$RALPH_WORKERS" -gt 1 && "$FREE_MB" -lt "$NEEDED_MB" ]]; then
      MAX_SAFE=$(( (FREE_MB - 512) / _PER_WORKER_MB ))
      [[ "$MAX_SAFE" -lt 1 ]] && MAX_SAFE=1
      if [[ "$MAX_SAFE" -lt "$RALPH_WORKERS" ]]; then
        echo "  [parallel] Memory: ${FREE_MB}MB free, need ${NEEDED_MB}MB for $RALPH_WORKERS workers"
        echo "  [parallel] Auto-reducing workers: $RALPH_WORKERS → $MAX_SAFE"
        RALPH_WORKERS="$MAX_SAFE"
        ITER_PER_WORKER=$(( (RALPH_MAX_ITERS + RALPH_WORKERS - 1) / RALPH_WORKERS ))
      fi
    fi
  fi
fi

# ── Initial worker cap from pressure file ──────────────────────────────────────
if type spiral_recommended_workers &>/dev/null && [[ "${SPIRAL_LOW_POWER_MODE:-1}" -eq 1 ]]; then
  _REC_W=$(spiral_recommended_workers)
  if [[ -n "$_REC_W" && "$_REC_W" =~ ^[0-9]+$ && "$_REC_W" -lt "$RALPH_WORKERS" ]]; then
    echo "  [parallel] Memory pressure: capping workers $RALPH_WORKERS -> $_REC_W"
    spiral_log_low_power "run_parallel: initial worker cap $RALPH_WORKERS -> $_REC_W"
    RALPH_WORKERS="$_REC_W"
    ITER_PER_WORKER=$(( (RALPH_MAX_ITERS + RALPH_WORKERS - 1) / RALPH_WORKERS ))
  fi
fi

echo "  [parallel] ═══════════════════════════════════════════════════"
echo "  [parallel]  PARALLEL RALPH — $RALPH_WORKERS workers"
echo "  [parallel]  Iters/worker:  $ITER_PER_WORKER (total budget: $RALPH_MAX_ITERS)"
echo "  [parallel]  Docker lock:   $LOCK_DIR"
[[ -n "${SPIRAL_FOCUS:-}" ]] && echo "  [parallel]  Focus:         $SPIRAL_FOCUS"
[[ -n "$PATCH_DIRS" ]] && echo "  [parallel]  Patch dirs:    $PATCH_DIRS"
[[ -n "$DEPLOY_CMD" ]] && echo "  [parallel]  Deploy cmd:    (configured)"
echo "  [parallel] ═══════════════════════════════════════════════════"

# ── Step 0: Gemini filesTouch pre-annotation (optional) ─────────────────────
# Pre-populates filesTouch so partition_prd.py can co-locate related stories,
# reducing merge conflicts across parallel workers.
if command -v gemini &>/dev/null && [[ -n "$GEMINI_ANNOTATE" ]]; then
  echo "  [parallel] Step 0: Gemini filesTouch pre-annotation..."
  PENDING_IDS=$("$JQ" -r '.userStories[] | select(.passes != true) | .id' "$PRD_FILE" | tr -d '\r')
  ANNOTATION_COUNT=0
  for story_id in $PENDING_IDS; do
    # Skip stories that already have filesTouch populated
    EXISTING_FILES=$("$JQ" -r ".userStories[] | select(.id == \"$story_id\") | .filesTouch // [] | length" "$PRD_FILE" 2>/dev/null || echo "0")
    if [[ "$EXISTING_FILES" -gt 0 ]]; then
      continue
    fi
    STORY_TITLE=$("$JQ" -r ".userStories[] | select(.id == \"$story_id\") | .title" "$PRD_FILE" | tr -d '\r')
    # Ask gemini which files this story touches; extract first JSON array from response
    PROMPT="${GEMINI_ANNOTATE//__STORY_TITLE__/$STORY_TITLE}"
    FILES=$(gemini \
      -m gemini-2.0-flash \
      -p "$PROMPT" \
      --output-format text 2>/dev/null | grep -o '\[.*\]' | head -1 || echo "[]")
    if [[ "$FILES" != "[]" && -n "$FILES" ]]; then
      UPDATED=$("$JQ" --arg id "$story_id" --argjson files "$FILES" \
        '(.userStories[] | select(.id == $id) | .filesTouch) = $files' "$PRD_FILE" 2>/dev/null) || true
      [[ -n "$UPDATED" ]] && echo "$UPDATED" > "$PRD_FILE"
      ANNOTATION_COUNT=$((ANNOTATION_COUNT + 1))
    fi
  done
  echo "  [parallel] Gemini annotated $ANNOTATION_COUNT stories with filesTouch hints"
else
  echo "  [parallel] Step 0: gemini annotation skipped (not configured or gemini not found)"
fi
echo ""

# ── Source assertion library (set SPIRAL_PYTHON for compatibility) ────────────
SPIRAL_PYTHON="${SPIRAL_PYTHON:-$PYTHON}"
export SPIRAL_PYTHON
source "$SPIRAL_HOME/lib/spiral_assert.sh"

# ── Resolve spiral-core binary (Rust hot-path) ────────────────────────────────
_SC_BIN=""
for _sc in "$SPIRAL_HOME/lib/spiral-core" "$SPIRAL_HOME/lib/spiral-core.exe"; do
  [[ -x "$_sc" ]] && { _SC_BIN="$_sc"; break; }
done

# ── Step 1: Partition pending stories into worker prd files ───────────────────
mkdir -p "$WORKER_DIR"
if [[ -n "$_SC_BIN" ]]; then
  "$_SC_BIN" partition \
    --prd "$PRD_FILE" \
    --workers "$RALPH_WORKERS" \
    --outdir "$WORKER_DIR"
else
  "$PYTHON" "$SPIRAL_HOME/lib/partition_prd.py" \
    --prd "$PRD_FILE" \
    --workers "$RALPH_WORKERS" \
    --outdir "$WORKER_DIR"
fi

# ── Step 1.5: Verify worker partitions have no overlapping pending stories ────
WORKER_PRD_FILES=()
for i in $(seq 1 "$RALPH_WORKERS"); do
  WORKER_PRD_FILES+=("$WORKER_DIR/worker_${i}.json")
done
spiral_assert_worker_disjoint "$WORKER_DIR" "${WORKER_PRD_FILES[@]}"

# ── Disk space preflight check ────────────────────────────────────────────────
# Estimates working-tree size × workers; aborts if > 90% of available space.
# Git worktrees share .git objects, so actual use ≈ working tree size per worker.
if [[ "${SPIRAL_SKIP_DISK_CHECK:-0}" != "1" ]]; then
  _REPO_SIZE_KB=$(du -sk "$REPO_ROOT" 2>/dev/null | awk '{print $1}' || echo "0")
  _AVAIL_KB=$(df -k "$REPO_ROOT" 2>/dev/null | awk 'NR==2 {print $4}' || echo "0")
  if [[ "$_REPO_SIZE_KB" =~ ^[0-9]+$ && "$_AVAIL_KB" =~ ^[0-9]+$ \
     && "$_REPO_SIZE_KB" -gt 0 && "$_AVAIL_KB" -gt 0 ]]; then
    _NEEDED_KB=$(( _REPO_SIZE_KB * RALPH_WORKERS ))
    # Abort if estimated need exceeds 90% of available space
    if (( _NEEDED_KB * 10 > _AVAIL_KB * 9 )); then
      echo "  [parallel] ERROR: Insufficient disk space for $RALPH_WORKERS worktrees."
      echo "  [parallel]   Repo size:       $(( _REPO_SIZE_KB / 1024 )) MB"
      echo "  [parallel]   Workers:         $RALPH_WORKERS"
      echo "  [parallel]   Estimated need:  $(( _NEEDED_KB / 1024 )) MB  ($RALPH_WORKERS × $(( _REPO_SIZE_KB / 1024 )) MB)"
      echo "  [parallel]   Available:       $(( _AVAIL_KB / 1024 )) MB"
      echo "  [parallel]   Set SPIRAL_SKIP_DISK_CHECK=1 to bypass this check."
      exit 1
    else
      echo "  [parallel] Disk OK: need ~$(( _NEEDED_KB / 1024 ))MB, have $(( _AVAIL_KB / 1024 ))MB free"
    fi
  else
    echo "  [parallel] Disk check: could not read disk stats — skipping (graceful degradation)"
  fi
fi

# ── Step 2: Create git worktrees + docker lock wrapper per worker ─────────────
declare -a WORKER_DIRS=()
declare -a WORKER_BRANCHES=()

for i in $(seq 1 "$RALPH_WORKERS"); do
  BRANCH="spiral-worker-${i}-${TIMESTAMP}"
  WTREE="$WORKTREE_BASE/worker-${i}"

  # Remove stale worktree if it exists
  git -C "$REPO_ROOT" worktree remove "$WTREE" --force 2>/dev/null || rm -rf "$WTREE" 2>/dev/null || true
  git -C "$REPO_ROOT" worktree add "$WTREE" -b "$BRANCH" HEAD

  # Overlay worker prd.json + override branchName to match the worker's own branch
  cp "$WORKER_DIR/worker_${i}.json" "$WTREE/prd.json"
  "$JQ" --arg b "$BRANCH" '.branchName = $b' "$WTREE/prd.json" > "$WTREE/prd.json.tmp" && mv "$WTREE/prd.json.tmp" "$WTREE/prd.json"

  # Fresh per-worker state files (avoid cross-worker contamination)
  echo "{}" > "$WTREE/retry-counts.json"
  echo "## Worker $i progress" > "$WTREE/progress.txt"

  # ── Docker lock wrapper ─────────────────────────────────────────────────
  # Serializes: docker cp  AND  docker exec ... bench (migrate/run-tests)
  # All other docker commands pass through immediately.
  mkdir -p "$WTREE/.spiral-bin"
  WRAPPER="$WTREE/.spiral-bin/docker"
  cat > "$WRAPPER" << WRAPPER_SCRIPT
#!/bin/bash
# Parallel Ralph docker lock wrapper — serializes container deploy+test ops
REAL="$REAL_DOCKER"
LOCK="$LOCK_DIR"
NEEDS_LOCK=0
[[ "\$1" == "cp" ]] && NEEDS_LOCK=1
# Lock only write-mutating bench operations; read-only calls pass through
[[ "\$*" == *"bench migrate"* ]] && NEEDS_LOCK=1
[[ "\$*" == *"bench sync_fixtures"* ]] && NEEDS_LOCK=1
[[ "\$*" == *"bench install-app"* ]] && NEEDS_LOCK=1
if [[ "\$NEEDS_LOCK" -eq 1 ]]; then
  # Spin-wait using mkdir atomicity (works on all POSIX + MSYS2 / Git Bash)
  while ! mkdir "\$LOCK" 2>/dev/null; do sleep 1; done
  "\$REAL" "\$@"
  RC=\$?
  rmdir "\$LOCK" 2>/dev/null || true
  exit \$RC
else
  exec "\$REAL" "\$@"
fi
WRAPPER_SCRIPT
  chmod +x "$WRAPPER"

  # Patch ralph-config.sh: use per-worker bench output file to avoid cross-worker race.
  WORKER_BENCH_OUT="/tmp/ralph-bench-output-worker-${i}.txt"
  sed -i "s|/tmp/ralph-bench-output\.txt|${WORKER_BENCH_OUT}|g" "$WTREE/ralph-config.sh" 2>/dev/null || true

  STORY_COUNT=$("$JQ" '[.userStories[] | select(.passes != true)] | length' "$WTREE/prd.json" 2>/dev/null || echo "?")
  echo "  [parallel] Worker $i ready — branch: $BRANCH | pending: $STORY_COUNT stories"

  WORKER_DIRS+=("$WTREE")
  WORKER_BRANCHES+=("$BRANCH")
done

# ── Step 2.5: Spawn live monitor terminal per worker (if --monitor) ───────────
if [[ "$MONITOR_TERMINALS" -eq 1 ]]; then
  # Auto-detect terminal emulator
  if [[ -n "$TERMINAL_EMU" ]]; then
    WT_EXE="$TERMINAL_EMU"
  elif [[ -f "/c/Users/$USER/AppData/Local/Microsoft/WindowsApps/wt.exe" ]]; then
    WT_EXE="/c/Users/$USER/AppData/Local/Microsoft/WindowsApps/wt.exe"
  else
    WT_EXE=""
  fi

  for i in $(seq 1 "$RALPH_WORKERS"); do
    LOG="$WORKER_DIR/worker_${i}.log"
    touch "$LOG"   # ensure file exists before tail -f attaches

    TITLE="SPIRAL Worker $i"
    INNER="echo '=== $TITLE — live log (ANSI colors ON) ==='; echo; tail -f '$LOG'"

    if [[ -n "$WT_EXE" && -f "$WT_EXE" ]]; then
      "$WT_EXE" --window 0 new-tab --title "$TITLE" -- bash.exe -c "$INNER" &
    elif command -v mintty &>/dev/null; then
      mintty --title "$TITLE" /bin/bash -c "$INNER" &
    else
      echo "  [parallel] WARNING: no terminal emulator found for --monitor"
      break
    fi

    echo "  [parallel] Monitor terminal opened for worker $i"
    sleep 0.3   # brief stagger so wt.exe doesn't race when opening multiple tabs
  done
fi

# ── Memory gate helper — wait until enough RAM is free before spawning ────────
# Prevents all workers launching simultaneously and collectively OOM'ing.
wait_for_memory() {
  local min_mb=${1:-2048}
  if ! command -v powershell.exe &>/dev/null; then
    return 0  # skip on non-Windows (no CIM)
  fi
  local attempts=0
  while true; do
    local free_mb
    free_mb=$(powershell.exe -NoProfile -Command \
      "[math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)" \
      2>/dev/null | tr -d '\r')
    if [[ -z "$free_mb" || ! "$free_mb" =~ ^[0-9]+$ ]]; then
      break  # can't read memory — don't block forever
    fi
    if [[ "$free_mb" -ge "$min_mb" ]]; then
      break
    fi
    echo "  [memory-gate] Only ${free_mb}MB free, waiting for ${min_mb}MB before spawning..."
    if type spiral_log_low_power &>/dev/null; then
      spiral_log_low_power "memory-gate: ${free_mb}MB free < ${min_mb}MB required, waiting"
    fi
    attempts=$((attempts + 1))
    if [[ "$attempts" -ge 30 ]]; then
      echo "  [memory-gate] Waited 5 minutes — proceeding anyway"
      break
    fi
    sleep 10
  done
}

# ── Step 3: Launch all workers in background (staggered) ─────────────────────
# Workers are staggered by 20 seconds to let each process complete its initial
# V8 compilation (the most memory-intensive phase) before the next one starts.
declare -a WORKER_PIDS=()
STAGGER_DELAY=20  # seconds between worker launches

for i in $(seq 1 "$RALPH_WORKERS"); do
  WTREE="${WORKER_DIRS[$((i-1))]}"
  LOG="$WORKER_DIR/worker_${i}.log"
  touch "$LOG"   # pre-create so tail -f attaches even if worker is slow to start

  # Wait for sufficient free RAM before each worker spawn
  _MIN_FREE_MB=$(( (RALPH_WORKERS - i + 1) * 1536 + 512 ))
  [[ "$_MIN_FREE_MB" -lt 2048 ]] && _MIN_FREE_MB=2048
  wait_for_memory "$_MIN_FREE_MB"

  echo "  [parallel] Launching worker $i → log: $LOG"
  # Build model flag for this worker
  _WORKER_MODEL_FLAG=""
  [[ -n "$RALPH_MODEL" ]] && _WORKER_MODEL_FLAG="--model $RALPH_MODEL"
  (
    cd "$WTREE"
    # Put lock wrapper first in PATH so docker calls are intercepted
    export PATH="$WTREE/.spiral-bin:$PATH"
    export SPIRAL_WORKER_ID=$i
    bash "$RALPH_SKILL" "$ITER_PER_WORKER" --prd prd.json $_WORKER_MODEL_FLAG \
      > "$LOG" 2>&1
  ) &
  WORKER_PIDS+=($!)

  # Stagger launches — let V8 init settle before spawning next worker
  if [[ "$i" -lt "$RALPH_WORKERS" ]]; then
    echo "  [parallel] Waiting ${STAGGER_DELAY}s before next worker (V8 init cooldown)..."
    sleep "$STAGGER_DELAY"
  fi
done

echo ""
TAIL_LOGS=$(seq 1 "$RALPH_WORKERS" | while read -r n; do printf "%s " "$WORKER_DIR/worker_${n}.log"; done)
echo "  [parallel] All $RALPH_WORKERS workers running."
echo "  [parallel] Monitor single:  tail -f $WORKER_DIR/worker_1.log"
echo "  [parallel] Monitor all:     tail -f $TAIL_LOGS"
echo "  [parallel] Waiting for completion..."
echo ""

# ── Step 4: Adaptive wait loop — monitor workers + manage pressure ────────────
declare -a WORKER_FINISHED=()
for i in "${!WORKER_PIDS[@]}"; do
  WORKER_FINISHED+=("0")
done

_ALL_DONE=0
while [[ "$_ALL_DONE" -eq 0 ]]; do
  _ALL_DONE=1
  _ACTIVE_COUNT=0

  for i in "${!WORKER_PIDS[@]}"; do
    if [[ "${WORKER_FINISHED[$i]}" -eq 0 ]]; then
      if ! kill -0 "${WORKER_PIDS[$i]}" 2>/dev/null; then
        # Worker finished
        WORKER_FINISHED[$i]=1
        WORKER_NUM=$((i + 1))
        wait "${WORKER_PIDS[$i]}" 2>/dev/null || true
        WTREE="${WORKER_DIRS[$i]}"
        DONE_W=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$WTREE/prd.json" 2>/dev/null || echo "?")
        TOTAL_W=$("$JQ" '[.userStories | length] | .[0]' "$WTREE/prd.json" 2>/dev/null || echo "?")
        echo "  [parallel] Worker $WORKER_NUM finished: $DONE_W/$TOTAL_W stories passed"
        # Remove pause file if it exists
        rm -f "${SPIRAL_SCRATCH_DIR}/_worker_pause_${WORKER_NUM}" 2>/dev/null || true
      else
        _ALL_DONE=0
        _ACTIVE_COUNT=$((_ACTIVE_COUNT + 1))
      fi
    fi
  done

  [[ "$_ALL_DONE" -eq 1 ]] && break

  # ── Adaptive pressure management: pause/resume workers ─────────────────────
  if type spiral_recommended_workers &>/dev/null && [[ "${SPIRAL_LOW_POWER_MODE:-1}" -eq 1 ]]; then
    _REC_W=$(spiral_recommended_workers)
    if [[ -n "$_REC_W" && "$_REC_W" =~ ^[0-9]+$ ]]; then
      if [[ "$_REC_W" -lt "$_ACTIVE_COUNT" ]]; then
        # Need to pause some workers — pause highest-numbered first
        _RUNNING=0
        for j in "${!WORKER_PIDS[@]}"; do
          WORKER_NUM=$((j + 1))
          if [[ "${WORKER_FINISHED[$j]}" -eq 0 ]]; then
            _RUNNING=$((_RUNNING + 1))
            if [[ "$_RUNNING" -gt "$_REC_W" ]]; then
              _PAUSE_F="${SPIRAL_SCRATCH_DIR}/_worker_pause_${WORKER_NUM}"
              if [[ ! -f "$_PAUSE_F" ]]; then
                touch "$_PAUSE_F"
                echo "  [parallel] Pausing worker $WORKER_NUM (pressure: recommended $_REC_W workers)"
                spiral_log_low_power "run_parallel: paused worker $WORKER_NUM (recommended $_REC_W)"
              fi
            fi
          fi
        done
      else
        # Pressure eased — resume any paused workers
        for j in "${!WORKER_PIDS[@]}"; do
          WORKER_NUM=$((j + 1))
          _PAUSE_F="${SPIRAL_SCRATCH_DIR}/_worker_pause_${WORKER_NUM}"
          if [[ -f "$_PAUSE_F" ]]; then
            rm -f "$_PAUSE_F"
            echo "  [parallel] Resuming worker $WORKER_NUM (pressure eased)"
            spiral_log_low_power "run_parallel: resumed worker $WORKER_NUM"
          fi
        done
      fi
    fi
  fi

  sleep 10
done

# Resume all paused workers before returning (safety net)
for i in $(seq 1 "$RALPH_WORKERS"); do
  rm -f "${SPIRAL_SCRATCH_DIR}/_worker_pause_${i}" 2>/dev/null || true
done

# ── Step 5: Print last 5 lines of each worker log ─────────────────────────────
echo ""
for i in $(seq 1 "$RALPH_WORKERS"); do
  echo "  ─── Worker $i (last 5 lines) ────────────────────────────────────"
  tail -5 "$WORKER_DIR/worker_${i}.log" 2>/dev/null | sed 's/^/  │ /' || true
done
echo ""

# ── Step 6: Merge prd.json pass results into main prd.json ───────────────────
# Re-encode all worker prd.json files to clean UTF-8 first.
for wtree in "${WORKER_DIRS[@]}"; do
  WPRD="$wtree/prd.json"
  [[ -f "$WPRD" ]] || continue
  "$PYTHON" - "$WPRD" << 'PYEOF'
import json, sys
path = sys.argv[1]
with open(path, encoding='utf-8', errors='replace') as f:
    content = f.read()
try:
    d = json.loads(content)
except Exception:
    with open(path, encoding='cp1252', errors='replace') as f:
        d = json.load(f)
with open(path, 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
    f.write('\n')
PYEOF
done

WORKER_PRDS=()
for wtree in "${WORKER_DIRS[@]}"; do
  WORKER_PRDS+=("$wtree/prd.json")
done

if [[ -n "$_SC_BIN" ]]; then
  "$_SC_BIN" merge-workers \
    --main "$PRD_FILE" \
    --workers "${WORKER_PRDS[@]}"
else
  "$PYTHON" "$SPIRAL_HOME/lib/merge_worker_results.py" \
    --main "$PRD_FILE" \
    --workers "${WORKER_PRDS[@]}"
fi

# Re-encode main prd.json to clean UTF-8 after merge
"$PYTHON" - "$PRD_FILE" << 'PYEOF'
import json, sys
path = sys.argv[1]
with open(path, encoding='utf-8', errors='replace') as f:
    content = f.read()
try:
    d = json.loads(content)
except Exception:
    with open(path, encoding='cp1252', errors='replace') as f:
        d = json.load(f)
with open(path, 'w', encoding='utf-8') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
    f.write('\n')
PYEOF

# Commit the merged prd.json as a stable base before code patches
git -C "$REPO_ROOT" add "$PRD_FILE" 2>/dev/null
git -C "$REPO_ROOT" commit -m "chore(spiral): merge prd.json from $RALPH_WORKERS parallel workers" \
  2>/dev/null || true

# ── Step 6.5: Extract patches + pre-detect conflicts via dry-run ─────────────
echo "  [parallel] Extracting and pre-checking patches for conflicts..."
declare -a CLEAN_WORKERS=()
declare -a CONFLICT_WORKERS=()

# Build git diff args from SPIRAL_PATCH_DIRS (or diff everything if empty)
DIFF_PATHS=()
if [[ -n "$PATCH_DIRS" ]]; then
  for d in $PATCH_DIRS; do
    DIFF_PATHS+=("$d")
  done
fi

for i in $(seq 1 "$RALPH_WORKERS"); do
  BRANCH="${WORKER_BRANCHES[$((i-1))]}"
  PATCH_FILE="$WORKER_DIR/worker_${i}.patch"

  if [[ ${#DIFF_PATHS[@]} -gt 0 ]]; then
    git -C "$REPO_ROOT" diff "HEAD..$BRANCH" -- \
      "${DIFF_PATHS[@]}" \
      > "$PATCH_FILE" 2>/dev/null || true
  else
    git -C "$REPO_ROOT" diff "HEAD..$BRANCH" \
      > "$PATCH_FILE" 2>/dev/null || true
  fi

  if [[ ! -s "$PATCH_FILE" ]]; then
    echo "  [parallel] Worker $i: no code changes (skipping)"
    continue
  fi

  if git -C "$REPO_ROOT" apply --check "$PATCH_FILE" 2>/dev/null; then
    CLEAN_WORKERS+=($i)
  else
    CONFLICT_WORKERS+=($i)
    echo "  [parallel] WARNING: Worker $i patch will conflict"
  fi
done
echo "  [parallel] Pre-check: ${#CLEAN_WORKERS[@]} clean, ${#CONFLICT_WORKERS[@]} conflicting"

# ── Step 7: Apply code changes — clean patches first, largest-first within each group ──
PATCHES_APPLIED=0
PATCHES_CONFLICTED=0

sort_by_patch_size() {
  for i in "$@"; do
    SIZE=$(wc -c < "$WORKER_DIR/worker_${i}.patch" 2>/dev/null || echo 0)
    echo "$SIZE $i"
  done | sort -rn | awk '{print $2}'
}

SORTED_CLEAN=$(sort_by_patch_size "${CLEAN_WORKERS[@]}")
SORTED_CONFLICT=$(sort_by_patch_size "${CONFLICT_WORKERS[@]}")

for i in $SORTED_CLEAN $SORTED_CONFLICT; do
  PATCH_FILE="$WORKER_DIR/worker_${i}.patch"
  LINES=$(wc -l < "$PATCH_FILE")
  SIZE=$(wc -c < "$PATCH_FILE" 2>/dev/null || echo 0)
  echo "  [parallel] Worker $i: applying $LINES-line patch (${SIZE} bytes)..."

  if git -C "$REPO_ROOT" apply --3way "$PATCH_FILE" 2>/dev/null; then
    git -C "$REPO_ROOT" add -A 2>/dev/null
    git -C "$REPO_ROOT" commit \
      -m "feat(spiral): worker $i parallel implementation" \
      2>/dev/null || true
    PATCHES_APPLIED=$((PATCHES_APPLIED + 1))
    echo "  [parallel] Worker $i code applied cleanly"
  else
    # 3-way failed — apply with --reject to get partial apply + .rej files
    echo "  [parallel] WARNING: Worker $i patch had conflicts — applying with --reject"
    git -C "$REPO_ROOT" apply --reject "$PATCH_FILE" 2>/dev/null || true
    git -C "$REPO_ROOT" add -A 2>/dev/null
    git -C "$REPO_ROOT" commit \
      -m "feat(spiral): worker $i code (partial — .rej files need review)" \
      2>/dev/null || true
    PATCHES_CONFLICTED=$((PATCHES_CONFLICTED + 1))
    echo "  [parallel] Worker $i: partial apply done; review *.rej files for conflicts"
  fi
done

echo "  [parallel] Code patches: $PATCHES_APPLIED clean, $PATCHES_CONFLICTED with conflicts"

# ── Step 8: Deploy merged code (optional, configured via SPIRAL_DEPLOY_CMD) ──
if [[ -n "$DEPLOY_CMD" ]]; then
  echo "  [parallel] Deploying merged code..."
  if eval "$DEPLOY_CMD" 2>/dev/null; then
    echo "  [parallel] Deploy complete"
  else
    echo "  [parallel] WARNING: Deploy command failed — code in repo is correct"
  fi
else
  echo "  [parallel] No deploy command configured — skipping container deploy"
fi

# ── Step 8.5: Merge worker results.tsv files (dedup + sort) ──────────────────
WORKER_RESULTS=()
for wtree in "${WORKER_DIRS[@]}"; do
  [[ -f "$wtree/results.tsv" ]] && WORKER_RESULTS+=("$wtree/results.tsv")
done
if [[ ${#WORKER_RESULTS[@]} -gt 0 ]]; then
  echo "  [parallel] Merging ${#WORKER_RESULTS[@]} worker results.tsv files..."
  "$PYTHON" "$SPIRAL_HOME/lib/merge_results_tsv.py" \
    --main "$REPO_ROOT/results.tsv" \
    --workers "${WORKER_RESULTS[@]}"
fi

# ── Step 9: Cleanup worktrees, branches, and lock ────────────────────────────
rm -rf "$LOCK_DIR" 2>/dev/null || true

for i in $(seq 1 "$RALPH_WORKERS"); do
  BRANCH="${WORKER_BRANCHES[$((i-1))]}"
  WTREE="${WORKER_DIRS[$((i-1))]}"
  git -C "$REPO_ROOT" worktree remove "$WTREE" --force 2>/dev/null || true
  git -C "$REPO_ROOT" branch -D "$BRANCH" 2>/dev/null || true
done
rm -rf "$WORKTREE_BASE" 2>/dev/null || true

echo "  [parallel] Cleanup complete."
echo "  [parallel] ═══════════════════════════════════════════════════"

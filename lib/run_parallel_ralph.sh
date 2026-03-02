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

REAL_DOCKER="$(command -v docker 2>/dev/null || echo docker)"

echo "  [parallel] ═══════════════════════════════════════════════════"
echo "  [parallel]  PARALLEL RALPH — $RALPH_WORKERS workers"
echo "  [parallel]  Iters/worker:  $ITER_PER_WORKER (total budget: $RALPH_MAX_ITERS)"
echo "  [parallel]  Docker lock:   $LOCK_DIR"
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

# ── Step 1: Partition pending stories into worker prd files ───────────────────
mkdir -p "$WORKER_DIR"
"$PYTHON" "$SPIRAL_HOME/lib/partition_prd.py" \
  --prd "$PRD_FILE" \
  --workers "$RALPH_WORKERS" \
  --outdir "$WORKER_DIR"

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

# ── Step 3: Launch all workers in background ──────────────────────────────────
declare -a WORKER_PIDS=()

for i in $(seq 1 "$RALPH_WORKERS"); do
  WTREE="${WORKER_DIRS[$((i-1))]}"
  LOG="$WORKER_DIR/worker_${i}.log"
  touch "$LOG"   # pre-create so tail -f attaches even if worker is slow to start

  echo "  [parallel] Launching worker $i → log: $LOG"
  # Build model flag for this worker
  _WORKER_MODEL_FLAG=""
  [[ -n "$RALPH_MODEL" ]] && _WORKER_MODEL_FLAG="--model $RALPH_MODEL"
  (
    cd "$WTREE"
    # Put lock wrapper first in PATH so docker calls are intercepted
    export PATH="$WTREE/.spiral-bin:$PATH"
    bash "$RALPH_SKILL" "$ITER_PER_WORKER" --prd prd.json $_WORKER_MODEL_FLAG \
      > "$LOG" 2>&1
  ) &
  WORKER_PIDS+=($!)
done

echo ""
TAIL_LOGS=$(seq 1 "$RALPH_WORKERS" | while read -r n; do printf "%s " "$WORKER_DIR/worker_${n}.log"; done)
echo "  [parallel] All $RALPH_WORKERS workers running."
echo "  [parallel] Monitor single:  tail -f $WORKER_DIR/worker_1.log"
echo "  [parallel] Monitor all:     tail -f $TAIL_LOGS"
echo "  [parallel] Waiting for completion..."
echo ""

# ── Step 4: Wait for all workers ──────────────────────────────────────────────
for i in "${!WORKER_PIDS[@]}"; do
  PID="${WORKER_PIDS[$i]}"
  WORKER_NUM=$((i + 1))
  wait "$PID" || true  # ralph exits non-zero when no stories remain — expected

  WTREE="${WORKER_DIRS[$i]}"
  DONE_W=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$WTREE/prd.json" 2>/dev/null || echo "?")
  TOTAL_W=$("$JQ" '[.userStories | length] | .[0]' "$WTREE/prd.json" 2>/dev/null || echo "?")
  echo "  [parallel] Worker $WORKER_NUM finished: $DONE_W/$TOTAL_W stories passed"
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

"$PYTHON" "$SPIRAL_HOME/lib/merge_worker_results.py" \
  --main "$PRD_FILE" \
  --workers "${WORKER_PRDS[@]}"

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

#!/usr/bin/env bash
# lib/spiral_startup.sh -- SPIRAL pre-loop startup initialization
#
# Sourced by spiral.sh (runs in caller scope, not a function).
# Performs one-time startup tasks before the main iteration loop:
#   - Pre-flight memory check & worker auto-adjust
#   - Dirty worktree detection & reset
#   - Worktree prune audit
#   - Research cache invalidation on constitution change
#   - SPIRAL banner, UI registration, mode handlers
#   - Checkpoint resume, progress init, stale story detection

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

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

# ── Detect and reset dirty worker worktrees (US-218, US-247) ──────────────────
# When a previous session was interrupted (OOM, Ctrl-C, network drop), worker
# worktrees may be left with staged/unstaged changes. Detect each dirty worktree
# and reset it to a clean state so the next run starts consistently.
# US-247: Use git diff-index --quiet HEAD as a fast pre-check (~15ms) before
# falling back to full git status --porcelain (~80ms) for confirmed dirty worktrees.
if [[ -d "$REPO_ROOT/.spiral-workers" ]]; then
  _DIRTY_WORKERS_CLEANED=()
  _DIFFIDX_SKIPPED=0
  _DIFFIDX_TOTAL=0
  for _wt_dir in "$REPO_ROOT/.spiral-workers"/worker-*; do
    [[ -d "$_wt_dir" ]] || continue
    _DIFFIDX_TOTAL=$((_DIFFIDX_TOTAL + 1))
    # Fast pre-check: diff-index exits 0 for clean, non-zero for dirty (~15ms vs ~80ms)
    if git -C "$_wt_dir" diff-index --quiet HEAD -- 2>/dev/null; then
      # Worktree is clean — skip expensive full status
      _DIFFIDX_SKIPPED=$((_DIFFIDX_SKIPPED + 1))
      continue
    fi
    # Worktree reported dirty by diff-index; confirm with full status for accuracy
    _wt_status=$(git -C "$_wt_dir" status --porcelain 2>/dev/null) || continue
    if [[ -n "$_wt_status" ]]; then
      _wt_name=$(basename "$_wt_dir")
      echo "  [startup] Dirty worktree detected: $_wt_name — resetting to clean state"
      # Remove stale index.lock before reset (may be left by OOM-killed process)
      if [[ -f "$_wt_dir/.git" ]]; then
        _wt_git_dir=$(sed 's/^gitdir: //' "$_wt_dir/.git" 2>/dev/null || true)
        [[ -n "$_wt_git_dir" && -f "$_wt_git_dir/index.lock" ]] && rm -f "$_wt_git_dir/index.lock"
      fi
      # Reset staged changes, then discard unstaged modifications
      git -C "$_wt_dir" reset HEAD 2>/dev/null || true
      git -C "$_wt_dir" checkout -- . 2>/dev/null || true
      # Remove any untracked files left behind
      git -C "$_wt_dir" clean -fd 2>/dev/null || true
      _DIRTY_WORKERS_CLEANED+=("$_wt_name")
    fi
  done
  if [[ "$_DIFFIDX_TOTAL" -gt 0 ]]; then
    echo "  [startup] Worktree status: Skipped full status on ${_DIFFIDX_SKIPPED}/${_DIFFIDX_TOTAL} worktrees (clean)"
  fi
  if [[ ${#_DIRTY_WORKERS_CLEANED[@]} -gt 0 ]]; then
    _cleaned_list=$(
      IFS=,
      echo "${_DIRTY_WORKERS_CLEANED[*]}"
    )
    echo "  [startup] Reset ${#_DIRTY_WORKERS_CLEANED[@]} dirty worktree(s): $_cleaned_list"
    log_spiral_event "worker_reset_dirty_worktree" \
      "\"worktrees\":[$(printf '"%s",' "${_DIRTY_WORKERS_CLEANED[@]}" | sed 's/,$//')],\"count\":${#_DIRTY_WORKERS_CLEANED[@]}"
  fi
fi

# ── US-370: Worktree prune audit at startup ──────────────────────────────────
# Run `git worktree prune --dry-run --verbose` to discover stale entries,
# auto-prune only those under .spiral-workers/, and warn about the rest.
# Note: --dry-run output uses internal admin names (e.g. "Removing worktrees/worker-1")
# so we resolve actual worktree paths via .git/worktrees/<name>/gitdir.
_WT_AUDIT_LOG="$SCRATCH_DIR/worktree_audit.log"
_WT_PRUNE_DRY=$(git -C "$REPO_ROOT" worktree prune --dry-run --verbose 2>&1 || true)
printf '%s\n' "$_WT_PRUNE_DRY" >"$_WT_AUDIT_LOG" 2>/dev/null || true

if [[ -n "$_WT_PRUNE_DRY" ]]; then
  echo "  [startup] Worktree prune dry-run found stale entries — see .spiral/worktree_audit.log"
  log_spiral_event "worktree_prune_audit" \
    "\"stale_count\":$(echo "$_WT_PRUNE_DRY" | grep -c '.' || echo 0),\"action\":\"dry_run\""

  # Classify stale entries as SPIRAL-owned or external by resolving admin gitdir
  _WT_AUTO_PRUNED=0
  _WT_EXTERNAL_WARN=0
  while IFS= read -r _wt_line; do
    [[ -z "$_wt_line" ]] && continue
    # Extract admin record name: "Removing worktrees/<name>: ..." → <name>
    _wt_admin_name=""
    if [[ "$_wt_line" =~ Removing\ worktrees/([^:]+): ]]; then
      _wt_admin_name="${BASH_REMATCH[1]}"
    fi
    if [[ -n "$_wt_admin_name" ]]; then
      # Resolve actual worktree path from .git/worktrees/<name>/gitdir
      _wt_gitdir_file="$REPO_ROOT/.git/worktrees/$_wt_admin_name/gitdir"
      _wt_actual_path=""
      [[ -f "$_wt_gitdir_file" ]] && _wt_actual_path=$(cat "$_wt_gitdir_file" 2>/dev/null || true)
      if echo "$_wt_actual_path" | grep -qF ".spiral-workers/"; then
        _WT_AUTO_PRUNED=$((_WT_AUTO_PRUNED + 1))
      else
        _WT_EXTERNAL_WARN=$((_WT_EXTERNAL_WARN + 1))
      fi
    else
      # Unparseable line — treat as external to be safe
      _WT_EXTERNAL_WARN=$((_WT_EXTERNAL_WARN + 1))
    fi
  done <<<"$_WT_PRUNE_DRY"

  if [[ "$_WT_AUTO_PRUNED" -gt 0 ]]; then
    # Safe to auto-prune: stale entries belong to SPIRAL's own worktree dir
    git -C "$REPO_ROOT" worktree prune 2>/dev/null || true
    echo "  [startup] Auto-pruned ${_WT_AUTO_PRUNED} stale SPIRAL worktree record(s)"
    log_spiral_event "worktree_prune_auto" \
      "\"pruned_count\":${_WT_AUTO_PRUNED}"
  fi

  if [[ "$_WT_EXTERNAL_WARN" -gt 0 ]]; then
    echo "  [startup] WARN: ${_WT_EXTERNAL_WARN} stale worktree(s) outside .spiral-workers/ — manual review recommended"
    log_spiral_event "worktree_prune_external_warn" \
      "\"external_count\":${_WT_EXTERNAL_WARN}"
  fi
fi

# ── US-302: Research cache invalidation on constitution.md change ──────────
# When constitution.md changes between runs, cached research may be misaligned
# with updated project goals. Detect hash change and clear the cache if needed.
# Controlled by SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE (default: true).
if [[ "${SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE:-true}" != "false" ]]; then
  _CONSTITUTION_HASH_FILE="$SCRATCH_DIR/_constitution_hash"
  # Resolve constitution file: prefer SPIRAL_SPECKIT_CONSTITUTION, fallback to constitution.md
  _CONSTITUTION_FILE=""
  if [[ -n "$SPIRAL_SPECKIT_CONSTITUTION" && -f "$REPO_ROOT/$SPIRAL_SPECKIT_CONSTITUTION" ]]; then
    _CONSTITUTION_FILE="$REPO_ROOT/$SPIRAL_SPECKIT_CONSTITUTION"
  elif [[ -f "$REPO_ROOT/constitution.md" ]]; then
    _CONSTITUTION_FILE="$REPO_ROOT/constitution.md"
  fi
  if [[ -n "$_CONSTITUTION_FILE" ]]; then
    # Compute SHA-256; prefer sha256sum (coreutils), fall back to Python
    _NEW_CONST_HASH=$(sha256sum "$_CONSTITUTION_FILE" 2>/dev/null | cut -d' ' -f1 ||
      "$SPIRAL_PYTHON" -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())" \
        "$_CONSTITUTION_FILE" 2>/dev/null || echo "")
    if [[ -n "$_NEW_CONST_HASH" ]]; then
      _OLD_CONST_HASH=""
      [[ -f "$_CONSTITUTION_HASH_FILE" ]] && _OLD_CONST_HASH=$(tr -d '[:space:]' <"$_CONSTITUTION_HASH_FILE" 2>/dev/null || echo "")
      if [[ "$_OLD_CONST_HASH" != "$_NEW_CONST_HASH" ]]; then
        _CONST_CLEARED_COUNT=0
        if [[ -d "$RESEARCH_CACHE_DIR" ]]; then
          _CONST_CLEARED_COUNT=$(find "$RESEARCH_CACHE_DIR" -maxdepth 1 -type f 2>/dev/null | wc -l | tr -d '[:space:]')
          find "$RESEARCH_CACHE_DIR" -maxdepth 1 -type f -delete 2>/dev/null || true
        fi
        # Persist new hash
        printf '%s\n' "$_NEW_CONST_HASH" >"$_CONSTITUTION_HASH_FILE"
        if [[ -n "$_OLD_CONST_HASH" ]]; then
          echo "  [startup] constitution.md changed — cleared ${_CONST_CLEARED_COUNT} research cache entries"
          echo "  [startup] Old: ${_OLD_CONST_HASH:0:16}… → New: ${_NEW_CONST_HASH:0:16}…"
          log_spiral_event "research_cache_invalidated" \
            "\"old_hash\":\"$_OLD_CONST_HASH\",\"new_hash\":\"$_NEW_CONST_HASH\",\"cleared_count\":${_CONST_CLEARED_COUNT},\"constitution\":\"$(basename "$_CONSTITUTION_FILE")\""
        else
          echo "  [startup] constitution.md hash recorded (first run)"
        fi
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
echo "  ║  Phase models: R=$SPIRAL_RESEARCH_MODEL  S=$SPIRAL_VALIDATION_MODEL  M=$SPIRAL_MERGE_MODEL"
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
[[ "${SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE:-true}" == "false" ]] &&
  echo "  ║  Cache inv.:  disabled (SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE=false)"
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
[[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]] && echo "  ║  Cache TTL:   ${SPIRAL_RESEARCH_CACHE_TTL_HOURS}h (research URL responses + Phase R output reuse)"
echo "  ║  Capacity:    Phase R skipped when pending > $CAPACITY_LIMIT"
echo "  ║  Scratch:     $SCRATCH_DIR"
echo "  ╚══════════════════════════════════════════════╝"
echo ""

# ── Register with SPIRAL UI and open dashboard ────────────────────────────────
_SPIRAL_UI_PORT="${SPIRAL_UI_PORT:-5299}"
_UI_PROJECT_NAME=$("$JQ" -r '.productName // empty' "$PRD_FILE" 2>/dev/null || true)
if [[ -z "$_UI_PROJECT_NAME" ]]; then
  _UI_PROJECT_NAME=$(basename "$REPO_ROOT" | tr '[:upper:]' '[:lower:]' | tr ' ' '-')
fi
_UI_BASE="http://localhost:${_SPIRAL_UI_PORT}"
_UI_DASH="${_UI_BASE}/${_UI_PROJECT_NAME}"

# Register project with UI server (non-blocking; UI may not be running — ignore errors)
if command -v curl &>/dev/null; then
  curl -sf -X POST "${_UI_BASE}/api/register-project" \
    -H "Content-Type: application/json" \
    -d "{\"name\":\"${_UI_PROJECT_NAME}\",\"root\":\"${REPO_ROOT}\"}" \
    >/dev/null 2>&1 || true
fi

# Open browser to project dashboard
echo "  [UI] Dashboard: ${_UI_DASH}"
if command -v cmd.exe &>/dev/null; then
  cmd.exe /c start "" "${_UI_DASH}" 2>/dev/null || true
elif command -v xdg-open &>/dev/null; then
  xdg-open "${_UI_DASH}" 2>/dev/null &
elif command -v open &>/dev/null; then
  open "${_UI_DASH}" 2>/dev/null || true
fi

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


#!/usr/bin/env bash
# lib/startup_checks.sh — SPIRAL startup checks
#
# Functions: run_startup_checks
# Performs: memory check + worker auto-reduction, dirty worktree detection/reset,
#           worktree prune audit, constitution cache invalidation.
#
# Globals read: RALPH_WORKERS, REPO_ROOT, SCRATCH_DIR, RESEARCH_CACHE_DIR,
#               SPIRAL_PYTHON, SPIRAL_SPECKIT_CONSTITUTION,
#               SPIRAL_INVALIDATE_CACHE_ON_CONSTITUTION_CHANGE
# Globals modified: RALPH_WORKERS (may be auto-reduced)

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_startup_checks() {
  # ── Pre-flight memory check — auto-adjust workers if RAM is low ────────
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

  # ── Detect and reset dirty worker worktrees (US-218, US-247) ────────────
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

  # ── US-370: Worktree prune audit at startup ────────────────────────────
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

  # ── US-302: Research cache invalidation on constitution.md change ──────
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
            echo "  [startup] Old: ${_OLD_CONST_HASH:0:16}... → New: ${_NEW_CONST_HASH:0:16}..."
            log_spiral_event "research_cache_invalidated" \
              "\"old_hash\":\"$_OLD_CONST_HASH\",\"new_hash\":\"$_NEW_CONST_HASH\",\"cleared_count\":${_CONST_CLEARED_COUNT},\"constitution\":\"$(basename "$_CONSTITUTION_FILE")\""
          else
            echo "  [startup] constitution.md hash recorded (first run)"
          fi
        fi
      fi
    fi
  fi
}

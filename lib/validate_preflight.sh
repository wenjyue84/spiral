#!/bin/bash
# SPIRAL — Pre-flight Validation
# Source this file in spiral.sh, then call spiral_preflight_check.
# Validates prd.json schema, checkpoint integrity, and config sanity before main loop.

spiral_preflight_check() {
  local prd_file="${1:-$PRD_FILE}"
  local scratch_dir="${2:-$SCRATCH_DIR}"
  local exit_on_fail=1

  echo "  [preflight] Validating prd.json schema..."
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd_file" --quiet
  local schema_rc=$?
  if [[ "$schema_rc" -ne 0 ]]; then
    echo "  [preflight] FATAL: prd.json schema validation failed — aborting (exit $schema_rc)"
    exit "$schema_rc"
  fi
  echo "  [preflight] prd.json schema: OK"

  # ── UTF-8 / control-character encoding check ────────────────────────────────
  local sanitize_flag=""
  if [[ "${SPIRAL_SANITIZE_PRD:-}" == "true" ]]; then
    sanitize_flag="--sanitize"
  fi
  local enc_out enc_rc
  enc_out=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/check_prd_encoding.py" "$prd_file" --quiet ${sanitize_flag} 2>&1)
  enc_rc=$?
  if [[ -n "$enc_out" ]]; then
    echo "$enc_out"
  fi
  if [[ "$enc_rc" -ne 0 ]]; then
    echo "  [preflight] FATAL: prd.json encoding check failed — aborting (exit $enc_rc)"
    exit "$enc_rc"
  fi

  # ── Checkpoint validation ──────────────────────────────────────────────────
  local ckpt="$scratch_dir/_checkpoint.json"
  if [[ -f "$ckpt" ]]; then
    echo "  [preflight] Validating checkpoint..."
    # Check it's valid JSON with required fields
    if ! "$JQ" -e '.iter and .phase and .ts' "$ckpt" >/dev/null 2>&1; then
      echo "  [preflight] WARNING: Corrupt checkpoint — removing $ckpt"
      rm -f "$ckpt"
    else
      local ckpt_phase
      ckpt_phase=$("$JQ" -r '.phase' "$ckpt")
      case "$ckpt_phase" in
        R | T | M | G | I | V | C) ;;
        *)
          echo "  [preflight] WARNING: Invalid checkpoint phase '$ckpt_phase' — removing"
          rm -f "$ckpt"
          ;;
      esac
    fi
  fi

  # ── Config validation (if spiral.config.sh vars are already sourced) ───────
  if [[ -n "${SPIRAL_MODEL_ROUTING:-}" ]]; then
    case "$SPIRAL_MODEL_ROUTING" in
      auto | haiku | sonnet | opus) ;;
      *)
        echo "  [preflight] WARNING: Unknown SPIRAL_MODEL_ROUTING='$SPIRAL_MODEL_ROUTING' (expected: auto|haiku|sonnet|opus)"
        ;;
    esac
  fi

  if [[ -n "${MAX_RETRIES:-}" ]]; then
    if ! [[ "$MAX_RETRIES" =~ ^[1-9][0-9]*$ ]]; then
      echo "  [preflight] WARNING: MAX_RETRIES='$MAX_RETRIES' is not a positive integer"
    fi
  fi

  if [[ -n "${SPIRAL_MAX_PENDING:-}" ]] && [[ "$SPIRAL_MAX_PENDING" != "0" ]]; then
    if ! [[ "$SPIRAL_MAX_PENDING" =~ ^[0-9]+$ ]]; then
      echo "  [preflight] WARNING: SPIRAL_MAX_PENDING='$SPIRAL_MAX_PENDING' is not a non-negative integer"
    fi
  fi

  # ── Story count health check ────────────────────────────────────────────────
  local max_stories="${SPIRAL_MAX_STORIES:-100}"
  local abort_on_excess="${SPIRAL_MAX_STORIES_ABORT:-0}"
  local story_count
  story_count=$("$JQ" '.userStories | length' "$prd_file" 2>/dev/null || echo "0")
  if [[ "$story_count" -gt "$max_stories" ]]; then
    echo "  [preflight] WARNING: prd.json has $story_count stories (threshold: $max_stories)."
    echo "  [preflight]   Run: bash spiral.sh --archive-done"
    echo "  [preflight]   This moves completed stories to prd-archive.json, keeping prd.json lean."
    if [[ "${abort_on_excess}" != "0" ]]; then
      echo "  [preflight] FATAL: SPIRAL_MAX_STORIES_ABORT is set — aborting due to story count ($story_count > $max_stories)"
      exit 1
    fi
  fi

  # ── Duplicate story ID check (US-180) ──────────────────────────────────────
  local dedup_mode="${SPIRAL_DEDUP_IDS:-strict}"
  local dup_ids
  dup_ids=$("$JQ" -r '[.userStories | group_by(.id)[] | select(length > 1) | .[0].id] | join(" ")' "$prd_file" 2>/dev/null || echo "")
  if [[ -n "$dup_ids" ]]; then
    if [[ "$dedup_mode" == "lenient" ]]; then
      echo "  [preflight] WARNING: Duplicate story IDs found: $dup_ids"
      echo "  [preflight]   Lenient mode: keeping passes:true entry, dropping duplicates..."
      local _dup_tmp
      _dup_tmp=$(mktemp)
      "$JQ" '.userStories |= (group_by(.id) | map((map(select(.passes == true)) | first) // first))' \
        "$prd_file" > "$_dup_tmp" && mv "$_dup_tmp" "$prd_file"
      printf '{"ts":"%s","event":"duplicate_ids_deduped","ids":"%s","mode":"lenient"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$dup_ids" \
        >> "${scratch_dir}/spiral_events.jsonl" 2>/dev/null || true
      echo "  [preflight] Duplicate IDs resolved (lenient)."
    else
      echo "  [preflight] FATAL: Duplicate story IDs detected — aborting."
      echo "  [preflight]   Duplicates: $dup_ids"
      echo "  [preflight]   Run with SPIRAL_DEDUP_IDS=lenient to auto-deduplicate."
      printf '{"ts":"%s","event":"duplicate_ids_fatal","ids":"%s","mode":"strict"}\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$dup_ids" \
        >> "${scratch_dir}/spiral_events.jsonl" 2>/dev/null || true
      exit 1
    fi
  fi

  # ── Acceptance-criteria lint (US-209) ──────────────────────────────────────
  local _lint_rc
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_lint.py" "$prd_file" \
    --events-file "${scratch_dir}/spiral_events.jsonl"
  _lint_rc=$?
  if [[ "$_lint_rc" -ne 0 ]]; then
    echo "  [preflight] FATAL: prd-lint failed (SPIRAL_STRICT_AC=true) — aborting"
    exit 1
  fi

  # ── ShellCheck (informational only) ────────────────────────────────────────
  if command -v shellcheck >/dev/null 2>&1; then
    local sc_errors=0
    for script in "$SPIRAL_HOME/spiral.sh" "$SPIRAL_HOME/ralph/ralph.sh"; do
      if [[ -f "$script" ]]; then
        local count
        count=$(shellcheck -S error "$script" 2>&1 | grep -c "^In " || true)
        if [[ "$count" -gt 0 ]]; then
          echo "  [preflight] ShellCheck: $count error-level issue(s) in $(basename "$script") (non-blocking)"
          sc_errors=$((sc_errors + count))
        fi
      fi
    done
    if [[ "$sc_errors" -eq 0 ]]; then
      echo "  [preflight] ShellCheck: clean"
    fi
  fi

  # ── Claude API reachability probe (US-179) ─────────────────────────────────
  if [[ "${DRY_RUN:-0}" -eq 1 ]]; then
    echo "  [preflight] Skipping Claude API check (--dry-run mode)"
  elif [[ "${SPIRAL_SKIP_API_CHECK:-}" == "true" ]]; then
    echo "  [preflight] Skipping Claude API check (SPIRAL_SKIP_API_CHECK=true)"
  elif [[ -z "${ANTHROPIC_API_KEY:-}" ]] && command -v claude &>/dev/null; then
    # Claude Code users: the claude CLI handles auth — no API key needed
    echo "  [preflight] Claude API check: using claude CLI auth (Claude Code mode)"
  else
    if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
      echo "  [preflight] FATAL: ANTHROPIC_API_KEY is not set and claude CLI not found"
      echo "  [preflight]   → If using Claude Code: install claude CLI and log in"
      echo "  [preflight]   → If using API directly: export ANTHROPIC_API_KEY=<your-key>"
      echo "  [preflight]   → Skip this check: export SPIRAL_SKIP_API_CHECK=true"
      exit "${ERR_API_DOWN:-14}"
    fi
    local _api_probe_ok=0
    if curl -sf --connect-timeout 5 --max-time 5 \
        -H "x-api-key: ${ANTHROPIC_API_KEY}" \
        -H "anthropic-version: 2023-06-01" \
        "https://api.anthropic.com/v1/models" >/dev/null 2>&1; then
      _api_probe_ok=1
    fi
    if [[ "$_api_probe_ok" -eq 1 ]]; then
      echo "  [preflight] Claude API reachable: OK"
    else
      echo "  [preflight] FATAL: Claude API not reachable (5-second probe failed)"
      echo "  [preflight]   Set SPIRAL_SKIP_API_CHECK=true to skip this check"
      exit "${ERR_API_DOWN:-14}"
    fi
  fi

  # ── Git author identity (US-211) ──────────────────────────────────────────
  local _git_name _git_email

  # If SPIRAL_GIT_AUTHOR is set, parse it and auto-configure git identity.
  if [[ -n "${SPIRAL_GIT_AUTHOR:-}" ]]; then
    _git_name="${SPIRAL_GIT_AUTHOR%%<*}"
    _git_name="${_git_name%% }"   # strip trailing space
    _git_email="${SPIRAL_GIT_AUTHOR#*<}"
    _git_email="${_git_email%>*}"
    if [[ -n "$_git_name" && -n "$_git_email" ]]; then
      git config user.name "$_git_name" 2>/dev/null || true
      git config user.email "$_git_email" 2>/dev/null || true
      echo "  [preflight] git identity set from SPIRAL_GIT_AUTHOR: $_git_name <$_git_email>"
    else
      echo "  [preflight] WARNING: SPIRAL_GIT_AUTHOR='${SPIRAL_GIT_AUTHOR}' could not be parsed — expected: 'Name <email>'"
    fi
  fi

  _git_name=$(git config user.name 2>/dev/null || true)
  _git_email=$(git config user.email 2>/dev/null || true)

  if [[ -z "$_git_name" || -z "$_git_email" ]]; then
    local _missing=""
    [[ -z "$_git_name" ]]  && _missing+=" user.name"
    [[ -z "$_git_email" ]] && _missing+=" user.email"
    echo "  [preflight] FATAL: git identity not configured (missing:${_missing})"
    echo "  [preflight]   → Fix: git config --global user.name  \"Your Name\""
    echo "  [preflight]   → Fix: git config --global user.email \"you@example.com\""
    echo "  [preflight]   → Alt: set SPIRAL_GIT_AUTHOR=\"Your Name <you@example.com>\" to auto-configure"
    printf '{"ts":"%s","event":"preflight_git_author_missing","missing":"%s"}\n' \
      "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${_missing# }" \
      >> "${scratch_dir}/spiral_events.jsonl" 2>/dev/null || true
    exit "${ERR_CONFIG:-3}"
  fi

  echo "  [preflight] git identity: OK ($_git_name <$_git_email>)"

  # ── Stale git lock-file cleanup (US-225) ──────────────────────────────────
  local lock_timeout="${SPIRAL_LOCK_TIMEOUT_MINUTES:-5}"
  if [[ "$lock_timeout" -gt 0 ]] && [[ -d "${REPO_ROOT:-}/.spiral-workers" ]]; then
    _check_stale_worktree_locks "${REPO_ROOT}/.spiral-workers" "${scratch_dir}" "$lock_timeout"
  fi

  echo "  [preflight] All checks passed"
}

# _check_stale_worktree_locks WORKTREE_BASE SCRATCH_DIR LOCK_TIMEOUT_MINUTES
# Scans active worktrees for .git/*.lock files older than LOCK_TIMEOUT_MINUTES.
# Removes stale locks only when no live git process is detected. Emits audit
# events for each removal.
_check_stale_worktree_locks() {
  local worktree_base="${1}"
  local scratch_dir="${2}"
  local lock_timeout="${3:-5}"
  local _locks_removed=0

  [[ -d "$worktree_base" ]] || return 0

  for wt in "$worktree_base"/worker-*; do
    [[ -d "$wt" ]] || continue
    local wt_git_dir="$wt/.git"

    # .git may be a gitdir pointer file (worktree mode)
    if [[ -f "$wt/.git" ]]; then
      wt_git_dir=$(sed 's/^gitdir: //' "$wt/.git" 2>/dev/null || true)
      [[ -n "$wt_git_dir" ]] || continue
    fi

    [[ -d "$wt_git_dir" ]] || continue

    while IFS= read -r -d '' lock_file; do
      # Get lock file age in minutes via Python (portable across platforms)
      # Convert MSYS path to Windows path on win32 so Python can resolve it
      local age_mins _lf_win
      _lf_win="$(cygpath -w "$lock_file" 2>/dev/null || echo "$lock_file")"
      age_mins=$(python3 -c "
import os, time
try:
    s = os.stat(r'''${_lf_win}''')
    print(int((time.time() - s.st_mtime) / 60))
except Exception:
    print(-1)
" 2>/dev/null || echo "-1")

      if [[ "$age_mins" -lt 0 ]]; then
        continue  # stat failed; skip
      fi

      if [[ "$age_mins" -lt "$lock_timeout" ]]; then
        # Lock is fresh — could belong to an active git operation; leave it
        continue
      fi

      # Check for any live git process as a safety guard before removal.
      # This is a coarse check: if any git process is running on this host,
      # we skip removal to avoid interfering with it. On a single-host CI
      # runner this is equivalent to lsof-based ownership verification.
      local live_git_count
      live_git_count=$(ps aux 2>/dev/null | grep -i "[g]it" | grep -cv "grep" || echo "0")

      if [[ "$live_git_count" -gt 0 ]]; then
        echo "  [preflight] Stale lock detected (${age_mins}m old) but live git process found — skipping: $lock_file"
        continue
      fi

      # Safe to remove: lock is stale and no git process is running
      if rm -f "$lock_file" 2>/dev/null; then
        echo "  [preflight] Removed stale git lock (${age_mins}m old): $lock_file"
        printf '{"ts":"%s","event":"stale_lock_removed","file":"%s","age_minutes":%d}\n' \
          "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$lock_file" "$age_mins" \
          >> "${scratch_dir}/spiral_events.jsonl" 2>/dev/null || true
        _locks_removed=$((_locks_removed + 1))
      fi
    done < <(find "$wt_git_dir" -maxdepth 2 -name "*.lock" -print0 2>/dev/null)
  done

  if [[ "$_locks_removed" -gt 0 ]]; then
    echo "  [preflight] Stale lock cleanup: removed $_locks_removed lock file(s)"
  fi
}

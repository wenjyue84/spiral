#!/usr/bin/env bash
# lib/startup_checks.sh -- Pre-loop startup checks (rerere, log rotation, preflight, etc.)
#
# Extracted from spiral.sh. Sourced after SPIRAL_HOME, SPIRAL_PYTHON, JQ,
# REPO_ROOT, SCRATCH_DIR, CHECKPOINT_FILE, PRD_FILE, log_spiral_event,
# spiral_preflight_check, prune_old_crashes are defined.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

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

  # Only phase is required — storyId/retryCount are set mid-Phase-I only.
  # Discarding checkpoints missing those fields caused every crash-recovery
  # to restart from iter 1 (fix: accept partial checkpoints gracefully).
  phase=$("$JQ" -r '.phase // empty' "$ckpt_file" 2>/dev/null || true)

  if [[ -z "$phase" ]]; then
    echo "  [checkpoint-completeness] INCOMPLETE: phase=✗ (required field missing)"
    return 1
  fi

  # Log optional fields as informational (not blocking)
  story_id=$("$JQ" -r '.storyId // empty' "$ckpt_file" 2>/dev/null || true)
  retry_count=$("$JQ" -r '.retryCount // empty' "$ckpt_file" 2>/dev/null || true)
  if [[ -z "$story_id" || -z "$retry_count" ]]; then
    echo "  [checkpoint-completeness] OK (phase=✓, storyId=$([[ -n "$story_id" ]] && echo "✓" || echo "absent"), retryCount=$([[ -n "$retry_count" ]] && echo "✓" || echo "absent")) — resuming"
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

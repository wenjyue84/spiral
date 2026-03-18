#!/usr/bin/env bash
# lib/phases/phase_i_implement.sh — Phase G+I: HUMAN GATE + IMPLEMENT
#
# Orchestrates the human gate and implementation sub-pipeline.
#
# Phase G: prompts user to proceed/skip/quit
# Phase I: runs ralph workers to implement pending stories
#
# Inputs:
#   $PRD_FILE, $RALPH_WORKERS, $RALPH_MAX_ITERS, $SPIRAL_STORY_BATCH_SIZE
#
# Outputs:
#   $PRD_FILE (stories marked passes: true on success)
#   progress.txt (learning log appended by each ralph invocation)
#
# Config vars:
#   SPIRAL_IMPL_TIMEOUT      — seconds per ralph call (default: 600)
#   RALPH_WORKERS            — parallel worker count (default: 1)
#   SPIRAL_LOW_POWER_MODE    — auto-reduce workers under memory pressure
#   SPIRAL_STORY_BATCH_SIZE  — max stories per batch (0 = all)

source "$(dirname "${BASH_SOURCE[0]}")/../impl/decompose.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../impl/retry.sh"
source "$(dirname "${BASH_SOURCE[0]}")/../impl/commit_revert.sh"

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_gate_and_implement() {
  # ── Phase G: HUMAN GATE + Phase I: IMPLEMENT ───────────────────────────────
  PHASE="G"
  write_active_status "G" 50 # US-311
  log_spiral_event "phase_start" "\"phase\":\"G\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "G" "start"
  _PHASE_TS_I=$(date +%s)
  run_phase_hook PRE "G" || return 1
  if checkpoint_phase_done "I"; then
    echo "  [G+I] Skipping (checkpoint: gate and ralph already done this iter)"
  else
    prd_stats

    # ── Generate story review report for human gate (skip in auto-proceed mode) ──
    GATE_REPORTS_DIR="$SCRATCH_DIR/gate-reports"
    if [[ "$GATE_DEFAULT" != "proceed" ]]; then
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/story_review_report.py" \
        --prd "$PRD_FILE" \
        --iter "$SPIRAL_ITER" \
        --added "$ADDED" \
        --output "$GATE_REPORTS_DIR" \
        --open 2>/dev/null || true
    fi

    # ── US-262: SAST gate check (Semgrep scan on changed files) ──────────────
    _SAST_BLOCKED=0
    run_sast_gate_check || _SAST_BLOCKED=1
    if [[ "$_SAST_BLOCKED" -eq 1 ]]; then
      echo "  [SAST] Gate blocked — HIGH/CRITICAL findings detected. Review: $GATE_REPORTS_DIR/*_sast.json"
      log_spiral_event "sast_gate_blocked" "\"iteration\":$SPIRAL_ITER"
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
        "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/route_stories.py" --prd "$PRD_FILE" --profile "$SPIRAL_MODEL_ROUTING"

        # ── DAG cycle detection ──────────────────────────────────────────
        DAG_SKIP_IMPL=0
        DAG_OUTPUT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/check_dag.py" "$PRD_FILE" 2>&1) || {
          echo "  [Phase I] WARNING: Dependency cycle detected — skipping implementation" >&2
          echo "$DAG_OUTPUT" >&2
          DAG_SKIP_IMPL=1
        }

        # ── Phase I: IMPLEMENT (Ralph) ──────────────────────────────────
        PHASE="I"
        _ACTIVE_STORY_ID=""
        _ACTIVE_STORY_TITLE=""     # US-311: reset story context
        write_active_status "I" 60 # US-311
        log_spiral_event "phase_start" "\"phase\":\"I\",\"iteration\":$SPIRAL_ITER"
        notify_webhook "I" "start"
        echo ""
        run_phase_hook PRE "I" || return 1

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
            _REC_OUTPUT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/recommend_workers.py" "$PRD_FILE" 2>/dev/null) || true
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

          # ── Export per-story test baseline command for ralph ─────────────────
          export SPIRAL_TEST_BASELINE_CMD="${SPIRAL_VALIDATE_CMD:-}"

          print_phase_banner "I" "IMPLEMENT — running ralph ($RALPH_MAX_ITERS inner iterations)..."

          # ── US-362: Prune old invocation snapshots ────────────────────────
          if [[ "${SPIRAL_SNAPSHOT_RETENTION:-7}" -gt 0 ]]; then
            _SNAP_PRUNED=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/resilience/invocation_snapshot.py" prune "$SCRATCH_DIR" \
              --iteration "$SPIRAL_ITER" --retention "${SPIRAL_SNAPSHOT_RETENTION:-7}" 2>/dev/null || echo "0")
            [[ "${_SNAP_PRUNED:-0}" -gt 0 ]] && echo "  [I] Pruned $_SNAP_PRUNED old invocation snapshot(s)"
          fi

          # ── Batch slicing: cap stories visible to ralph ──────────────────
          _BATCH_ACTIVE=0
          _FULL_PRD_BACKUP="$SCRATCH_DIR/_full_prd_backup.json"
          if [[ "$SPIRAL_STORY_BATCH_SIZE" -gt 0 && "$PENDING" -gt "$SPIRAL_STORY_BATCH_SIZE" ]]; then
            cp "$PRD_FILE" "$_FULL_PRD_BACKUP"
            "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/slice_prd.py" slice \
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

          # Note: model is now assigned per-story by lib/routing/route_stories.py

          # Build --dry-run flag for ralph invocations
          _DRY_RUN_FLAG=""
          [[ "$DRY_RUN" -eq 1 ]] && _DRY_RUN_FLAG="--dry-run"

          # ── US-177: Dirty working tree guard ─────────────────────────────
          _AUTO_STASH_REF=""
          _DIRTY_SKIP_RALPH=0
          _DIRTY_FILES=$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null || true)
          if [[ -n "$_DIRTY_FILES" ]]; then
            if [[ "$SPIRAL_AUTO_STASH" == "true" ]]; then
              _STASH_MSG="spiral-auto-stash-iter-${SPIRAL_ITER}"
              echo "  [Phase I] Dirty working tree detected — auto-stashing (iter ${SPIRAL_ITER})..."
              if git -C "$REPO_ROOT" stash push --include-untracked -m "$_STASH_MSG" 2>/dev/null; then
                _AUTO_STASH_REF=$(git -C "$REPO_ROOT" stash list --format="%gd %gs" 2>/dev/null |
                  grep "$_STASH_MSG" | head -1 | awk '{print $1}')
                echo "  [Phase I] Stash created: ${_AUTO_STASH_REF:-stash@{0}}"
              else
                echo "  [Phase I] WARNING: Auto-stash failed — proceeding with dirty tree"
              fi
            else
              echo ""
              echo "  ╔══════════════════════════════════════════════════════════════╗"
              echo "  ║  [Phase I] SKIPPED — uncommitted changes detected            ║"
              echo "  ║                                                              ║"
              echo "  ║  Phase I requires a clean working tree to avoid git errors. ║"
              echo "  ║  Options:                                                    ║"
              echo "  ║    1. Commit or stash your changes, then re-run              ║"
              echo "  ║    2. Set SPIRAL_AUTO_STASH=true to stash automatically      ║"
              echo "  ╚══════════════════════════════════════════════════════════════╝"
              echo ""
              echo "  Dirty files:"
              echo "$_DIRTY_FILES" | head -10 | sed 's/^/    /'
              log_spiral_event "phase_skip" "\"phase\":\"I\",\"iteration\":$SPIRAL_ITER,\"reason\":\"dirty_working_tree\""
              _DIRTY_SKIP_RALPH=1
            fi
          fi
          # ── End dirty working tree guard ─────────────────────────────────

          if [[ "$_DIRTY_SKIP_RALPH" -eq 0 ]]; then
            RALPH_RAN=1
            PRE_RALPH_PRD_JSON=$(cat "$PRD_FILE")
            DONE_BEFORE=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")
            _PASSES_BEFORE_I="$DONE_BEFORE"

            if [[ "$RALPH_WORKERS" -gt 1 ]]; then
              # ── Parallel mode with wave dispatch ───────────────────────────────
              # US-246: Shared-fetch optimization — single coordinated fetch in main repo
              # All worktrees share one object database, so one fetch satisfies all workers
              echo "  [I] US-246: Performing shared git fetch (one fetch for all $RALPH_WORKERS workers)..."
              _FETCH_START=$(date +%s%N)
              if git -C "$REPO_ROOT" fetch origin 2>&1 | grep -q "fetch\|Already"; then
                _FETCH_ELAPSED=$((($(date +%s%N) - _FETCH_START) / 1000000))
                _FETCH_SECS=$(echo "scale=2; $_FETCH_ELAPSED / 1000" | bc 2>/dev/null || echo "$_FETCH_ELAPSED")
                _ESTIMATED_PER_WORKER_TOTAL=$((${_FETCH_ELAPSED} * ${RALPH_WORKERS} / 1000))
                echo "  [I]   Shared fetch completed in ${_FETCH_SECS}ms (vs estimated ${_ESTIMATED_PER_WORKER_TOTAL}ms if per-worker)"
                printf '{"ts":"%s","event":"shared_fetch_completed","run_id":"%s","shared_fetch_ms":%d,"workers":%d,"estimated_per_worker_total_ms":%d}\n' \
                  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${SPIRAL_RUN_ID:-}" "${_FETCH_ELAPSED}" "$RALPH_WORKERS" "$_ESTIMATED_PER_WORKER_TOTAL" \
                  >>"$SCRATCH_DIR/spiral_events.jsonl" 2>/dev/null || true
              else
                echo "  [I]   Shared fetch skipped (no remote updates needed)"
                printf '{"ts":"%s","event":"shared_fetch_skipped","run_id":"%s","reason":"no_updates","workers":%d}\n' \
                  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${SPIRAL_RUN_ID:-}" "$RALPH_WORKERS" \
                  >>"$SCRATCH_DIR/spiral_events.jsonl" 2>/dev/null || true
              fi

              # Pre-populate filesTouch hints from git history (best-effort)
              "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research/populate_hints.py" \
                --prd "$PRD_FILE" --repo-root "$REPO_ROOT" 2>/dev/null || true

              if [[ -n "$SPIRAL_CORE_BIN" ]]; then
                _PARTITION_CMD=("$SPIRAL_CORE_BIN" partition)
              else
                _PARTITION_CMD=("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/partition_prd.py")
              fi
              TOTAL_WAVES=$("${_PARTITION_CMD[@]}" \
                --prd "$PRD_FILE" --list-waves 2>/dev/null || echo "1")
              echo "  [I] Parallel mode: $RALPH_WORKERS workers, $TOTAL_WAVES wave(s)"

              # ── US-322: Cascade fan-out counter (reset per Phase I) ──────────
              _CASCADE_FAIL_COUNT=0
              _CASCADE_FAIL_IDS=""

              WAVE=0
              while true; do
                # Get story count for this wave level (recomputed from current prd.json)
                WAVE_STORY_COUNT=$("${_PARTITION_CMD[@]}" \
                  --prd "$PRD_FILE" --wave-count "$WAVE" 2>/dev/null || echo "0")

                # No stories at this level — check if higher levels exist
                if [[ "$WAVE_STORY_COUNT" -eq 0 ]]; then
                  REMAINING=$("${_PARTITION_CMD[@]}" \
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
                  _NEXT_SID=$("$JQ" -r '[.userStories[] | select(.passes != true)] | sort_by(if .priorityScore != null then (100 - .priorityScore) elif .priority == "critical" then 20 elif .priority == "high" then 40 elif .priority == "medium" then 60 else 80 end) | first | .id // ""' "$PRD_FILE" 2>/dev/null || echo "")
                  if [[ "$_NEXT_SID" == UT-* ]]; then
                    _RALPH_TOOL="codex"
                    echo "  [I] Story $_NEXT_SID is a test story → routing to Codex"
                  else
                    _RALPH_TOOL="claude"
                  fi
                  # US-311: update active status with story context
                  if [[ -n "$_NEXT_SID" ]]; then
                    _ACTIVE_STORY_ID="$_NEXT_SID"
                    _ACTIVE_STORY_TITLE=$("$JQ" -r --arg id "$_NEXT_SID" '.userStories[] | select(.id == $id) | .title // ""' "$PRD_FILE" 2>/dev/null || echo "")
                    write_active_status "I" 60
                  fi
                  # US-325: Idempotency guard — skip if matching commit already exists
                  if [[ -n "$_NEXT_SID" ]] && check_idempotency_guard "$_NEXT_SID" "$PRD_FILE"; then
                    WAVE=$((WAVE + 1))
                    continue
                  fi
                  # US-219: begin story task span; prints story-scoped TRACEPARENT for child action spans
                  _STORY_TP=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" begin-story \
                    --story-id "$_NEXT_SID" --scratch-dir "$SCRATCH_DIR" 2>/dev/null || true)
                  # US-362: Write pre-invocation snapshot for post-mortem replay
                  _SNAP_STORY_TMP=$(mktemp -p "$SCRATCH_DIR" _snap_story_XXXXXX.json 2>/dev/null || echo "$SCRATCH_DIR/_snap_story_$$.json")
                  "$JQ" --arg id "$_NEXT_SID" '.userStories[] | select(.id == $id)' "$PRD_FILE" >"$_SNAP_STORY_TMP" 2>/dev/null || true
                  _SNAP_RALPH_FLAGS="$RALPH_MAX_ITERS --prd $PRD_FILE --tool $_RALPH_TOOL $_DRY_RUN_FLAG"
                  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/resilience/invocation_snapshot.py" write "$SCRATCH_DIR" \
                    --story-id "$_NEXT_SID" \
                    --story-json "$_SNAP_STORY_TMP" \
                    --model "${EFFECTIVE_MODEL:-unknown}" \
                    --ralph-flags "$_SNAP_RALPH_FLAGS" \
                    --iteration "$SPIRAL_ITER" \
                    --phase "I" 2>/dev/null || true
                  rm -f "$_SNAP_STORY_TMP" 2>/dev/null || true
                  _I_EXIT=0
                  _I_START=$(date +%s)
                  _STORY_BUDGET=$(get_story_timeout "$_NEXT_SID")
                  _I_STDOUT_FILE=$(mktemp -p "$SCRATCH_DIR" _ralph_out_XXXXXX.log 2>/dev/null || echo "$SCRATCH_DIR/_ralph_out_$$.log")
                  if [[ "${_STORY_BUDGET:-0}" -gt 0 ]] && command -v timeout &>/dev/null; then
                    echo "  [I] Budget: ${_STORY_BUDGET}s for $_NEXT_SID"
                    timeout --kill-after=30 "${_STORY_BUDGET}" bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" $_DRY_RUN_FLAG 2>&1 | tee "$_I_STDOUT_FILE" || _I_EXIT=$?
                  else
                    bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" $_DRY_RUN_FLAG 2>&1 | tee "$_I_STDOUT_FILE" || _I_EXIT=$?
                  fi
                  _I_ELAPSED=$(($(date +%s) - _I_START))
                  # US-362: Finish snapshot with returncode and stdout head
                  _SNAP_STDOUT_HEAD=$(head -c 2000 "$_I_STDOUT_FILE" 2>/dev/null || true)
                  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/resilience/invocation_snapshot.py" finish "$SCRATCH_DIR" \
                    --story-id "$_NEXT_SID" \
                    --returncode "$_I_EXIT" \
                    --stdout-head "${_SNAP_STDOUT_HEAD:-}" 2>/dev/null || true
                  rm -f "$_I_STDOUT_FILE" 2>/dev/null || true
                  if [[ "$_I_EXIT" -eq 124 ]]; then
                    echo "  [I] WARNING: Ralph timed out after ${_I_ELAPSED}s (budget: ${_STORY_BUDGET}s)"
                    log_spiral_event "phase_timeout" "\"phase\":\"I\",\"story_id\":\"$_NEXT_SID\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_I_ELAPSED * 1000)),\"timeout_s\":${_STORY_BUDGET}"
                  fi
                  # US-219: emit action span for the LLM implementation call
                  STORY_TRACEPARENT="$_STORY_TP" "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" emit-action \
                    --type llm_query --duration-s "$_I_ELAPSED" --story-id "$_NEXT_SID" 2>/dev/null || true
                  # US-219: close story task span with pass/fail
                  _STORY_PASSES=$("$JQ" -r --arg id "$_NEXT_SID" \
                    '.userStories[] | select(.id == $id) | .passes // false' "$PRD_FILE" 2>/dev/null || echo "false")
                  _STORY_STATUS="failed"
                  [[ "$_STORY_PASSES" == "true" ]] && _STORY_STATUS="passed"
                  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-story \
                    --story-id "$_NEXT_SID" --status "$_STORY_STATUS" --scratch-dir "$SCRATCH_DIR" 2>/dev/null || true
                  # US-318/US-341: emit invoke_agent span for worker lifecycle with cache token attributes
                  _IA_CACHE_READ=$(awk -F'\t' -v sid="$_NEXT_SID" '$4 == sid { cr=$13 } END { print cr+0 }' "$RESULTS_FILE" 2>/dev/null || echo 0)
                  _IA_CACHE_CREATE=$(awk -F'\t' -v sid="$_NEXT_SID" '$4 == sid { cc=$14 } END { print cc+0 }' "$RESULTS_FILE" 2>/dev/null || echo 0)
                  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" invoke-agent \
                    --story-id "$_NEXT_SID" --worker-id "0" \
                    --duration-s "$_I_ELAPSED" --status "$_STORY_STATUS" \
                    --agent-version "${SPIRAL_VERSION:-unknown}" \
                    --conversation-id "${SPIRAL_RUN_ID:-}" \
                    --cache-read-tokens "${_IA_CACHE_READ:-0}" \
                    --cache-creation-tokens "${_IA_CACHE_CREATE:-0}" 2>/dev/null || true
                  # US-189: record per-story token metrics after Phase I
                  _TOK_IN=$("$JQ" -r --arg id "$_NEXT_SID" '.[$id].tokens_input // 0' "$SCRATCH_DIR/story_costs.json" 2>/dev/null || echo 0)
                  _TOK_OUT=$("$JQ" -r --arg id "$_NEXT_SID" '.[$id].tokens_output // 0' "$SCRATCH_DIR/story_costs.json" 2>/dev/null || echo 0)
                  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_metrics.py" record-tokens \
                    --story-id "$_NEXT_SID" --phase I \
                    --input-tokens "${_TOK_IN:-0}" --output-tokens "${_TOK_OUT:-0}" \
                    --duration-ms "$((_I_ELAPSED * 1000))" \
                    --scratch-dir "$SCRATCH_DIR" 2>/dev/null || true
                  # US-192: record calibration data (actual vs estimated complexity) if story passed
                  if [[ "$_STORY_PASSES" == "true" ]]; then
                    _EST_COMPLEXITY=$("$JQ" -r --arg id "$_NEXT_SID" '.userStories[] | select(.id == $id) | .estimatedComplexity // "medium"' "$PRD_FILE" 2>/dev/null || echo "medium")
                    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/calibration_tracker.py" record \
                      --story-id "$_NEXT_SID" \
                      --estimated-complexity "$_EST_COMPLEXITY" \
                      --actual-duration-s "$_I_ELAPSED" \
                      --phase-retries 0 \
                      --passed true \
                      --output calibration.jsonl 2>/dev/null || true
                  fi
                  # ── US-353: Store plan in cache on success ──────────────────────
                  if [[ "$_STORY_PASSES" == "true" && "${SPIRAL_PLAN_CACHE_ENABLED:-true}" == "true" ]]; then
                    _PLAN_CACHE_DIR="$SCRATCH_DIR/plan_cache"
                    _STORY_TMP=$(mktemp -p "$SCRATCH_DIR" _story_XXXXXX.json 2>/dev/null || echo "$SCRATCH_DIR/_story_$$.json")
                    "$JQ" --arg id "$_NEXT_SID" '.userStories[] | select(.id == $id)' "$PRD_FILE" >"$_STORY_TMP" 2>/dev/null || true
                    _PLAN_JSON="{\"story_id\":\"$_NEXT_SID\",\"duration_s\":$_I_ELAPSED,\"model\":\"${EFFECTIVE_MODEL:-unknown}\"}"
                    _PLAN_TMP=$(mktemp -p "$SCRATCH_DIR" _plan_XXXXXX.json 2>/dev/null || echo "$SCRATCH_DIR/_plan_$$.json")
                    printf '%s' "$_PLAN_JSON" >"$_PLAN_TMP"
                    _PC_RESULT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/resilience/plan_cache.py" store "$_PLAN_CACHE_DIR" \
                      --story-json "$_STORY_TMP" --plan-json "$_PLAN_TMP" 2>/dev/null || echo "")
                    if [[ -n "$_PC_RESULT" ]]; then
                      log_spiral_event "plan_cache_store" \
                        "\"story_id\":\"$_NEXT_SID\",\"plan_key\":\"$(basename "$_PC_RESULT" .json)\""
                    fi
                    rm -f "$_STORY_TMP" "$_PLAN_TMP" 2>/dev/null || true
                  fi
                  # ── US-260: Post-Phase-I drift check ──────────────────────────
                  if [[ "${SPIRAL_DRIFT_CHECK:-false}" != "false" && -n "${_NEXT_SID:-}" ]]; then
                    echo "  [drift] Checking implementation drift for $_NEXT_SID..."
                    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/drift_check.py" \
                      --story-id "$_NEXT_SID" \
                      --prd "$PRD_FILE" \
                      --scratch-dir "$SCRATCH_DIR" \
                      --repo-root "$REPO_ROOT" \
                      --pass-threshold "${SPIRAL_DRIFT_PASS_THRESHOLD:-70}" \
                      --fail-threshold "${SPIRAL_DRIFT_FAIL_THRESHOLD:-40}" \
                      --iteration "$SPIRAL_ITER" 2>/dev/null || true
                  fi
                  # ── End drift check ───────────────────────────────────────────
                  # US-194: post-story plugin hooks (e.g. Slack notifications)
                  if [[ -n "${PLUGIN_HOOKS[post-story]:-}" ]]; then
                    _PS_TITLE=$("$JQ" -r --arg id "$_NEXT_SID" '.userStories[] | select(.id == $id) | .title // ""' "$PRD_FILE" 2>/dev/null || echo "")
                    _PS_RETRY=$("$JQ" -r --arg id "$_NEXT_SID" '.[$id] // 0' "$REPO_ROOT/retry-counts.json" 2>/dev/null || echo "0")
                    run_plugin_hooks "post-story" "POST" "$_NEXT_SID" \
                      "\"story_title\":\"${_PS_TITLE//\"/\\\"}\",\"story_passes\":$_STORY_PASSES,\"retry_count\":${_PS_RETRY:-0}" 2>/dev/null || true
                  fi
                  # ── US-322: Update cascade fan-out counter ────────────────────
                  if [[ "$_STORY_PASSES" == "true" ]]; then
                    _CASCADE_FAIL_COUNT=0
                    _CASCADE_FAIL_IDS=""
                  else
                    _CASCADE_FAIL_COUNT=$((_CASCADE_FAIL_COUNT + 1))
                    _CASCADE_FAIL_IDS="${_CASCADE_FAIL_IDS:+$_CASCADE_FAIL_IDS,}$_NEXT_SID"
                    if [[ "${SPIRAL_CASCADE_FAN_OUT_LIMIT:-5}" -gt 0 && "$_CASCADE_FAIL_COUNT" -ge "${SPIRAL_CASCADE_FAN_OUT_LIMIT:-5}" ]]; then
                      echo ""
                      echo "  ╔══════════════════════════════════════════════════════════════╗"
                      echo "  ║  CASCADE ABORT — $_CASCADE_FAIL_COUNT consecutive story failures        ║"
                      echo "  ║  Failing stories: ${_CASCADE_FAIL_IDS}"
                      echo "  ║  Inspect the first failure and fix the root cause.          ║"
                      echo "  ╚══════════════════════════════════════════════════════════════╝"
                      echo ""
                      log_spiral_event "cascade_abort" \
                        "\"iteration\":$SPIRAL_ITER,\"consecutive_failures\":$_CASCADE_FAIL_COUNT,\"failing_ids\":\"$_CASCADE_FAIL_IDS\",\"limit\":${SPIRAL_CASCADE_FAN_OUT_LIMIT:-5}"
                      rm -f "$CHECKPOINT_FILE"
                      spiral_exit E405 "${SPIRAL_CASCADE_FAN_OUT_LIMIT:-5}"
                    fi
                  fi
                else
                  # Cap workers to story count so no worker sits idle
                  WAVE_WORKERS="$RALPH_WORKERS"
                  if [[ "$WAVE_STORY_COUNT" -lt "$RALPH_WORKERS" ]]; then
                    WAVE_WORKERS="$WAVE_STORY_COUNT"
                    echo "  [I] Wave $((WAVE + 1)): capping to $WAVE_WORKERS workers (only $WAVE_STORY_COUNT stories)"
                  fi

                  # ── Pre-flight: cross-story conflict detection (US-186) ─────────
                  # Before launching workers, detect stories that would produce merge
                  # conflicts and defer lower-priority ones to the next batch.
                  if [[ "${SKIP_CONFLICT_PREFLIGHT:-0}" -ne 1 ]]; then
                    _WAVE_STORY_IDS=($("$JQ" -r \
                      '[.userStories[] | select(.passes != true and ._skipped != true and ._decomposed != true)] | sort_by(if .priorityScore != null then (100 - .priorityScore) elif .priority == "critical" then 20 elif .priority == "high" then 40 elif .priority == "medium" then 60 else 80 end) | .[0:'"$WAVE_STORY_COUNT"'] | .[].id' \
                      "$PRD_FILE" 2>/dev/null || true))
                    if [[ ${#_WAVE_STORY_IDS[@]} -ge 2 ]]; then
                      _CF_LOG="$SCRATCH_DIR/conflict-log.jsonl"
                      _CF_RESULT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/workers/conflict_preflight.py" \
                        --prd "$PRD_FILE" \
                        --story-ids "${_WAVE_STORY_IDS[@]}" \
                        --repo-root "$REPO_ROOT" \
                        --conflict-log "$_CF_LOG" \
                        --batch-number "$((WAVE + 1))" \
                        --update-prd 2>&1) || true
                      _CF_DEFERRED=$(echo "$_CF_RESULT" | "$JQ" -r '.deferred | length' 2>/dev/null || echo "0")
                      if [[ "$_CF_DEFERRED" -gt 0 ]]; then
                        _CF_IDS=$(echo "$_CF_RESULT" | "$JQ" -r '.deferred | join(", ")' 2>/dev/null || echo "")
                        echo "  [conflict-preflight] Deferred $_CF_DEFERRED story/stories to next batch: $_CF_IDS"
                        log_spiral_event "conflict_preflight_deferred" "\"batch\":$((WAVE + 1)),\"deferred\":$_CF_DEFERRED,\"ids\":\"${_CF_IDS}\""
                        # Recompute wave story count after deferral
                        WAVE_STORY_COUNT=$("${_PARTITION_CMD[@]}" \
                          --prd "$PRD_FILE" --wave-count "$WAVE" 2>/dev/null || echo "0")
                        if [[ "$WAVE_STORY_COUNT" -le 1 ]]; then
                          echo "  [I] Wave $((WAVE + 1)): only $WAVE_STORY_COUNT story after deferral — sequential fallback"
                          WAVE=$((WAVE + 1))
                          continue
                        fi
                        # Recompute WAVE_WORKERS after deferral
                        if [[ "$WAVE_STORY_COUNT" -lt "$WAVE_WORKERS" ]]; then
                          WAVE_WORKERS="$WAVE_STORY_COUNT"
                        fi
                      fi
                    fi
                  fi

                  bash "$SPIRAL_HOME/lib/run_parallel_ralph.sh" \
                    "$WAVE_WORKERS" "$RALPH_MAX_ITERS" "$REPO_ROOT" "$PRD_FILE" \
                    "$SCRATCH_DIR" "$SPIRAL_RALPH" "$JQ" "$SPIRAL_PYTHON" \
                    "$MONITOR_TERMINALS" "$SPIRAL_HOME" "" || true
                  # ── US-322: Check cascade fan-out after parallel wave ────────
                  # Count how many stories from this wave passed vs failed
                  _WAVE_PASSED=0
                  _WAVE_FAILED_IDS=""
                  for _WS_ID in "${_WAVE_STORY_IDS[@]:0:$WAVE_WORKERS}"; do
                    [[ -z "$_WS_ID" ]] && continue
                    _WS_PASSES=$("$JQ" -r --arg id "$_WS_ID" \
                      '.userStories[] | select(.id == $id) | .passes // false' "$PRD_FILE" 2>/dev/null || echo "false")
                    if [[ "$_WS_PASSES" == "true" ]]; then
                      _WAVE_PASSED=$((_WAVE_PASSED + 1))
                    else
                      _WAVE_FAILED_IDS="${_WAVE_FAILED_IDS:+$_WAVE_FAILED_IDS,}$_WS_ID"
                    fi
                  done
                  if [[ "$_WAVE_PASSED" -gt 0 ]]; then
                    _CASCADE_FAIL_COUNT=0
                    _CASCADE_FAIL_IDS=""
                  elif [[ -n "$_WAVE_FAILED_IDS" ]]; then
                    # All stories in this wave failed — count them as consecutive
                    IFS=',' read -ra _WF_ARR <<<"$_WAVE_FAILED_IDS"
                    _CASCADE_FAIL_COUNT=$((_CASCADE_FAIL_COUNT + ${#_WF_ARR[@]}))
                    _CASCADE_FAIL_IDS="${_CASCADE_FAIL_IDS:+$_CASCADE_FAIL_IDS,}$_WAVE_FAILED_IDS"
                    if [[ "${SPIRAL_CASCADE_FAN_OUT_LIMIT:-5}" -gt 0 && "$_CASCADE_FAIL_COUNT" -ge "${SPIRAL_CASCADE_FAN_OUT_LIMIT:-5}" ]]; then
                      echo ""
                      echo "  ╔══════════════════════════════════════════════════════════════╗"
                      echo "  ║  CASCADE ABORT — $_CASCADE_FAIL_COUNT consecutive story failures        ║"
                      echo "  ║  Failing stories: ${_CASCADE_FAIL_IDS}"
                      echo "  ║  Inspect the first failure and fix the root cause.          ║"
                      echo "  ╚══════════════════════════════════════════════════════════════╝"
                      echo ""
                      log_spiral_event "cascade_abort" \
                        "\"iteration\":$SPIRAL_ITER,\"consecutive_failures\":$_CASCADE_FAIL_COUNT,\"failing_ids\":\"$_CASCADE_FAIL_IDS\",\"limit\":${SPIRAL_CASCADE_FAN_OUT_LIMIT:-5}"
                      rm -f "$CHECKPOINT_FILE"
                      spiral_exit E405 "${SPIRAL_CASCADE_FAN_OUT_LIMIT:-5}"
                    fi
                  fi
                fi

                WAVE=$((WAVE + 1))
              done
            else
              # ── Sequential mode (default) ────────────────────────────────────
              # Auto-detect tool: UT-* test stories → Codex; others → Claude
              _NEXT_SID=$("$JQ" -r '[.userStories[] | select(.passes != true)] | sort_by(if .priorityScore != null then (100 - .priorityScore) elif .priority == "critical" then 20 elif .priority == "high" then 40 elif .priority == "medium" then 60 else 80 end) | first | .id // ""' "$PRD_FILE" 2>/dev/null || echo "")
              if [[ "$_NEXT_SID" == UT-* ]]; then
                _RALPH_TOOL="codex"
                echo "  [I] Story $_NEXT_SID is a test story → routing to Codex"
              else
                _RALPH_TOOL="claude"
              fi
              # US-311: update active status with story context
              if [[ -n "$_NEXT_SID" ]]; then
                _ACTIVE_STORY_ID="$_NEXT_SID"
                _ACTIVE_STORY_TITLE=$("$JQ" -r --arg id "$_NEXT_SID" '.userStories[] | select(.id == $id) | .title // ""' "$PRD_FILE" 2>/dev/null || echo "")
                write_active_status "I" 60
              fi
              # US-325: Idempotency guard — skip if matching commit already exists
              if [[ -n "$_NEXT_SID" ]] && check_idempotency_guard "$_NEXT_SID" "$PRD_FILE"; then
                # Story already implemented — skip entire sequential ralph invocation
                :
              else
                # US-295: context-window-aware model selection before ralph.sh dispatch
                # Estimate prompt tokens (ralph CLAUDE.md + story JSON) and upgrade model if needed
                RALPH_MODEL_FLAG=""
                if [[ -n "$_NEXT_SID" ]]; then
                  _RALPH_PROMPT_TEXT=""
                  if [[ -f "$SPIRAL_HOME/ralph/CLAUDE.md" ]]; then
                    _RALPH_PROMPT_TEXT+=$(cat "$SPIRAL_HOME/ralph/CLAUDE.md" 2>/dev/null || true)
                  fi
                  _STORY_JSON=$("$JQ" -r --arg id "$_NEXT_SID" '.userStories[] | select(.id == $id)' "$PRD_FILE" 2>/dev/null || echo "")
                  _RALPH_PROMPT_TEXT+="$_STORY_JSON"
                  _PROMPT_TOKEN_EST=$(((${#_RALPH_PROMPT_TEXT} + 3) / 4))
                  _ROUTER_JSON=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/llm_router.py" \
                    --story "$_NEXT_SID" --prd "$PRD_FILE" \
                    --prompt-tokens "$_PROMPT_TOKEN_EST" \
                    --events-file "$SCRATCH_DIR/spiral_events.jsonl" 2>/dev/null || echo "")
                  if [[ -n "$_ROUTER_JSON" ]]; then
                    _CHOSEN_MODEL=$("$JQ" -r '.model // ""' <<<"$_ROUTER_JSON" 2>/dev/null || echo "")
                    _CW_UPGRADED=$("$JQ" -r '.context_window_upgrade // false' <<<"$_ROUTER_JSON" 2>/dev/null || echo "false")
                    if [[ -n "$_CHOSEN_MODEL" ]]; then
                      RALPH_MODEL_FLAG="--model $_CHOSEN_MODEL"
                      if [[ "$_CW_UPGRADED" == "true" ]]; then
                        echo "  [I] Context-window upgrade: $_NEXT_SID → $_CHOSEN_MODEL (est. ${_PROMPT_TOKEN_EST} tokens)"
                      fi
                    fi
                  fi
                fi
                # US-219: begin story task span; prints story-scoped TRACEPARENT for child action spans
                _STORY_TP=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" begin-story \
                  --story-id "$_NEXT_SID" --scratch-dir "$SCRATCH_DIR" 2>/dev/null || true)
                _I_EXIT=0
                _I_START=$(date +%s)
                _STORY_BUDGET=$(get_story_timeout "$_NEXT_SID")
                # US-279: capture stderr to temp file for crash persistence
                _STDERR_CAPTURE=$(mktemp -p "$SCRATCH_DIR" _ralph_stderr_XXXXXX.txt 2>/dev/null || echo "$SCRATCH_DIR/_ralph_stderr_$$.txt")
                if [[ "${_STORY_BUDGET:-0}" -gt 0 ]] && command -v timeout &>/dev/null; then
                  echo "  [I] Budget: ${_STORY_BUDGET}s for $_NEXT_SID"
                  timeout --kill-after=30 "${_STORY_BUDGET}" bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" $RALPH_MODEL_FLAG $_DRY_RUN_FLAG 2>"$_STDERR_CAPTURE" || _I_EXIT=$?
                else
                  bash "$SPIRAL_RALPH" "$RALPH_MAX_ITERS" --prd "$PRD_FILE" --tool "$_RALPH_TOOL" $RALPH_MODEL_FLAG $_DRY_RUN_FLAG 2>"$_STDERR_CAPTURE" || _I_EXIT=$?
                fi
                _I_ELAPSED=$(($(date +%s) - _I_START))
                if [[ "$_I_EXIT" -eq 124 ]]; then
                  echo "  [I] WARNING: Ralph timed out after ${_I_ELAPSED}s (budget: ${_STORY_BUDGET}s) — partial progress saved"
                  log_spiral_event "phase_timeout" "\"phase\":\"I\",\"story_id\":\"$_NEXT_SID\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_I_ELAPSED * 1000)),\"timeout_s\":${_STORY_BUDGET}"
                fi
                # US-279: capture crash traceback on non-zero exit
                if [[ "$_I_EXIT" -ne 0 ]]; then
                  capture_crash "$_NEXT_SID" "$_I_EXIT" "sequential" "$_STDERR_CAPTURE"
                fi
                rm -f "$_STDERR_CAPTURE" 2>/dev/null || true
                # US-219: emit action span for the LLM implementation call
                STORY_TRACEPARENT="$_STORY_TP" "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" emit-action \
                  --type llm_query --duration-s "$_I_ELAPSED" --story-id "$_NEXT_SID" 2>/dev/null || true
                # US-219: close story task span with pass/fail
                _STORY_PASSES=$("$JQ" -r --arg id "$_NEXT_SID" \
                  '.userStories[] | select(.id == $id) | .passes // false' "$PRD_FILE" 2>/dev/null || echo "false")
                _STORY_STATUS="failed"
                [[ "$_STORY_PASSES" == "true" ]] && _STORY_STATUS="passed"
                "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-story \
                  --story-id "$_NEXT_SID" --status "$_STORY_STATUS" --scratch-dir "$SCRATCH_DIR" 2>/dev/null || true
                # US-189: record per-story token metrics after Phase I
                _TOK_IN=$("$JQ" -r --arg id "$_NEXT_SID" '.[$id].tokens_input // 0' "$SCRATCH_DIR/story_costs.json" 2>/dev/null || echo 0)
                _TOK_OUT=$("$JQ" -r --arg id "$_NEXT_SID" '.[$id].tokens_output // 0' "$SCRATCH_DIR/story_costs.json" 2>/dev/null || echo 0)
                "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_metrics.py" record-tokens \
                  --story-id "$_NEXT_SID" --phase I \
                  --input-tokens "${_TOK_IN:-0}" --output-tokens "${_TOK_OUT:-0}" \
                  --duration-ms "$((_I_ELAPSED * 1000))" \
                  --scratch-dir "$SCRATCH_DIR" 2>/dev/null || true
                # US-192: record calibration data (actual vs estimated complexity) if story passed
                if [[ "$_STORY_PASSES" == "true" ]]; then
                  _EST_COMPLEXITY=$("$JQ" -r --arg id "$_NEXT_SID" '.userStories[] | select(.id == $id) | .estimatedComplexity // "medium"' "$PRD_FILE" 2>/dev/null || echo "medium")
                  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/calibration_tracker.py" record \
                    --story-id "$_NEXT_SID" \
                    --estimated-complexity "$_EST_COMPLEXITY" \
                    --actual-duration-s "$_I_ELAPSED" \
                    --phase-retries 0 \
                    --passed true \
                    --output calibration.jsonl 2>/dev/null || true
                fi
                # ── US-353: Store plan in cache on success ──────────────────────
                if [[ "$_STORY_PASSES" == "true" && "${SPIRAL_PLAN_CACHE_ENABLED:-true}" == "true" ]]; then
                  _PLAN_CACHE_DIR="$SCRATCH_DIR/plan_cache"
                  _STORY_TMP=$(mktemp -p "$SCRATCH_DIR" _story_XXXXXX.json 2>/dev/null || echo "$SCRATCH_DIR/_story_$$.json")
                  "$JQ" --arg id "$_NEXT_SID" '.userStories[] | select(.id == $id)' "$PRD_FILE" >"$_STORY_TMP" 2>/dev/null || true
                  _PLAN_JSON="{\"story_id\":\"$_NEXT_SID\",\"duration_s\":$_I_ELAPSED,\"model\":\"${EFFECTIVE_MODEL:-unknown}\"}"
                  _PLAN_TMP=$(mktemp -p "$SCRATCH_DIR" _plan_XXXXXX.json 2>/dev/null || echo "$SCRATCH_DIR/_plan_$$.json")
                  printf '%s' "$_PLAN_JSON" >"$_PLAN_TMP"
                  _PC_RESULT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/resilience/plan_cache.py" store "$_PLAN_CACHE_DIR" \
                    --story-json "$_STORY_TMP" --plan-json "$_PLAN_TMP" 2>/dev/null || echo "")
                  if [[ -n "$_PC_RESULT" ]]; then
                    log_spiral_event "plan_cache_store" \
                      "\"story_id\":\"$_NEXT_SID\",\"plan_key\":\"$(basename "$_PC_RESULT" .json)\""
                  fi
                  rm -f "$_STORY_TMP" "$_PLAN_TMP" 2>/dev/null || true
                fi
                # ── US-260: Post-Phase-I drift check (parallel path) ──────────
                if [[ "${SPIRAL_DRIFT_CHECK:-false}" != "false" && -n "${_NEXT_SID:-}" ]]; then
                  echo "  [drift] Checking implementation drift for $_NEXT_SID..."
                  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/drift_check.py" \
                    --story-id "$_NEXT_SID" \
                    --prd "$PRD_FILE" \
                    --scratch-dir "$SCRATCH_DIR" \
                    --repo-root "$REPO_ROOT" \
                    --pass-threshold "${SPIRAL_DRIFT_PASS_THRESHOLD:-70}" \
                    --fail-threshold "${SPIRAL_DRIFT_FAIL_THRESHOLD:-40}" \
                    --iteration "$SPIRAL_ITER" 2>/dev/null || true
                fi
                # ── End drift check ───────────────────────────────────────────
                # US-194: post-story plugin hooks (e.g. Slack notifications)
                if [[ -n "${PLUGIN_HOOKS[post-story]:-}" ]]; then
                  _PS_TITLE=$("$JQ" -r --arg id "$_NEXT_SID" '.userStories[] | select(.id == $id) | .title // ""' "$PRD_FILE" 2>/dev/null || echo "")
                  _PS_RETRY=$("$JQ" -r --arg id "$_NEXT_SID" '.[$id] // 0' "$REPO_ROOT/retry-counts.json" 2>/dev/null || echo "0")
                  run_plugin_hooks "post-story" "POST" "$_NEXT_SID" \
                    "\"story_title\":\"${_PS_TITLE//\"/\\\"}\",\"story_passes\":$_STORY_PASSES,\"retry_count\":${_PS_RETRY:-0}" 2>/dev/null || true
                fi
              fi # US-325: close idempotency guard else
            fi

            # ── Batch merge: restore full PRD with ralph's updates ─────────
            if [[ "$_BATCH_ACTIVE" -eq 1 && -f "$_FULL_PRD_BACKUP" ]]; then
              "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/slice_prd.py" merge \
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
              # Strategy 8: Zero-progress auto-tune — graduated recovery before halting.
              # Count 1: force-decompose stuck stories (retries > 1) to unlock the backlog.
              # Count 2: halve SPIRAL_STORY_BATCH_SIZE to expose different stories.
              # Count N (SPIRAL_CONSECUTIVE_FAIL_ABORT): halt with ERR_ZERO_PROGRESS.
              # US-400: threshold is configurable; 0 = disabled (recovery strategies still apply cyclically).
              _ZP_ABORT_LIMIT="${SPIRAL_CONSECUTIVE_FAIL_ABORT:-3}"
              if [[ "$ZERO_PROGRESS_COUNT" -eq 1 ]]; then
                echo "  [zero-progress] Recovery 1: force-decomposing stuck stories (retries > 1)..."
                log_spiral_event "zero_progress_recovery" "\"action\":\"force_decompose\",\"streak\":$ZERO_PROGRESS_COUNT"
                _ZP_DECOMPOSED=0
                while IFS= read -r _ZP_SID; do
                  [[ -z "$_ZP_SID" ]] && continue
                  _ZP_RETRIES=$("$JQ" -r --arg id "$_ZP_SID" '.[$id] // 0' "$REPO_ROOT/retry-counts.json" 2>/dev/null || echo "0")
                  if [[ "$_ZP_RETRIES" -gt 1 ]]; then
                    echo "  [zero-progress] Force-decomposing $_ZP_SID (retries=$_ZP_RETRIES)..."
                    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/workers/decompose_story.py" \
                      --story-id "$_ZP_SID" --prd "$PRD_FILE" \
                      --progress "$REPO_ROOT/progress.txt" --model sonnet 2>/dev/null &&
                      _ZP_DECOMPOSED=$((_ZP_DECOMPOSED + 1)) ||
                      echo "  [zero-progress] Decompose failed for $_ZP_SID — skipping"
                  fi
                done < <("$JQ" -r '[.userStories[] | select(.passes != true and ._skipped != true and ._decomposed != true)] | .[].id' "$PRD_FILE" 2>/dev/null || true)
                echo "  [zero-progress] Force-decomposed $_ZP_DECOMPOSED stuck stories"
              elif [[ "$ZERO_PROGRESS_COUNT" -eq 2 ]]; then
                _ZP_OLD_BATCH="${SPIRAL_STORY_BATCH_SIZE:-20}"
                _ZP_NEW_BATCH=$((${SPIRAL_STORY_BATCH_SIZE:-20} > 10 ? ${SPIRAL_STORY_BATCH_SIZE:-20} / 2 : 5))
                SPIRAL_STORY_BATCH_SIZE="$_ZP_NEW_BATCH"
                echo "  [zero-progress] Recovery 2: batch size reduced $_ZP_OLD_BATCH → $SPIRAL_STORY_BATCH_SIZE (exposes different stories)"
                log_spiral_event "zero_progress_recovery" "\"action\":\"halve_batch_size\",\"streak\":$ZERO_PROGRESS_COUNT,\"old_batch\":$_ZP_OLD_BATCH,\"new_batch\":$SPIRAL_STORY_BATCH_SIZE"
              fi
              # US-400: Check configurable abort threshold (0 = disabled)
              if [[ "$_ZP_ABORT_LIMIT" -gt 0 && "$ZERO_PROGRESS_COUNT" -ge "$_ZP_ABORT_LIMIT" ]]; then
                echo ""
                echo "  ╔══════════════════════════════════════════════════════╗"
                printf "  ║  SPIRAL HALTED — %d consecutive zero-progress iters  ║\n" "$ZERO_PROGRESS_COUNT"
                echo "  ║  Pending stories may be blocked or require manual   ║"
                echo "  ║  intervention. Review prd.json and re-run.          ║"
                echo "  ╚══════════════════════════════════════════════════════╝"
                prd_stats
                echo ""
                # US-400: Diagnostic — list stuck story IDs, retry counts, and last failure reason
                echo "  ── Stuck Story Diagnostic ──────────────────────────────────"
                while IFS= read -r _ZP_DIAG_SID; do
                  _ZP_DIAG_SID="${_ZP_DIAG_SID//$'\r'/}"
                  [[ -z "$_ZP_DIAG_SID" ]] && continue
                  _ZP_DIAG_RETRIES=$("$JQ" -r --arg id "$_ZP_DIAG_SID" '.[$id] // 0' "$REPO_ROOT/retry-counts.json" 2>/dev/null || echo "0")
                  _ZP_DIAG_REASON=$("$JQ" -r --arg id "$_ZP_DIAG_SID" '.userStories[] | select(.id == $id) | ._failureReason // "unknown"' "$PRD_FILE" 2>/dev/null || echo "unknown")
                  _ZP_DIAG_TITLE=$("$JQ" -r --arg id "$_ZP_DIAG_SID" '.userStories[] | select(.id == $id) | .title // "?"' "$PRD_FILE" 2>/dev/null || echo "?")
                  printf "  [STUCK] %-8s retries=%-2s  %s\n" "$_ZP_DIAG_SID" "$_ZP_DIAG_RETRIES" "$_ZP_DIAG_TITLE"
                  [[ "$_ZP_DIAG_REASON" != "unknown" && "$_ZP_DIAG_REASON" != "null" ]] &&
                    echo "          └─ reason: ${_ZP_DIAG_REASON:0:120}"
                done < <("$JQ" -r '[.userStories[] | select(.passes != true and ._skipped != true)] | .[].id' "$PRD_FILE" 2>/dev/null || true)
                echo ""
                # US-400: Collect stuck IDs for event logging
                _ZP_STUCK_IDS=$("$JQ" -r '[.userStories[] | select(.passes != true and ._skipped != true)] | map(.id) | join(",")' "$PRD_FILE" 2>/dev/null || echo "")
                log_spiral_event "consecutive_fail_abort" \
                  "\"iteration\":$SPIRAL_ITER,\"consecutive_zero_pass\":$ZERO_PROGRESS_COUNT,\"limit\":$_ZP_ABORT_LIMIT,\"stuck_ids\":\"$_ZP_STUCK_IDS\""
                # US-400: Record abort_reason in _checkpoint.json before exit
                _ZP_CKPT_TMP="${CHECKPOINT_FILE}.tmp.$$"
                printf '{"iter":%d,"phase":"I","ts":"%s","run_id":"%s","abort_reason":"consecutive_failures","consecutive_zero_pass":%d,"limit":%d,"stuck_ids":"%s"}\n' \
                  "$SPIRAL_ITER" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${SPIRAL_RUN_ID:-}" \
                  "$ZERO_PROGRESS_COUNT" "$_ZP_ABORT_LIMIT" "$_ZP_STUCK_IDS" \
                  >"$_ZP_CKPT_TMP" 2>/dev/null && mv "$_ZP_CKPT_TMP" "$CHECKPOINT_FILE" 2>/dev/null || true
                spiral_exit E401
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

            # ── Scope-creep guard (US-150) ──────────────────────────────────────
            if [[ "$RALPH_PROGRESS" -gt 0 && "${SPIRAL_MAX_FILES_PER_STORY:-10}" -gt 0 ]]; then
              # Count files changed in the last commit, excluding .spiralignore patterns
              _SC_FILES_RAW=$(git -C "$REPO_ROOT" diff --name-only HEAD~1 2>/dev/null || echo "")
              _SC_DEFAULT_EXCLUDES='\.lock$|_generated\.|\.pb\.go$'
              _SC_FILE_LIST=$(echo "$_SC_FILES_RAW" | grep -Ev "$_SC_DEFAULT_EXCLUDES" || true)
              _SC_COUNT=$(echo "$_SC_FILE_LIST" | grep -c '.' 2>/dev/null || echo "0")
              # grep -c on empty string returns 0 lines but exits 1; guard with || true
              [[ -z "$_SC_FILE_LIST" ]] && _SC_COUNT=0

              if [[ "$_SC_COUNT" -gt "${SPIRAL_MAX_FILES_PER_STORY:-10}" ]]; then
                _SC_FILE_JSON=$(echo "$_SC_FILE_LIST" | "$JQ" -Rsc 'split("\n") | map(select(. != ""))' 2>/dev/null || echo "[]")
                echo ""
                echo "  [scope-creep] WARNING: Phase I touched $_SC_COUNT files (limit: ${SPIRAL_MAX_FILES_PER_STORY:-10})"
                echo "  [scope-creep] This story may be too large — consider decomposing it."
                log_spiral_event "scope_creep" \
                  "\"story_id\":\"${_NEXT_SID:-unknown}\",\"files_touched\":$_SC_COUNT,\"limit\":${SPIRAL_MAX_FILES_PER_STORY:-10},\"files\":$_SC_FILE_JSON,\"action\":\"${SPIRAL_SCOPE_CREEP_ACTION:-warn}\""

                if [[ "${SPIRAL_SCOPE_CREEP_ACTION:-warn}" == "abort" ]]; then
                  echo "  [scope-creep] SPIRAL_SCOPE_CREEP_ACTION=abort — marking story as failed and flagging for decomposition"
                  if [[ -n "${_NEXT_SID:-}" ]]; then
                    _SC_UPDATED=$("$JQ" --arg id "$_NEXT_SID" \
                      '(.userStories[] | select(.id == $id)) |= (. + {"passes": false, "_failureReason": "scope_creep: touched '"$_SC_COUNT"' files (limit '"${SPIRAL_MAX_FILES_PER_STORY:-10}"')", "_scopeCreep": true})' \
                      "$PRD_FILE" 2>/dev/null) || true
                    [[ -n "$_SC_UPDATED" ]] && { printf '%s\n' "$_SC_UPDATED" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE"; }
                  fi
                else
                  # warn mode: stamp _scopeCreep on the story without failing it
                  if [[ -n "${_NEXT_SID:-}" ]]; then
                    _SC_UPDATED=$("$JQ" --arg id "$_NEXT_SID" \
                      '(.userStories[] | select(.id == $id)) |= (. + {"_scopeCreep": true})' \
                      "$PRD_FILE" 2>/dev/null) || true
                    [[ -n "$_SC_UPDATED" ]] && { printf '%s\n' "$_SC_UPDATED" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE"; }
                  fi
                fi
              fi
            fi
          # ── End scope-creep guard ────────────────────────────────────────────
          fi # end _DIRTY_SKIP_RALPH=0 guard (US-177)

          # ── US-177: Pop auto-stash if one was created ─────────────────────
          if [[ -n "$_AUTO_STASH_REF" ]]; then
            echo "  [Phase I] Popping auto-stash ${_AUTO_STASH_REF}..."
            if ! git -C "$REPO_ROOT" stash pop "${_AUTO_STASH_REF}" 2>/dev/null; then
              echo "  [Phase I] WARNING: Auto-stash pop failed for ${_AUTO_STASH_REF} — stash preserved (recover manually)" >&2
              log_spiral_event "stash_pop_failed" "\"iteration\":$SPIRAL_ITER,\"stash_ref\":\"${_AUTO_STASH_REF}\""
            fi
          fi
          # ── End auto-stash pop ───────────────────────────────────────────
        fi # end PENDING > 0 block
        ;;
      *)
        echo "  [G] Unrecognized input '$GATE_INPUT' — treating as skip"
        ;;
    esac

    write_checkpoint "$SPIRAL_ITER" "I"

    # ── US-204: Cascade skip status through dependency chain ──────────────
    if [[ "${NO_CASCADE_SKIP:-0}" -eq 0 ]]; then
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/resilience/cascade_skip.py" \
        --prd "$PRD_FILE" \
        --events "${SCRATCH_DIR}/spiral_events.jsonl" \
        --iteration "$SPIRAL_ITER" \
        --run-id "${SPIRAL_RUN_ID:-}" 2>/dev/null || true
    fi

    # ── Tier 2: Verify passes didn't regress during implementation ────────
    spiral_assert_passes_monotonic "$PRD_FILE"
    spiral_assert_decomposition_integrity "$PRD_FILE"
    spiral_assert_dependency_completion_order "$PRD_FILE"
  fi
  run_phase_hook POST "I" || true
  run_phase_hook POST "G" || true
  _PHASE_DUR_I=$(($(date +%s) - _PHASE_TS_I))
  log_spiral_event "phase_end" "\"phase\":\"I\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_I"
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-phase --phase I --duration-s "$_PHASE_DUR_I" --iteration "$SPIRAL_ITER" 2>/dev/null || true
  notify_webhook "I" "end"
  log_spiral_event "phase_end" "\"phase\":\"G\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_I"
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-phase --phase G --duration-s "$_PHASE_DUR_I" --iteration "$SPIRAL_ITER" 2>/dev/null || true
  notify_webhook "G" "end"

  # ── LLM-as-Judge: score Phase I output (US-248) ──────────────────────────
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/quality/quality_judge.py" judge-phase-i \
    --prd "$PRD_FILE" \
    --checkpoint "$CHECKPOINT_FILE" \
    --iteration "$SPIRAL_ITER" \
    --threshold "${SPIRAL_QUALITY_THRESHOLD:-3}" 2>&1 | grep -v "^\s*$" || true

  # ── Snapshot passes count after Phase I (US-183) ──────────────────────────
  _PASSES_AFTER_I=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE" 2>/dev/null || echo "${_PASSES_BEFORE_I}")
}

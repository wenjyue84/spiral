#!/usr/bin/env python3
"""
Patch spiral.sh to parallelize Phase R and Phase T (US-182).
Replaces lines 1506-1834 (1-indexed) with parallel execution block.
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8')

with open('spiral.sh', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 0-indexed range to replace: 1505..1833 (inclusive)
START_IDX = 1505
END_IDX   = 1833

print(f"Replacing lines {START_IDX+1}..{END_IDX+1} ({END_IDX-START_IDX+1} lines)")
print("  Starts with:", repr(lines[START_IDX][:60]))
print("  Ends with  :", repr(lines[END_IDX][:60]))

NEW_SECTION = r"""  # ── Capacity guard → skip Phase R only when over capacity ────────────────
  OVER_CAPACITY=0
  if [[ "$PENDING" -gt "$CAPACITY_LIMIT" ]]; then
    OVER_CAPACITY=1
    echo ""
    echo "  [CAPACITY] $PENDING pending stories exceed limit of $CAPACITY_LIMIT."
    echo "  [CAPACITY] Skipping Phase R only (no web research for new stories) — T/M still run to catch regressions."
  fi

  # ── Phase R + T: RESEARCH and TEST SYNTHESIS (parallel) ──────────────────
  # US-182: R and T are independent — launch as background jobs and await both.
  PHASE="R"
  RESEARCH_OUTPUT="$SCRATCH_DIR/_research_output.json"
  TEST_OUTPUT="$SCRATCH_DIR/_test_stories_output.json"
  _phase_r_ckpt="$SCRATCH_DIR/_phase_R_${SPIRAL_ITER}.ckpt"
  _phase_t_ckpt="$SCRATCH_DIR/_phase_T_${SPIRAL_ITER}.ckpt"

  log_spiral_event "phase_start" "\"phase\":\"R\",\"iteration\":$SPIRAL_ITER"
  log_spiral_event "phase_start" "\"phase\":\"T\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "R" "start"
  notify_webhook "T" "start"

  # PRE hook for Phase R (synchronous — a failing hook aborts this iteration)
  run_phase_hook PRE "R" || continue

  # ── Determine skip conditions (synchronous, fast) ─────────────────────────
  _R_SKIP=0
  _T_SKIP=0

  if checkpoint_phase_done "R"; then
    echo ""
    echo "  [R] Skipping Phase R (checkpoint: already done this iter)"
    _R_SKIP=1
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo ""
    echo "  [dry-run] skipping research agent — using empty output"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    touch "$_phase_r_ckpt"
    _R_SKIP=1
  elif [[ "$SKIP_RESEARCH" -eq 1 ]]; then
    echo ""
    echo "  [R] Skipping Phase R (--skip-research flag set)"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    touch "$_phase_r_ckpt"
    _R_SKIP=1
  elif [[ "$OVER_CAPACITY" -eq 1 ]]; then
    echo ""
    echo "  [R] Skipping Phase R (over-capacity: $PENDING pending > $CAPACITY_LIMIT)"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    touch "$_phase_r_ckpt"
    _R_SKIP=1
  elif [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && spiral_should_skip_phase "R"; then
    _P_LVL=$(spiral_pressure_level)
    echo ""
    echo "  [R] Skipping Phase R (memory pressure: level $_P_LVL)"
    spiral_log_low_power "Phase R skipped (pressure level $_P_LVL, iter $SPIRAL_ITER)"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
    touch "$_phase_r_ckpt"
    _R_SKIP=1
  fi

  if checkpoint_phase_done "T"; then
    echo "  [T] Skipping Phase T (checkpoint: already done this iter)"
    _T_SKIP=1
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] skipping test synthesis"
    echo '{"stories":[]}' >"$TEST_OUTPUT"
    touch "$_phase_t_ckpt"
    _T_SKIP=1
  elif [[ "$SPIRAL_LOW_POWER_MODE" -eq 1 ]] && spiral_should_skip_phase "T"; then
    _P_LVL=$(spiral_pressure_level)
    echo "  [T] Skipping Phase T (memory pressure: level $_P_LVL)"
    spiral_log_low_power "Phase T skipped (pressure level $_P_LVL, iter $SPIRAL_ITER)"
    echo '{"stories":[]}' >"$TEST_OUTPUT"
    touch "$_phase_t_ckpt"
    _T_SKIP=1
  fi

  # ── Launch parallel background jobs ────────────────────────────────────────
  _PHASE_TS_RT=$(date +%s)
  _PHASE_TS_R=$_PHASE_TS_RT
  _PHASE_TS_T=$_PHASE_TS_RT
  PID_R=""
  PID_T=""

  if [[ "$_R_SKIP" -eq 0 ]]; then
    echo ""
    echo "  [Phase R] RESEARCH — launching in background..."
    (
      # ── Research cache: prune expired entries ──────────────────────────────
      if [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]]; then
        mkdir -p "$RESEARCH_CACHE_DIR"
        PRUNED=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research_cache.py" prune "$RESEARCH_CACHE_DIR" --ttl-hours "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" 2>/dev/null | grep -oP '\d+' || echo "0")
        [[ "$PRUNED" -gt 0 ]] && echo "  [R] Cache: pruned $PRUNED expired entries (TTL=${SPIRAL_RESEARCH_CACHE_TTL_HOURS}h)"
      fi

      # ── Gemini web research (optional, configured via SPIRAL_GEMINI_PROMPT) ──
      GEMINI_RESEARCH=""
      if command -v gemini &>/dev/null && [[ -n "$SPIRAL_GEMINI_PROMPT" ]]; then
        echo "  [R] Running Gemini 2.5 Pro web research (-y web search enabled)..."
        GEMINI_ERR_TMP=$(mktemp)
        GEMINI_RESEARCH=$(gemini \
          -m gemini-2.5-pro \
          -p "$SPIRAL_GEMINI_PROMPT" \
          -y --output-format text 2>"$GEMINI_ERR_TMP" || true)
        if [[ -n "$GEMINI_RESEARCH" ]]; then
          echo "  [R] Gemini web research complete ($(echo "$GEMINI_RESEARCH" | wc -l) lines)"
        else
          # Diagnose failure reason from stderr
          if grep -qi '429\|RESOURCE_EXHAUSTED\|rate.limit\|quota' "$GEMINI_ERR_TMP" 2>/dev/null; then
            echo "  [R] Gemini rate-limited — Claude will browse URLs directly"
          elif grep -qi 'PERMISSION_DENIED\|API.key\|api_key\|UNAUTHENTICATED' "$GEMINI_ERR_TMP" 2>/dev/null; then
            echo "  [R] Gemini auth error — check GEMINI_API_KEY"
          elif [[ -s "$GEMINI_ERR_TMP" ]]; then
            GEMINI_ERR_FIRST=$(head -1 "$GEMINI_ERR_TMP")
            echo "  [R] Gemini web research returned empty — $GEMINI_ERR_FIRST"
          else
            echo "  [R] Gemini web research returned empty — Claude will browse URLs directly"
          fi
        fi
        rm -f "$GEMINI_ERR_TMP"
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

      # ── Inject cached URL content so agent skips re-fetching ──────────────
      if [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]]; then
        CACHE_CONTEXT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research_cache.py" inject "$RESEARCH_CACHE_DIR" --ttl-hours "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" 2>/dev/null || true)
        if [[ -n "$CACHE_CONTEXT" ]]; then
          CACHE_COUNT=$(ls "$RESEARCH_CACHE_DIR"/*.json 2>/dev/null | wc -l)
          echo "  [R] Cache: injecting $CACHE_COUNT cached URL responses into prompt"
          INJECTED_PROMPT="$CACHE_CONTEXT

---

$INJECTED_PROMPT"
        fi
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

      # ── Retry loop for Phase R ─────────────────────────────────────────────
      _R_ATTEMPT=0
      _R_MAX_ATTEMPTS=$((SPIRAL_RESEARCH_RETRIES + 1))
      _R_SUCCESS=0

      while [[ "$_R_ATTEMPT" -lt "$_R_MAX_ATTEMPTS" ]]; do
        if [[ "$_R_ATTEMPT" -gt 0 ]]; then
          echo "  [R] Research output missing or invalid — retrying (attempt $_R_ATTEMPT/$SPIRAL_RESEARCH_RETRIES)"
        fi

        echo "  [R] Spawning Claude research agent (max 30 turns, model: $RESEARCH_MODEL)..."
        echo "  ─────── Research Agent Start ─────────────────────────"

        _R_EXIT=0
        _R_START=$(date +%s)
        if [[ "${SPIRAL_RESEARCH_TIMEOUT:-300}" -gt 0 ]] && command -v timeout &>/dev/null; then
          if command -v node &>/dev/null && [[ -f "$STREAM_FMT" ]]; then
            (
              unset CLAUDECODE
              timeout --kill-after=30 "${SPIRAL_RESEARCH_TIMEOUT}" \
                claude -p "$INJECTED_PROMPT" \
                --model "$RESEARCH_MODEL" \
                --allowedTools "$RESEARCH_TOOLS" \
                --max-turns 30 \
                --verbose \
                --output-format stream-json \
                --dangerously-skip-permissions \
                </dev/null 2>&1 | node "$STREAM_FMT"
            ) || _R_EXIT=$?
          else
            (
              unset CLAUDECODE
              timeout --kill-after=30 "${SPIRAL_RESEARCH_TIMEOUT}" \
                claude -p "$INJECTED_PROMPT" \
                --model "$RESEARCH_MODEL" \
                --allowedTools "$RESEARCH_TOOLS" \
                --max-turns 30 \
                --dangerously-skip-permissions \
                </dev/null 2>&1
            ) || _R_EXIT=$?
          fi
        else
          if command -v node &>/dev/null && [[ -f "$STREAM_FMT" ]]; then
            (
              unset CLAUDECODE
              claude -p "$INJECTED_PROMPT" \
                --model "$RESEARCH_MODEL" \
                --allowedTools "$RESEARCH_TOOLS" \
                --max-turns 30 \
                --verbose \
                --output-format stream-json \
                --dangerously-skip-permissions \
                </dev/null 2>&1 | node "$STREAM_FMT"
            ) || _R_EXIT=$?
          else
            (
              unset CLAUDECODE
              claude -p "$INJECTED_PROMPT" \
                --model "$RESEARCH_MODEL" \
                --allowedTools "$RESEARCH_TOOLS" \
                --max-turns 30 \
                --dangerously-skip-permissions \
                </dev/null 2>&1
            ) || _R_EXIT=$?
          fi
        fi
        _R_ELAPSED=$(($(date +%s) - _R_START))
        if [[ "$_R_EXIT" -eq 124 ]]; then
          echo ""
          echo "  [Phase R] WARNING: Research agent timed out after ${_R_ELAPSED}s (limit: ${SPIRAL_RESEARCH_TIMEOUT}s)"
          log_spiral_event "phase_timeout" "\"phase\":\"R\",\"story_id\":\"research\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_R_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_RESEARCH_TIMEOUT}"
        fi

        echo "  ─────── Research Agent End ───────────────────────────"

        # Validate output: file must exist and be valid JSON
        if [[ -f "$RESEARCH_OUTPUT" ]] && "$SPIRAL_PYTHON" -c "import json; json.load(open('$RESEARCH_OUTPUT'))" 2>/dev/null; then
          _R_SUCCESS=1
          break
        fi

        ((_R_ATTEMPT++)) || true
      done

      if [[ "$_R_SUCCESS" -eq 0 ]]; then
        echo "  [R] WARNING: Research output missing or invalid after all retries — using empty"
        echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
      fi

      if [[ ! -f "$RESEARCH_OUTPUT" ]]; then
        echo "  [R] WARNING: Research agent did not write $RESEARCH_OUTPUT — using empty"
        echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
      else
        RESEARCH_COUNT=$("$JQ" '.stories | length' "$RESEARCH_OUTPUT" 2>/dev/null || echo "?")
        echo "  [R] Research complete — $RESEARCH_COUNT story candidates found"

        # ── Cache source URLs from research output ─────────────────────────
        if [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]]; then
          CACHED_URLS=0
          while IFS= read -r src_url; do
            [[ -z "$src_url" ]] && continue
            # Extract story content referencing this source for cache value
            STORY_CONTENT=$("$JQ" -r --arg url "$src_url" \
              '[.stories[] | select(.source == $url)] | map(.title + ": " + .description) | join("\n")' \
              "$RESEARCH_OUTPUT" 2>/dev/null || true)
            if [[ -n "$STORY_CONTENT" ]]; then
              echo "$STORY_CONTENT" | "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research_cache.py" store "$RESEARCH_CACHE_DIR" "$src_url" - >/dev/null 2>&1 && ((CACHED_URLS++)) || true
            fi
          done < <("$JQ" -r '[.stories[].source // empty] | unique | .[]' "$RESEARCH_OUTPUT" 2>/dev/null || true)
          [[ "$CACHED_URLS" -gt 0 ]] && echo "  [R] Cache: stored $CACHED_URLS source URLs for future iterations"
        fi
      fi

      # Mark Phase R complete and record end time for duration calculation
      touch "$_phase_r_ckpt"
      date +%s >"$SCRATCH_DIR/_phase_R_${SPIRAL_ITER}.endtime"
    ) >"$SCRATCH_DIR/_phase_r_bg.log" 2>&1 &
    PID_R=$!
  fi

  if [[ "$_T_SKIP" -eq 0 ]]; then
    echo "  [Phase T] TEST SYNTHESIS — launching in background..."
    (
      _T_EXIT=0
      _T_START=$(date +%s)
      if [[ -n "$SPIRAL_CORE_BIN" ]]; then
        if [[ "${SPIRAL_TEST_SYNTH_TIMEOUT:-60}" -gt 0 ]] && command -v timeout &>/dev/null; then
          timeout --kill-after=30 "${SPIRAL_TEST_SYNTH_TIMEOUT}" \
            "$SPIRAL_CORE_BIN" synthesize \
            --prd "$PRD_FILE" \
            --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
            --output "$TEST_OUTPUT" \
            --repo-root "$REPO_ROOT" \
            ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
        else
          "$SPIRAL_CORE_BIN" synthesize \
            --prd "$PRD_FILE" \
            --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
            --output "$TEST_OUTPUT" \
            --repo-root "$REPO_ROOT" \
            ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
        fi
      else
        if [[ "${SPIRAL_TEST_SYNTH_TIMEOUT:-60}" -gt 0 ]] && command -v timeout &>/dev/null; then
          timeout --kill-after=30 "${SPIRAL_TEST_SYNTH_TIMEOUT}" \
            "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/synthesize_tests.py" \
            --prd "$PRD_FILE" \
            --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
            --output "$TEST_OUTPUT" \
            --repo-root "$REPO_ROOT" \
            ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
        else
          "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/synthesize_tests.py" \
            --prd "$PRD_FILE" \
            --reports-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
            --output "$TEST_OUTPUT" \
            --repo-root "$REPO_ROOT" \
            ${SPIRAL_FOCUS:+--focus "$SPIRAL_FOCUS"} || _T_EXIT=$?
        fi
      fi
      _T_ELAPSED=$(($(date +%s) - _T_START))
      if [[ "$_T_EXIT" -eq 124 ]]; then
        echo "  [Phase T] WARNING: Test synthesis timed out after ${_T_ELAPSED}s (limit: ${SPIRAL_TEST_SYNTH_TIMEOUT}s) — using empty output"
        log_spiral_event "phase_timeout" "\"phase\":\"T\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_T_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_TEST_SYNTH_TIMEOUT}"
        echo '{"stories":[]}' >"$TEST_OUTPUT"
      elif [[ "$_T_EXIT" -ne 0 ]]; then
        echo "  [Phase T] WARNING: Test synthesis exited with status $_T_EXIT — continuing with partial/empty output"
      fi

      TEST_COUNT=$("$JQ" '.stories | length' "$TEST_OUTPUT" 2>/dev/null || echo "0")
      echo "  [T] Test synthesis complete — $TEST_COUNT story candidates from failures"

      # Mark Phase T complete and record end time
      touch "$_phase_t_ckpt"
      date +%s >"$SCRATCH_DIR/_phase_T_${SPIRAL_ITER}.endtime"
    ) >"$SCRATCH_DIR/_phase_t_bg.log" 2>&1 &
    PID_T=$!
  fi

  # ── Await both background jobs ─────────────────────────────────────────────
  RC_R=0
  RC_T=0
  [[ -n "$PID_R" ]] && { wait "$PID_R"; RC_R=$?; }
  [[ -n "$PID_T" ]] && { wait "$PID_T"; RC_T=$?; }

  # ── Print buffered output (R first, then T) ────────────────────────────────
  [[ -n "$PID_R" && -f "$SCRATCH_DIR/_phase_r_bg.log" ]] && cat "$SCRATCH_DIR/_phase_r_bg.log"
  [[ -n "$PID_T" && -f "$SCRATCH_DIR/_phase_t_bg.log" ]] && cat "$SCRATCH_DIR/_phase_t_bg.log"

  # ── Handle failures: treat output as empty ────────────────────────────────
  if [[ "$RC_R" -ne 0 && ! -f "$RESEARCH_OUTPUT" ]]; then
    echo "  [R] Phase R background job failed (exit $RC_R) — using empty research output"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
  fi
  if [[ "$RC_T" -ne 0 && ! -f "$TEST_OUTPUT" ]]; then
    echo "  [T] Phase T background job failed (exit $RC_T) — using empty test output"
    echo '{"stories":[]}' >"$TEST_OUTPUT"
  fi

  # ── Write main checkpoint (T = last parallel phase in ordering) ───────────
  write_checkpoint "$SPIRAL_ITER" "T"

  # ── Compute individual durations and combined wall time ───────────────────
  _NOW=$(date +%s)
  _R_END=$(cat "$SCRATCH_DIR/_phase_R_${SPIRAL_ITER}.endtime" 2>/dev/null || echo "$_NOW")
  _T_END=$(cat "$SCRATCH_DIR/_phase_T_${SPIRAL_ITER}.endtime" 2>/dev/null || echo "$_NOW")
  _PHASE_DUR_R=$((_R_END - _PHASE_TS_RT))
  _PHASE_DUR_T=$((_T_END - _PHASE_TS_RT))
  _PHASE_DUR_RT_WALL=$((_NOW - _PHASE_TS_RT))  # actual wall time = max(R,T)

  log_spiral_event "phase_end" "\"phase\":\"R\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_R"
  log_spiral_event "phase_end" "\"phase\":\"T\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_T"
  notify_webhook "R" "end"
  notify_webhook "T" "end"
  PHASE="T"

  # POST hook for R (runs after both phases complete)
  run_phase_hook POST "R" || true
"""

new_lines = NEW_SECTION.splitlines(keepends=True)

result = lines[:START_IDX] + new_lines + lines[END_IDX+1:]

with open('spiral.sh', 'w', encoding='utf-8') as f:
    f.writelines(result)

print(f"Done. New total lines: {len(result)} (was {len(lines)})")
print(f"Inserted {len(new_lines)} lines, removed {END_IDX-START_IDX+1} lines")

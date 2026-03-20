#!/usr/bin/env bash
# lib/phases/phase_v_validate.sh — Phase V: VALIDATE (code)
#
# Runs the project's test suite after Phase I implementation to confirm
# the codebase is green end-to-end. Also runs optional browser/Lighthouse
# audits when configured.
#
# Steps:
#   1. Incremental mode (if SPIRAL_INCREMENTAL_VALIDATE=true):
#        — run only tests covering files touched by newly passed stories
#        — falls back to full suite when no matching tests found
#   2. Full suite: run $SPIRAL_VALIDATE_CMD
#   3. Optional: Lighthouse audit (if SPIRAL_DEV_URL set)
#   4. Optional: Chrome DevTools screenshot (if chrome-devtools-mcp available)
#   5. Write report.json + dashboard HTML
#
# Inputs:
#   $SPIRAL_VALIDATE_CMD       — test command (e.g. pytest tests/ -v)
#   $SPIRAL_REPORTS_DIR        — where test reports are written
#
# Outputs:
#   .spiral/report.json
#   .spiral/dashboard.html
#   .spiral/screenshots/iter-N-*.png (optional)
#
# Config vars:
#   SPIRAL_VALIDATE_TIMEOUT        — seconds before timeout (default: 300)
#   SPIRAL_INCREMENTAL_VALIDATE    — true = targeted test runs
#   SPIRAL_TEST_PREFIX             — test file prefix for incremental mode
#   SPIRAL_DEV_URL                 — enables Lighthouse + screenshot

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_validate() {
  # ── Snapshot passes count after Phase I (US-183) ──────────────────────────
  _PASSES_AFTER_I=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE" 2>/dev/null || echo "${_PASSES_BEFORE_I}")

  # ── Phase V: VALIDATE (test suite) ────────────────────────────────────────
  PHASE="V"
  _ACTIVE_STORY_ID=""
  _ACTIVE_STORY_TITLE=""     # US-311: clear story context after Phase I
  write_active_status "V" 80 # US-311
  print_phase_banner "V" "VALIDATE — running test suite..."
  log_spiral_event "phase_start" "\"phase\":\"V\",\"iteration\":$SPIRAL_ITER"
  notify_webhook "V" "start"
  _PHASE_TS_V=$(date +%s)
  run_phase_hook PRE "V" || return 1

  if checkpoint_phase_done "V"; then
    echo "  [V] Skipping (checkpoint: already done this iter)"
  elif [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  [dry-run] skipping validate — assuming pass"
    VALIDATE_EXIT=0
    write_checkpoint "$SPIRAL_ITER" "V"
  elif [[ "$RALPH_RAN" -eq 0 ]]; then
    echo "  [V] Skipping (ralph did not run — test results unchanged)"
    write_checkpoint "$SPIRAL_ITER" "V"
  elif [[ "$_PASSES_AFTER_I" -le "$_PASSES_BEFORE_I" && "$_PASSES_BEFORE_I" -ge 0 && "${SPIRAL_FORCE_VALIDATE:-false}" != "true" ]]; then
    echo "  [V] Skipping (Phase I produced no new story passes — set SPIRAL_FORCE_VALIDATE=true to override)"
    _PHASE_V_SKIPPED=1
    log_spiral_event "phase_v_skipped" "\"reason\":\"no_new_passes\",\"passes_before\":$_PASSES_BEFORE_I,\"passes_after\":$_PASSES_AFTER_I,\"iteration\":$SPIRAL_ITER"
    write_checkpoint "$SPIRAL_ITER" "V"
  else
    # ── Build effective validate command: incremental or full suite (US-131) ──
    _EFFECTIVE_VALIDATE_CMD="$SPIRAL_VALIDATE_CMD"
    if [[ "${SPIRAL_INCREMENTAL_VALIDATE:-false}" == "true" && -n "${PRE_RALPH_PRD_JSON:-}" ]]; then
      # When all stories are done, always run full suite as final gate
      _PENDING_NOW=$("$JQ" '[.userStories[] | select(.passes != true)] | length' "$PRD_FILE" 2>/dev/null || echo 1)
      if [[ "$_PENDING_NOW" -eq 0 ]]; then
        echo "  [V] All stories complete — running full test suite as final gate"
      else
        # Find newly passed stories vs pre-Phase-I baseline
        _NEWLY_PASSED_IDS=()
        mapfile -t _NEWLY_PASSED_IDS < <(
          "$JQ" -r --argjson before "$PRE_RALPH_PRD_JSON" \
            '[.userStories[] | . as $s |
            select(.passes == true) |
            select(($before.userStories | map(select(.id == $s.id and (.passes // false) == true)) | length) == 0)
          ] | .[] | .id' "$PRD_FILE" 2>/dev/null
        ) || true
        if [[ ${#_NEWLY_PASSED_IDS[@]} -gt 0 ]]; then
          # Collect filesTouch entries from newly passed stories
          _FILES_TOUCHED=()
          for _sid in "${_NEWLY_PASSED_IDS[@]}"; do
            while IFS= read -r _ft_entry; do
              [[ -n "$_ft_entry" ]] && _FILES_TOUCHED+=("$_ft_entry")
            done < <("$JQ" -r --arg id "$_sid" \
              '.userStories[] | select(.id == $id) | .filesTouch // [] | .[]' \
              "$PRD_FILE" 2>/dev/null || true)
          done
          if [[ ${#_FILES_TOUCHED[@]} -gt 0 ]]; then
            if echo "$SPIRAL_VALIDATE_CMD" | grep -q "vitest"; then
              # vitest: use --related flag to target only changed files
              _EFFECTIVE_VALIDATE_CMD="$SPIRAL_VALIDATE_CMD --related ${_FILES_TOUCHED[*]}"
              echo "  [V] Incremental (vitest --related): ${_FILES_TOUCHED[*]}"
              log_spiral_event "phase_v_incremental" \
                "\"mode\":\"vitest\",\"files\":${#_FILES_TOUCHED[@]},\"stories\":${#_NEWLY_PASSED_IDS[@]},\"iteration\":$SPIRAL_ITER"
            elif echo "$SPIRAL_VALIDATE_CMD" | grep -q "pytest"; then
              # pytest: map filesTouch entries to test file paths via SPIRAL_TEST_PREFIX
              _PYTEST_TARGETS=()
              for _ft in "${_FILES_TOUCHED[@]}"; do
                _base=$(basename "${_ft%.*}")
                _test_candidate="${SPIRAL_TEST_PREFIX:-tests/test_}${_base}.py"
                [[ -f "$REPO_ROOT/$_test_candidate" ]] && _PYTEST_TARGETS+=("$_test_candidate")
              done
              if [[ ${#_PYTEST_TARGETS[@]} -gt 0 && "$SPIRAL_VALIDATE_CMD" == *"tests/"* ]]; then
                _PYTEST_TARGETS_STR="${_PYTEST_TARGETS[*]}"
                _EFFECTIVE_VALIDATE_CMD="${SPIRAL_VALIDATE_CMD/tests\//${_PYTEST_TARGETS_STR} }"
                echo "  [V] Incremental (pytest): ${_PYTEST_TARGETS[*]}"
                log_spiral_event "phase_v_incremental" \
                  "\"mode\":\"pytest\",\"files\":${#_PYTEST_TARGETS[@]},\"stories\":${#_NEWLY_PASSED_IDS[@]},\"iteration\":$SPIRAL_ITER"
              fi
            fi
          fi
        fi
      fi
    fi
    # ── Parallel test execution (US-148) ────────────────────────────────────
    if [[ "${SPIRAL_PARALLEL_TESTS:-false}" == "true" ]]; then
      # Resolve worker count: explicit > nproc/2 (minimum 1)
      if [[ -n "${SPIRAL_TEST_WORKERS:-}" ]]; then
        _TEST_WORKERS="$SPIRAL_TEST_WORKERS"
      else
        _NPROC=$(nproc 2>/dev/null || echo 2)
        _TEST_WORKERS=$((_NPROC / 2))
        [[ "$_TEST_WORKERS" -lt 1 ]] && _TEST_WORKERS=1
      fi
      if echo "$_EFFECTIVE_VALIDATE_CMD" | grep -q "pytest"; then
        if "$SPIRAL_PYTHON" -c "import xdist" 2>/dev/null; then
          _EFFECTIVE_VALIDATE_CMD="$_EFFECTIVE_VALIDATE_CMD -n $_TEST_WORKERS"
          echo "  [V] Parallel pytest: -n $_TEST_WORKERS (pytest-xdist)"
          log_spiral_event "phase_v_parallel" "\"mode\":\"pytest-xdist\",\"workers\":$_TEST_WORKERS,\"iteration\":$SPIRAL_ITER"
        else
          echo "  [V] WARN: SPIRAL_PARALLEL_TESTS=true but pytest-xdist not installed — running serial"
        fi
      elif echo "$_EFFECTIVE_VALIDATE_CMD" | grep -qE "(^| )bats( |$)"; then
        if command -v parallel &>/dev/null; then
          _EFFECTIVE_VALIDATE_CMD="$_EFFECTIVE_VALIDATE_CMD --jobs $_TEST_WORKERS"
          echo "  [V] Parallel bats: --jobs $_TEST_WORKERS (GNU parallel)"
          log_spiral_event "phase_v_parallel" "\"mode\":\"bats\",\"workers\":$_TEST_WORKERS,\"iteration\":$SPIRAL_ITER"
        else
          echo "  [V] WARN: SPIRAL_PARALLEL_TESTS=true but GNU parallel not installed — running serial"
        fi
      fi
    fi
    export _EFFECTIVE_VALIDATE_CMD

    # ── Pre-Phase V memory gate: cap pytest workers under memory pressure ────
    # Same pattern as lib/run_parallel_ralph.sh:248-279 (Phase I memory check).
    # If free RAM < 2GB, force -n 1 (single worker) to avoid OOM crash.
    if command -v powershell.exe &>/dev/null && echo "$_EFFECTIVE_VALIDATE_CMD" | grep -qP -- '-n\s+\d+'; then
      _V_FREE_MB=$(powershell.exe -Command \
        "[math]::Floor((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1024)" 2>/dev/null | tr -d '\r')
      if [[ -n "$_V_FREE_MB" && "$_V_FREE_MB" =~ ^[0-9]+$ ]]; then
        if [[ "$_V_FREE_MB" -lt 2048 ]]; then
          # Force single worker to avoid OOM
          _EFFECTIVE_VALIDATE_CMD=$(echo "$_EFFECTIVE_VALIDATE_CMD" | sed -E 's/-n\s+[0-9]+/-n 1/')
          echo "  [V] Memory gate: ${_V_FREE_MB}MB free (<2048MB) — forcing -n 1 to prevent OOM"
          log_spiral_event "phase_v_memory_gate" \
            "\"free_mb\":$_V_FREE_MB,\"forced_workers\":1,\"iteration\":$SPIRAL_ITER"
        elif [[ "$_V_FREE_MB" -lt 3072 ]]; then
          echo "  [V] Memory: ${_V_FREE_MB}MB free — using configured pytest workers"
        fi
      fi
    fi

    # Run the project's validation command (with optional timeout)
    _VALIDATE_EXIT=0
    if [[ "${SPIRAL_VALIDATE_TIMEOUT:-300}" -gt 0 ]] && command -v timeout &>/dev/null; then
      _VALIDATE_START=$(date +%s)
      (cd "$REPO_ROOT" && timeout --kill-after=30 "${SPIRAL_VALIDATE_TIMEOUT}" bash -c "eval \"\$_EFFECTIVE_VALIDATE_CMD\"" 2>&1) || _VALIDATE_EXIT=$?
      _VALIDATE_ELAPSED=$(($(date +%s) - _VALIDATE_START))
      if [[ "$_VALIDATE_EXIT" -eq 124 ]]; then
        echo ""
        echo "  [Phase V] WARNING: Phase V timed out after ${_VALIDATE_ELAPSED}s — treating as validation failure"
        log_spiral_event "phase_timeout" "\"phase\":\"V\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_VALIDATE_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_VALIDATE_TIMEOUT}"
        _VALIDATE_EXIT=1
      fi
    else
      (cd "$REPO_ROOT" && eval "$_EFFECTIVE_VALIDATE_CMD" 2>&1) || _VALIDATE_EXIT=$?
    fi

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

    # ── Optional: Chrome DevTools screenshot ───────────────────────────────
    if [[ -n "${SPIRAL_DEV_URL:-}" ]]; then
      _SCREENSHOT_DIR="$SCRATCH_DIR/screenshots"
      mkdir -p "$_SCREENSHOT_DIR"
      _SCREENSHOT_TS=$(date +%Y%m%d-%H%M%S)
      _SCREENSHOT_PATH="$_SCREENSHOT_DIR/iter-${SPIRAL_ITER}-${_SCREENSHOT_TS}.png"
      echo "  [V] Taking screenshot of $SPIRAL_DEV_URL..."

      # Use Claude agent with Chrome DevTools MCP to navigate + screenshot
      _SCREENSHOT_PROMPT="Navigate to $SPIRAL_DEV_URL using mcp__chrome-devtools__navigate_page, wait for it to load, then take a screenshot using mcp__chrome-devtools__take_screenshot and save the result. Output only the word DONE when finished."
      if (
        unset CLAUDECODE
        claude -p "$_SCREENSHOT_PROMPT" \
          --allowedTools "Bash,mcp__chrome-devtools__navigate_page,mcp__chrome-devtools__take_screenshot,mcp__chrome-devtools__wait_for" \
          --max-turns 5 \
          --dangerously-skip-permissions \
          2>/dev/null
      ) | grep -qi "done"; then
        # Chrome DevTools saves screenshots via its own mechanism;
        # check if a screenshot was produced in the scratch dir
        if ls "$_SCREENSHOT_DIR"/iter-${SPIRAL_ITER}-*.png 1>/dev/null 2>&1; then
          echo "  [V] Screenshot saved to $_SCREENSHOT_DIR/"
        else
          echo "  [V] Screenshot command ran but no file was saved (Chrome DevTools MCP may not be available)"
        fi
      else
        echo "  [V] Screenshot skipped (Chrome DevTools MCP not available or failed)"
      fi
    fi

    # ── Optional: Pinchtab shell-driven E2E assertions ──────────────────────
    # Runs AFTER pytest and after the optional Chrome DevTools screenshot.
    # Pinchtab is a persistent HTTP browser server — called from shell, not
    # from inside a Claude agent turn. Text mode is 5-13x cheaper in tokens.
    if [[ -n "${SPIRAL_PINCHTAB_URL:-}" ]]; then
      _PINCHTAB_EXIT=0
      if [[ -n "${SPIRAL_PINCHTAB_E2E_CMD:-}" ]]; then
        # User-supplied E2E script (login flows, multi-step assertions)
        echo "  [V] Running pinchtab E2E: $SPIRAL_PINCHTAB_E2E_CMD"
        (cd "$REPO_ROOT" && eval "$SPIRAL_PINCHTAB_E2E_CMD" 2>&1) || _PINCHTAB_EXIT=$?
      elif [[ -n "${SPIRAL_DEV_URL:-}" ]] && command -v pinchtab &>/dev/null; then
        # Default: nav to dev URL, extract text, print first 20 lines
        echo "  [V] Pinchtab E2E: navigating to $SPIRAL_DEV_URL..."
        pinchtab --server "$SPIRAL_PINCHTAB_URL" nav "$SPIRAL_DEV_URL" 2>/dev/null || _PINCHTAB_EXIT=$?
        if [[ "$_PINCHTAB_EXIT" -eq 0 ]]; then
          _PINCHTAB_TEXT=$(pinchtab --server "$SPIRAL_PINCHTAB_URL" text 2>/dev/null || true)
          if [[ -n "$_PINCHTAB_TEXT" ]]; then
            echo "  [V] Pinchtab page text (first 20 lines):"
            echo "$_PINCHTAB_TEXT" | head -20 | sed 's/^/    /'
          else
            echo "  [V] Pinchtab: page loaded (no text content extracted)"
          fi
        else
          echo "  [V] WARNING: pinchtab nav failed (exit $_PINCHTAB_EXIT) — E2E step skipped"
        fi
      elif ! command -v pinchtab &>/dev/null; then
        echo "  [V] Pinchtab E2E skipped (pinchtab CLI not found — install with: npm install -g pinchtab)"
      else
        echo "  [V] Pinchtab E2E skipped (SPIRAL_DEV_URL not set — set it to enable nav+text assertions)"
      fi

      if [[ "$_PINCHTAB_EXIT" -ne 0 ]]; then
        echo "  [V] WARNING: Pinchtab E2E step failed (exit $_PINCHTAB_EXIT) — does not affect validation result"
      fi
    fi

    # ── Persistent Test Suites ────────────────────────────────────────────────
    # Accumulate passing stories into suites, then run active suite tests.
    # Tests grow over time; results saved per-iteration in .spiral/test-suites/.
    _SUITE_ROOT="$SCRATCH_DIR/test-suites"
    echo "  [V] Updating persistent test suites from passed stories..."
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/quality/test_suite_manager.py" add-from-prd \
      --prd "$PRD_FILE" \
      --suite-root "$_SUITE_ROOT" \
      --suite-types "smoke,regression,security,performance" || true

    for _suite_type in smoke regression security performance; do
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/quality/test_suite_manager.py" run "$_suite_type" \
        --suite-root "$_SUITE_ROOT" \
        --iteration "$SPIRAL_ITER" \
        --repo-root "$REPO_ROOT" \
        --timeout 120 || true
    done

    # Print suite status summary
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/quality/test_suite_manager.py" status \
      --suite-root "$_SUITE_ROOT" || true

    write_checkpoint "$SPIRAL_ITER" "V"
  fi
  run_phase_hook POST "V" || true
  _PHASE_DUR_V=$(($(date +%s) - _PHASE_TS_V))
  log_spiral_event "phase_end" "\"phase\":\"V\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_V"
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-phase --phase V --duration-s "$_PHASE_DUR_V" --iteration "$SPIRAL_ITER" 2>/dev/null || true
  notify_webhook "V" "end"
}

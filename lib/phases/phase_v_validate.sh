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
    # ── US-782: Failure attribution (baseline captured in spiral.sh before Phase I) ──
    _TEST_BASELINE_EXISTS=0
    if [[ -f "$_TEST_BASELINE_FILE" ]]; then
      _TEST_BASELINE_EXISTS=1
    fi
    # ── Build effective validate command: incremental or full suite (US-131, US-1102) ──
    _EFFECTIVE_VALIDATE_CMD="$SPIRAL_VALIDATE_CMD"
    _FORCE_FULL_SUITE=0
    _INCREMENTAL_RUN=0

    # ── Check if we should force full suite every N iterations (US-1102) ──
    if [[ "${SPIRAL_FULL_TEST_EVERY_N:-5}" -gt 0 ]]; then
      _MOD=$((SPIRAL_ITER % ${SPIRAL_FULL_TEST_EVERY_N:-5}))
      if [[ "$_MOD" -eq 0 ]]; then
        _FORCE_FULL_SUITE=1
        echo "  [V] Full suite forced (iter $SPIRAL_ITER % ${SPIRAL_FULL_TEST_EVERY_N:-5} = 0)"
        log_spiral_event "phase_v_full_suite_forced" \
          "\"reason\":\"iteration_frequency\",\"interval\":${SPIRAL_FULL_TEST_EVERY_N:-5},\"iteration\":$SPIRAL_ITER"
      fi
    fi

    if [[ "${SPIRAL_INCREMENTAL_VALIDATE:-false}" == "true" && -n "${PRE_RALPH_PRD_JSON:-}" && "$_FORCE_FULL_SUITE" -eq 0 ]]; then
      # When all stories are done, always run full suite as final gate
      _PENDING_NOW=$("$JQ" '[.userStories[] | select(.passes != true)] | length' "$PRD_FILE" 2>/dev/null || echo 1)
      if [[ "$_PENDING_NOW" -eq 0 ]]; then
        _FORCE_FULL_SUITE=1
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
          # ── Per-story verification contracts ──
          # If a story has a `verification` field, use it directly instead of
          # the filesTouch heuristic. Supports testFiles, testMarker, and command.
          _VERIFICATION_PYTEST_TARGETS=()
          _VERIFICATION_MARKERS=()
          _VERIFICATION_COMMANDS=()
          _STORIES_WITH_CONTRACT=()
          for _sid in "${_NEWLY_PASSED_IDS[@]}"; do
            _HAS_VERIFICATION=$("$JQ" -r --arg id "$_sid" \
              '.userStories[] | select(.id == $id) | .verification // empty | type' \
              "$PRD_FILE" 2>/dev/null || echo '')
            if [[ "$_HAS_VERIFICATION" == "object" ]]; then
              _STORIES_WITH_CONTRACT+=("$_sid")
              # Extract testFiles
              while IFS= read -r _tf; do
                [[ -n "$_tf" && -f "$REPO_ROOT/$_tf" ]] && _VERIFICATION_PYTEST_TARGETS+=("$_tf")
              done < <("$JQ" -r --arg id "$_sid" \
                '.userStories[] | select(.id == $id) | .verification.testFiles // [] | .[]' \
                "$PRD_FILE" 2>/dev/null || true)
              # Extract testMarker
              _MARKER=$("$JQ" -r --arg id "$_sid" \
                '.userStories[] | select(.id == $id) | .verification.testMarker // empty' \
                "$PRD_FILE" 2>/dev/null || echo '')
              [[ -n "$_MARKER" ]] && _VERIFICATION_MARKERS+=("$_MARKER")
              # Extract command
              _CMD=$("$JQ" -r --arg id "$_sid" \
                '.userStories[] | select(.id == $id) | .verification.command // empty' \
                "$PRD_FILE" 2>/dev/null || echo '')
              [[ -n "$_CMD" ]] && _VERIFICATION_COMMANDS+=("$_CMD")
            fi
          done

          # Apply verification contracts: testFiles and markers override filesTouch
          if [[ ${#_VERIFICATION_PYTEST_TARGETS[@]} -gt 0 || ${#_VERIFICATION_MARKERS[@]} -gt 0 ]]; then
            _INCREMENTAL_RUN=1
            if [[ ${#_VERIFICATION_PYTEST_TARGETS[@]} -gt 0 ]]; then
              _PYTEST_TARGETS_STR="${_VERIFICATION_PYTEST_TARGETS[*]}"
              _EFFECTIVE_VALIDATE_CMD="${SPIRAL_VALIDATE_CMD/tests\//${_PYTEST_TARGETS_STR} }"
            fi
            for _m in "${_VERIFICATION_MARKERS[@]}"; do
              _EFFECTIVE_VALIDATE_CMD="$_EFFECTIVE_VALIDATE_CMD -m $_m"
            done
            echo "  [V] Verification contract: files=[${_VERIFICATION_PYTEST_TARGETS[*]}] markers=[${_VERIFICATION_MARKERS[*]}]"
            log_spiral_event "phase_v_verification_contract" \
              "\"stories\":[$(printf '"%s",' "${_STORIES_WITH_CONTRACT[@]}" | sed 's/,$//')],\"test_files\":${#_VERIFICATION_PYTEST_TARGETS[@]},\"markers\":${#_VERIFICATION_MARKERS[@]},\"iteration\":$SPIRAL_ITER"
          fi

          # Run standalone verification commands (non-pytest)
          for _vcmd in "${_VERIFICATION_COMMANDS[@]}"; do
            echo "  [V] Running verification command: $_vcmd"
            if ! eval "$_vcmd" 2>&1; then
              echo "  [V] Verification command FAILED: $_vcmd"
            fi
          done

          # Filter stories without contracts for filesTouch heuristic
          _STORIES_WITHOUT_CONTRACT=()
          for _sid in "${_NEWLY_PASSED_IDS[@]}"; do
            local _has_contract=false
            for _csid in "${_STORIES_WITH_CONTRACT[@]}"; do
              [[ "$_sid" == "$_csid" ]] && _has_contract=true && break
            done
            [[ "$_has_contract" == "false" ]] && _STORIES_WITHOUT_CONTRACT+=("$_sid")
          done

          # Collect filesTouch entries from newly passed stories WITHOUT verification contracts
          _FILES_TOUCHED=()
          for _sid in "${_STORIES_WITHOUT_CONTRACT[@]}"; do
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
              _INCREMENTAL_RUN=1
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
                _INCREMENTAL_RUN=1
                _PYTEST_TARGETS_STR="${_PYTEST_TARGETS[*]}"
                _EFFECTIVE_VALIDATE_CMD="${SPIRAL_VALIDATE_CMD/tests\//${_PYTEST_TARGETS_STR} }"

                # ── Add pytest --lf (last-failed) flag if enabled (US-1102) ──
                if [[ "${SPIRAL_USE_LAST_FAILED:-true}" == "true" ]]; then
                  _EFFECTIVE_VALIDATE_CMD="$_EFFECTIVE_VALIDATE_CMD --lf"
                  echo "  [V] Incremental (pytest --lf): ${_PYTEST_TARGETS[*]} + last-failed"
                else
                  echo "  [V] Incremental (pytest): ${_PYTEST_TARGETS[*]}"
                fi
                log_spiral_event "phase_v_incremental" \
                  "\"mode\":\"pytest\",\"files\":${#_PYTEST_TARGETS[@]},\"stories\":${#_NEWLY_PASSED_IDS[@]},\"last_failed\":${SPIRAL_USE_LAST_FAILED:-true},\"iteration\":$SPIRAL_ITER"
              fi
            fi
          fi
        fi

        # ── Detect changed files via git diff and map to tests (US-1102) ──
        if [[ "$_INCREMENTAL_RUN" -eq 0 ]]; then
          # No newly passed stories, but check git diff for other changes
          _CHANGED_FILES=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/util/changed_files_to_tests.py" \
            --git-diff "HEAD~1" --repo-root "$REPO_ROOT" 2>/dev/null || echo '{}')
          _AFFECTED_TESTS=$(echo "$_CHANGED_FILES" | "$JQ" -r '.mapping.all[]? // empty' 2>/dev/null | tr '\n' ' ')
          if [[ -n "$_AFFECTED_TESTS" ]] && echo "$SPIRAL_VALIDATE_CMD" | grep -q "pytest"; then
            _INCREMENTAL_RUN=1
            _EFFECTIVE_VALIDATE_CMD="${SPIRAL_VALIDATE_CMD/tests\//$_AFFECTED_TESTS }"

            # ── Add pytest --lf flag if enabled (US-1102) ──
            if [[ "${SPIRAL_USE_LAST_FAILED:-true}" == "true" ]]; then
              _EFFECTIVE_VALIDATE_CMD="$_EFFECTIVE_VALIDATE_CMD --lf"
              echo "  [V] Incremental (git diff + --lf): $_AFFECTED_TESTS"
            else
              echo "  [V] Incremental (git diff): $_AFFECTED_TESTS"
            fi
            log_spiral_event "phase_v_incremental_git_diff" \
              "\"mode\":\"git_diff\",\"affected_tests\":$(echo "$_AFFECTED_TESTS" | wc -w),\"last_failed\":${SPIRAL_USE_LAST_FAILED:-true},\"iteration\":$SPIRAL_ITER"
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

    # ── pytest cache persistence (US-1099) ────────────────────────────────────
    # Add -o cache_dir and --import-mode to pytest for faster reruns.
    # Cache persists across iterations and worker resets.
    if echo "$_EFFECTIVE_VALIDATE_CMD" | grep -q "pytest"; then
      _CACHE_DIR="${SPIRAL_PYTEST_CACHE_DIR:-.spiral/.pytest_cache}"
      _CACHE_PATH="$REPO_ROOT/$_CACHE_DIR"
      mkdir -p "$_CACHE_PATH" 2>/dev/null || true

      # Check cache size and prune if exceeds limit
      if [[ "${SPIRAL_PYTEST_CACHE_MAX_MB:-100}" -gt 0 ]]; then
        _CACHE_SIZE_MB=$("$SPIRAL_PYTHON" -c \
          "import os; cd='$_CACHE_PATH'; print(int(sum(os.path.getsize(os.path.join(d,f)) for d,_,fs in os.walk(cd) for f in fs) / 1024 / 1024)) if os.path.exists(cd) else print(0)" \
          2>/dev/null || echo 0)
        if [[ "$_CACHE_SIZE_MB" -gt "${SPIRAL_PYTEST_CACHE_MAX_MB}" ]]; then
          echo "  [V] Cache: ${_CACHE_SIZE_MB}MB > limit ${SPIRAL_PYTEST_CACHE_MAX_MB}MB — pruning..."
          rm -rf "$_CACHE_PATH" 2>/dev/null || true
          mkdir -p "$_CACHE_PATH" 2>/dev/null || true
          log_spiral_event "phase_v_cache_prune" \
            "\"cache_size_mb\":$_CACHE_SIZE_MB,\"limit_mb\":${SPIRAL_PYTEST_CACHE_MAX_MB},\"iteration\":$SPIRAL_ITER"
        else
          echo "  [V] Cache: ${_CACHE_SIZE_MB}MB (limit: ${SPIRAL_PYTEST_CACHE_MAX_MB}MB)"
        fi
      fi

      # Add cache flags to pytest command using -o (config override)
      _EFFECTIVE_VALIDATE_CMD="$_EFFECTIVE_VALIDATE_CMD -o cache_dir=$_CACHE_DIR --import-mode=importlib"
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
    _TEST_OUTPUT_FILE="$SCRATCH_DIR/test_output_${SPIRAL_ITER}.log"
    mkdir -p "$SCRATCH_DIR"

    if [[ "${SPIRAL_VALIDATE_TIMEOUT:-300}" -gt 0 ]] && command -v timeout &>/dev/null; then
      _VALIDATE_START=$(date +%s)
      (cd "$REPO_ROOT" && timeout --kill-after=30 "${SPIRAL_VALIDATE_TIMEOUT}" bash -c "eval \"\$_EFFECTIVE_VALIDATE_CMD\"" 2>&1) | tee "$_TEST_OUTPUT_FILE" || _VALIDATE_EXIT=$?
      _VALIDATE_ELAPSED=$(($(date +%s) - _VALIDATE_START))
      if [[ "$_VALIDATE_EXIT" -eq 124 ]]; then
        echo ""
        echo "  [Phase V] WARNING: Phase V timed out after ${_VALIDATE_ELAPSED}s — treating as validation failure"
        log_spiral_event "phase_timeout" "\"phase\":\"V\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_VALIDATE_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_VALIDATE_TIMEOUT}"
        _VALIDATE_EXIT=1
      fi
    else
      (cd "$REPO_ROOT" && eval "$_EFFECTIVE_VALIDATE_CMD" 2>&1) | tee "$_TEST_OUTPUT_FILE" || _VALIDATE_EXIT=$?
    fi

    # ── US-1184: Generate test report JSON ──────────────────────────────────────
    # Parse test output and write report.json so Phase C can find results
    _REPORT_PATH=""
    if [[ -f "$_TEST_OUTPUT_FILE" && -s "$_TEST_OUTPUT_FILE" ]]; then
      _REPORT_PATH=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/quality/parse_test_output.py" \
        --format auto \
        --input "$_TEST_OUTPUT_FILE" \
        --output-dir "$REPO_ROOT/$SPIRAL_REPORTS_DIR" \
        --exit-code "$_VALIDATE_EXIT" 2>/dev/null || echo "")
      if [[ -n "$_REPORT_PATH" && -f "$_REPORT_PATH" ]]; then
        echo "  [V] Test report written to $_REPORT_PATH"
        log_spiral_event "phase_v_report_generated" \
          "\"report_path\":\"$(basename $(dirname $_REPORT_PATH))\",\"exit_code\":$_VALIDATE_EXIT,\"iteration\":$SPIRAL_ITER"
      else
        # Fallback: create minimal report from exit code
        _FALLBACK_TS=$(date +%Y%m%d-%H%M%S)
        _FALLBACK_DIR="$REPO_ROOT/$SPIRAL_REPORTS_DIR/$_FALLBACK_TS"
        mkdir -p "$_FALLBACK_DIR"
        _FALLBACK_REPORT="$_FALLBACK_DIR/report.json"
        printf '{"timestamp":"%s","exit_code":%d,"summary":{"passed":0,"failed":0,"errored":0,"skipped":0,"total":0}}\n' \
          "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$_VALIDATE_EXIT" >"$_FALLBACK_REPORT"
        echo "  [V] Fallback test report created: $_FALLBACK_REPORT"
        _REPORT_PATH="$_FALLBACK_REPORT"
      fi
    else
      # No test output captured; create a fallback report
      _FALLBACK_TS=$(date +%Y%m%d-%H%M%S)
      _FALLBACK_DIR="$REPO_ROOT/$SPIRAL_REPORTS_DIR/$_FALLBACK_TS"
      mkdir -p "$_FALLBACK_DIR"
      _FALLBACK_REPORT="$_FALLBACK_DIR/report.json"
      printf '{"timestamp":"%s","exit_code":%d,"summary":{"passed":0,"failed":0,"errored":0,"skipped":0,"total":0}}\n' \
        "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$_VALIDATE_EXIT" >"$_FALLBACK_REPORT"
      echo "  [V] Test output not captured; fallback report created: $_FALLBACK_REPORT"
      _REPORT_PATH="$_FALLBACK_REPORT"
    fi

    # ── Auto-Generate Assertions from AC (US-1413) ──────────────────────────────
    # For stories without explicit testFiles/testMarker, auto-generate assertions
    # from acceptance criteria text using assertion_extractor.py
    if [[ "${SPIRAL_AUTO_ASSERTIONS:-true}" == "true" && "$_VALIDATE_EXIT" -eq 0 ]]; then
      echo "  [V] Auto-Generating Assertions: extracting from acceptance criteria..."

      mapfile -t _PASSED_STORIES < <(
        "$JQ" -r '.userStories[] | select(.passes == true) | .id' "$PRD_FILE" 2>/dev/null || true
      ) || true

      for _story_id in "${_PASSED_STORIES[@]}"; do
        # Check if story has explicit verification
        _HAS_TEST_FILES=$("$JQ" --arg id "$_story_id" \
          '.userStories[] | select(.id == $id) | .verification.testFiles // empty' \
          "$PRD_FILE" 2>/dev/null || echo "")
        _HAS_TEST_MARKER=$("$JQ" --arg id "$_story_id" \
          '.userStories[] | select(.id == $id) | .verification.testMarker // empty' \
          "$PRD_FILE" 2>/dev/null || echo "")

        # If no explicit verification, auto-generate from AC
        if [[ -z "$_HAS_TEST_FILES" && -z "$_HAS_TEST_MARKER" ]]; then
          _AUTO_ASSERTIONS_DIR="$SCRATCH_DIR/auto_assertions"
          mkdir -p "$_AUTO_ASSERTIONS_DIR"

          # Call assertion_extractor to generate pytest assertions
          _EXTRACTION_RESULT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/assertion_extractor.py" \
            --story-id "$_story_id" \
            --prd-file "$PRD_FILE" \
            --output-dir "$_AUTO_ASSERTIONS_DIR" 2>&1 || echo "extraction_failed")

          if [[ ! "$_EXTRACTION_RESULT" =~ "extraction_failed" ]]; then
            _AUTO_ASSERTIONS_FILE="$_AUTO_ASSERTIONS_DIR/${_story_id}.py"
            if [[ -f "$_AUTO_ASSERTIONS_FILE" ]]; then
              echo "  [V] Auto-assertions generated: $_AUTO_ASSERTIONS_FILE"
            fi
          fi
        fi
      done
    fi

    # ── Optional: AC Verification (US-1005) ────────────────────────────────────
    # After pytest passes, run AC verification on extracted assertions.
    # Only runs if SPIRAL_AC_VERIFY=true and pytest passed.
    if [[ "${SPIRAL_AC_VERIFY:-true}" == "true" && "$_VALIDATE_EXIT" -eq 0 ]]; then
      echo "  [V] AC Verification: checking extracted acceptance criteria..."

      # For each newly passed story, run AC verification if assertions exist
      _AC_VERIFY_FAILED=0
      mapfile -t _PASSED_STORIES < <(
        "$JQ" -r '.userStories[] | select(.passes == true) | .id' "$PRD_FILE" 2>/dev/null || true
      ) || true

      for _story_id in "${_PASSED_STORIES[@]}"; do
        _AC_CHECKS_FILE="$SCRATCH_DIR/ac_checks/${_story_id}.json"
        if [[ -f "$_AC_CHECKS_FILE" ]]; then
          # Run AC verification for this story
          _AC_RESULTS=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/ac_verification_runner.py" \
            --story-id "$_story_id" \
            --assertions-file "$_AC_CHECKS_FILE" \
            --timeout 30 2>&1 || echo '{"error":"runner failed"}')

          # Parse results
          _AC_PASSED=$(echo "$_AC_RESULTS" | "$JQ" '.passed // 0' 2>/dev/null || echo 0)
          _AC_FAILED=$(echo "$_AC_RESULTS" | "$JQ" '.failed // 0' 2>/dev/null || echo 0)
          _AC_SKIPPED=$(echo "$_AC_RESULTS" | "$JQ" '.skipped // 0' 2>/dev/null || echo 0)
          _AC_TOTAL=$(echo "$_AC_RESULTS" | "$JQ" '.total // 0' 2>/dev/null || echo 0)

          # Update story with AC verification results
          if [[ "$_AC_TOTAL" -gt 0 ]]; then
            "$JQ" --arg id "$_story_id" \
              --argjson results "$_AC_RESULTS" \
              '(.userStories[] | select(.id == $id) | ._acVerification) = $results' \
              "$PRD_FILE" >"$PRD_FILE.tmp" 2>/dev/null && mv "$PRD_FILE.tmp" "$PRD_FILE" || true
          fi

          # Determine if AC verification failed
          if [[ "$_AC_FAILED" -gt 0 && "$_AC_PASSED" -eq 0 ]]; then
            # Zero assertions passed — story fails
            echo "  [V] AC FAIL: $_story_id — $_AC_FAILED/$_AC_TOTAL assertions failed, 0 passed"
            _AC_VERIFY_FAILED=1
            _VALIDATE_EXIT=1
          elif [[ "$_AC_FAILED" -gt 0 && "$_AC_PASSED" -gt 0 ]]; then
            # Mixed results — warn but allow
            echo "  [V] AC WARN: $_story_id — $_AC_PASSED/$_AC_TOTAL passed, $_AC_FAILED failed (mixed results allowed)"
          elif [[ "$_AC_PASSED" -gt 0 ]]; then
            # All assertions passed
            echo "  [V] AC OK: $_story_id — $_AC_PASSED/$_AC_TOTAL assertions passed"
          fi
        fi
      done
    fi

    # ── Optional: Dead Feature Detection (US-1006) ────────────────────────────────
    # After pytest passes, scan for newly added functions/classes that are never
    # imported or called anywhere. Prevents code that exists but doesn't work.
    _DFD_FAILED=0
    if [[ "$_VALIDATE_EXIT" -eq 0 ]]; then
      echo "  [V] Dead Feature Detection: scanning for unreachable new code..."

      mapfile -t _PASSED_STORIES < <(
        "$JQ" -r '.userStories[] | select(.passes == true) | .id' "$PRD_FILE" 2>/dev/null || true
      ) || true

      for _story_id in "${_PASSED_STORIES[@]}"; do
        # Get filesTouch for this story
        _FILES_TO_SCAN=()
        while IFS= read -r _ft_entry; do
          [[ -n "$_ft_entry" ]] && _FILES_TO_SCAN+=("$_ft_entry")
        done < <("$JQ" -r --arg id "$_story_id" \
          '.userStories[] | select(.id == $id) | .filesTouch // [] | .[]' \
          "$PRD_FILE" 2>/dev/null || true)

        if [[ ${#_FILES_TO_SCAN[@]} -gt 0 ]]; then
          # Run dead feature detector
          _DFD_RESULTS=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/dead_feature_detector.py" \
            --story-id "$_story_id" \
            --changed-files "${_FILES_TO_SCAN[@]}" \
            --repo-root "$REPO_ROOT" 2>&1 || echo '{"error":"detector failed"}')

          # Parse results
          _DFD_TOTAL=$(echo "$_DFD_RESULTS" | "$JQ" '.total_features // 0' 2>/dev/null || echo 0)
          _DFD_SUMMARY=$(echo "$_DFD_RESULTS" | "$JQ" -r '.summary // "unknown"' 2>/dev/null || echo "unknown")

          # Update story with dead feature detection results
          if [[ "$_DFD_TOTAL" -gt 0 ]]; then
            "$JQ" --arg id "$_story_id" \
              --argjson results "$_DFD_RESULTS" \
              '(.userStories[] | select(.id == $id) | ._deadFeatures) = $results' \
              "$PRD_FILE" >"$PRD_FILE.tmp" 2>/dev/null && mv "$PRD_FILE.tmp" "$PRD_FILE" || true

            if [[ "${SPIRAL_STRICT_DEAD_FEATURE:-false}" == "true" ]]; then
              # Hard block: story fails if dead features found
              echo "  [V] DFD FAIL: $_story_id — $_DFD_SUMMARY (SPIRAL_STRICT_DEAD_FEATURE=true)"
              _DFD_FAILED=1
              _VALIDATE_EXIT=1
            else
              # Soft warning: log but allow
              echo "  [V] DFD WARN: $_story_id — $_DFD_SUMMARY (soft warning)"
            fi
          elif [[ "$_DFD_TOTAL" -eq 0 ]]; then
            echo "  [V] DFD OK: $_story_id — 0 dead features"
          fi
        fi
      done
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

    # ── US-782: Attribution of newly-failed tests to the story (if baseline exists) ──
    if [[ "$_TEST_BASELINE_EXISTS" -eq 1 ]] && [[ -f "$_TEST_BASELINE_FILE" ]]; then
      echo "  [V] Attributing newly-failed tests to stories (US-782)..."

      # Find the freshest test report
      _NEW_REPORT_FILE=""
      if [[ -d "$SPIRAL_REPORTS_DIR" ]]; then
        _NEW_REPORT_FILE=$(find "$SPIRAL_REPORTS_DIR" -name "report.json" -type f | sort -r | head -1)
      fi

      if [[ -f "$_NEW_REPORT_FILE" ]]; then
        # Get list of changed files from the current story (if available)
        # This is populated by Ralph during Phase I
        _CHANGED_FILES_FILE="$SCRATCH_DIR/_changed_files_${SPIRAL_ITER}.txt"
        if [[ ! -f "$_CHANGED_FILES_FILE" && -n "$_ACTIVE_STORY_ID" ]]; then
          # Fallback: extract filesTouch from the story in prd.json
          "$JQ" -r --arg id "$_ACTIVE_STORY_ID" \
            '.userStories[] | select(.id == $id) | .filesTouch // [] | .[]' \
            "$PRD_FILE" >"$_CHANGED_FILES_FILE" 2>/dev/null || true
        fi

        if [[ -f "$_CHANGED_FILES_FILE" ]]; then
          _ATTRIBUTION_OUTPUT="$SCRATCH_DIR/attribution_iter_${SPIRAL_ITER}.json"

          # Run test_blame.py to attribute failures
          "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/test_blame.py" \
            --baseline-results "$_TEST_BASELINE_FILE" \
            --new-results "$_NEW_REPORT_FILE" \
            --changed-files "$_CHANGED_FILES_FILE" \
            --story-id "${_ACTIVE_STORY_ID:-unknown}" \
            --output "$_ATTRIBUTION_OUTPUT" 2>/dev/null || true

          if [[ -f "$_ATTRIBUTION_OUTPUT" ]]; then
            # Extract newly failed tests and update story's _failureReason
            _NEWLY_FAILED_TESTS=$("$JQ" -r '.newly_failed_tests | join(", ")' "$_ATTRIBUTION_OUTPUT" 2>/dev/null || echo "")
            if [[ -n "$_NEWLY_FAILED_TESTS" && -n "$_ACTIVE_STORY_ID" ]]; then
              # Update story's _failureReason field with broken test names
              "$JQ" --arg id "$_ACTIVE_STORY_ID" --arg reason "$_NEWLY_FAILED_TESTS" \
                '(.userStories[] | select(.id == $id) | ._failureReason) |= $reason' \
                "$PRD_FILE" >"$PRD_FILE.tmp" && mv "$PRD_FILE.tmp" "$PRD_FILE"
              echo "  [V] Attributed failures to story $_ACTIVE_STORY_ID: $_NEWLY_FAILED_TESTS"
            fi
            echo "  [V] Attribution report: $_ ATTRIBUTION_OUTPUT"
          fi
        fi
      fi
    fi

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

    # ── CodeQL deep semantic analysis (complements Semgrep pattern-matching) ──
    # Runs after tests pass as the "serious judge" for data-flow vulnerabilities.
    if [[ "${SPIRAL_CODEQL_ENABLED:-false}" == "true" ]]; then
      local _codeql_mode="${SPIRAL_CODEQL_MODE:-validate}"
      if [[ "$_codeql_mode" == "validate" || "$_codeql_mode" == "gate" ]]; then
        run_codeql_scan || echo "  [CodeQL] Findings detected — see gate-reports/codeql-*.sarif"
      fi
    fi

    # ── Dead Feature Detector (US-1006) ─────────────────────────────────────
    # After tests pass, scan newly added functions/classes for dead features.
    # A dead feature is a function/class defined but never imported/called.
    if [[ "$_VALIDATE_EXIT" -eq 0 ]]; then
      echo "  [V] Scanning for dead features in newly added code..."

      # For each newly passed story, run dead feature detection
      _DEAD_FEATURES_FOUND=0
      mapfile -t _NEWLY_PASSED_STORIES < <(
        "$JQ" -r '.userStories[] | select(.passes == true) | .id' "$PRD_FILE" 2>/dev/null || true
      ) || true

      for _story_id in "${_NEWLY_PASSED_STORIES[@]}"; do
        # Get filesTouch entries for this story
        _FILES_TOUCHED_STR=$("$JQ" -r --arg id "$_story_id" \
          '.userStories[] | select(.id == $id) | .filesTouch // [] | join(" ")' \
          "$PRD_FILE" 2>/dev/null || echo "")

        if [[ -n "$_FILES_TOUCHED_STR" ]]; then
          # Run dead feature detector
          _DEAD_FEATURES_RESULT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/dead_feature_detector.py" \
            --story-id "$_story_id" \
            --changed-files $_FILES_TOUCHED_STR \
            --repo-root "$REPO_ROOT" 2>&1 || echo '{"story_id":"'$_story_id'","total_features":0,"dead_features":[]}')

          # Extract dead features count
          _DEAD_COUNT=$(echo "$_DEAD_FEATURES_RESULT" | "$JQ" '.total_features // 0' 2>/dev/null || echo 0)

          # Store results in story _deadFeatures field
          if [[ "$_DEAD_COUNT" -gt 0 ]]; then
            "$JQ" --arg id "$_story_id" \
              --argjson results "$_DEAD_FEATURES_RESULT" \
              '(.userStories[] | select(.id == $id) | ._deadFeatures) = $results' \
              "$PRD_FILE" >"$PRD_FILE.tmp" 2>/dev/null && mv "$PRD_FILE.tmp" "$PRD_FILE" || true

            echo "  [V] Dead features detected in $_story_id: $_DEAD_COUNT features"
            _DEAD_FEATURES_FOUND=1
            log_spiral_event "phase_v_dead_features" \
              "\"story_id\":\"$_story_id\",\"count\":$_DEAD_COUNT,\"iteration\":$SPIRAL_ITER"

            # Hard block if SPIRAL_STRICT_DEAD_FEATURE is enabled
            if [[ "${SPIRAL_STRICT_DEAD_FEATURE:-false}" == "true" ]]; then
              echo "  [V] FAIL: Dead features detected and SPIRAL_STRICT_DEAD_FEATURE=true"
              _VALIDATE_EXIT=1
              break
            else
              echo "  [V] WARN: Dead features detected (soft warning; set SPIRAL_STRICT_DEAD_FEATURE=true to block)"
            fi
          fi
        fi
      done

      if [[ "$_DEAD_FEATURES_FOUND" -eq 1 && "_VALIDATE_EXIT" -eq 0 ]]; then
        log_spiral_event "phase_v_dead_features_warning" \
          "\"total_stories_checked\":${#_NEWLY_PASSED_STORIES[@]},\"iteration\":$SPIRAL_ITER"
      fi
    fi

    # ── Reachability Verifier (US-1007) ────────────────────────────────────────
    # After tests pass, verify that new Python modules for Phase stories are
    # actually called by spiral.sh or main.py. Prevents dead code that's wired up.
    if [[ "$_VALIDATE_EXIT" -eq 0 ]]; then
      echo "  [V] Reachability Verifier: checking new Phase modules are wired..."

      mapfile -t _NEWLY_PASSED_STORIES < <(
        "$JQ" -r '.userStories[] | select(.passes == true) | .id' "$PRD_FILE" 2>/dev/null || true
      ) || true

      for _story_id in "${_NEWLY_PASSED_STORIES[@]}"; do
        # Get story title
        _STORY_TITLE=$("$JQ" -r --arg id "$_story_id" \
          '.userStories[] | select(.id == $id) | .title' \
          "$PRD_FILE" 2>/dev/null || echo "")

        # Run reachability verifier (only checks Phase stories)
        _REACH_RESULT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/reachability_verifier.py" "$_STORY_TITLE" 2>&1 || echo "✗ Reachability check failed")

        # Update story with results
        if echo "$_REACH_RESULT" | grep -q "✓"; then
          echo "  [V] Reach OK: $_story_id ($_STORY_TITLE)"
          "$JQ" --arg id "$_story_id" \
            '(.userStories[] | select(.id == $id) | ._reachabilityCheck) = {"status":"pass"}' \
            "$PRD_FILE" >"$PRD_FILE.tmp" 2>/dev/null && mv "$PRD_FILE.tmp" "$PRD_FILE" || true
        else
          echo "  [V] Reach WARN: $_story_id — not a Phase story or no new modules"
        fi
      done
    fi

    # ── Evidence aggregator (US-1246) ──────────────────────────────────────
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/phase_v_evidence.py" \
      --prd "$PRD_FILE" \
      --out "$SCRATCH_DIR/evidence.json" 2>/dev/null || true

    # ── Granular verification evidence (US-1406) ─────────────────────────
    if [[ -f "$_TEST_OUTPUT_FILE" && -s "$_TEST_OUTPUT_FILE" ]]; then
      "$SPIRAL_PYTHON" -c "
from lib.phase_v_evidence import TestEvidenceAggregator; import sys
agg = TestEvidenceAggregator()
output = open(sys.argv[1], encoding='utf-8').read()
for sid in sys.argv[3:]:
    p = agg.aggregate(output, sid, sys.argv[2])
    print(f'  [V] Evidence: {p}')
" "$_TEST_OUTPUT_FILE" "$SCRATCH_DIR/verification_evidence" \
        $("$JQ" -r '.userStories[] | select(.passes == true) | .id' "$PRD_FILE" 2>/dev/null) 2>/dev/null || true
    fi

    write_checkpoint "$SPIRAL_ITER" "V"
  fi
  run_phase_hook POST "V" || true
  _PHASE_DUR_V=$(($(date +%s) - _PHASE_TS_V))
  log_spiral_event "phase_end" "\"phase\":\"V\",\"iteration\":$SPIRAL_ITER,\"duration_s\":$_PHASE_DUR_V"
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/observability/otel_spans.py" end-phase --phase V --duration-s "$_PHASE_DUR_V" --iteration "$SPIRAL_ITER" 2>/dev/null || true
  notify_webhook "V" "end"
}

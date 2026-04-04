#!/usr/bin/env bash
# lib/spiral_helpers.sh — SPIRAL helper functions sourced by spiral.sh
#
# Contains: write_iter_summary, _write_empty_test_output, write_checkpoint,
#           notify_webhook, run_phase_hook, checkpoint_phase_done,
#           run_sast_gate_check, scan_web_content, build_research_prompt
#
# All functions here depend on globals set by spiral.sh before sourcing.

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# ── Helper: write per-iteration summary JSON (US-039) ──────────────────────
# Writes $SCRATCH_DIR/_iteration_summary.json with compact iteration stats.
# Overwrites each iteration. Non-fatal on write failure.
write_iter_summary() {
  local _iter_end _iter_dur _attempted _failed _phases_json _sep _p _var
  _iter_end=$(date +%s)
  _iter_dur=$((_iter_end - ITER_START))

  # stories_passed = RALPH_PROGRESS (set in Phase I)
  # stories_attempted: count from results.tsv if available, else = stories_passed
  _attempted=${RALPH_PROGRESS:-0}
  if [[ -f "$REPO_ROOT/results.tsv" ]]; then
    local _tsv_count
    _tsv_count=$(awk -F'\t' -v iter="$SPIRAL_ITER" 'NR>1 && $2==iter' "$REPO_ROOT/results.tsv" | wc -l)
    _tsv_count=$((_tsv_count + 0)) # trim whitespace
    [[ "$_tsv_count" -gt "$_attempted" ]] && _attempted=$_tsv_count
  fi
  _failed=$((_attempted - ${RALPH_PROGRESS:-0}))

  # Build phases_completed from phase start timestamps
  _phases_json="["
  _sep=""
  for _p in R T M I V C; do
    _var="_PHASE_TS_${_p}"
    if [[ "${!_var:-0}" -gt 0 ]]; then
      _phases_json="${_phases_json}${_sep}\"${_p}\""
      _sep=","
    fi
  done
  _phases_json="${_phases_json}]"

  # US-212: Build phase_timings JSON: {R: {start_epoch, duration_seconds}, ...}
  local _phase_timings_json _ts_var _dur_var _ts_val _dur_val
  _phase_timings_json="{"
  _sep=""
  for _p in R T S M I V C; do
    _ts_var="_PHASE_TS_${_p}"
    _dur_var="_PHASE_DUR_${_p}"
    _ts_val="${!_ts_var:-0}"
    _dur_val="${!_dur_var:-0}"
    if [[ "$_ts_val" -gt 0 ]]; then
      _phase_timings_json="${_phase_timings_json}${_sep}\"${_p}\":{\"start_epoch\":${_ts_val},\"duration_seconds\":${_dur_val}}"
      _sep=","
    fi
  done
  _phase_timings_json="${_phase_timings_json}}"

  "$SPIRAL_PYTHON" -c "
import json, sys, os
d = {
    'iter': int(sys.argv[1]),
    'ts_start': int(sys.argv[2]),
    'ts_end': int(sys.argv[3]),
    'duration_sec': int(sys.argv[4]),
    'stories_attempted': int(sys.argv[5]),
    'stories_passed': int(sys.argv[6]),
    'stories_failed': int(sys.argv[7]),
    'phases_completed': json.loads(sys.argv[8]),
    'phase_v_skipped': sys.argv[10] == '1',
    'phase_r_pre_model': sys.argv[11] if sys.argv[11] != 'none' else None,
}
# US-241: merge _contextStats from ralph.sh observation masking if available
_ctx_stats_file = sys.argv[12] if len(sys.argv) > 12 else ''
if _ctx_stats_file and os.path.isfile(_ctx_stats_file):
    try:
        with open(_ctx_stats_file, encoding='utf-8') as _cf:
            _ctx = json.load(_cf)
        d['_contextStats'] = _ctx
    except Exception:
        pass
# US-212: merge phase_timings
_phase_timings_raw = sys.argv[13] if len(sys.argv) > 13 else '{}'
try:
    _phase_timings = json.loads(_phase_timings_raw)
    if _phase_timings:
        d['phase_timings'] = _phase_timings
except Exception:
    pass
# Remove None values to keep JSON clean
d = {k: v for k, v in d.items() if v is not None}
with open(sys.argv[9], 'w') as f:
    json.dump(d, f, indent=2)
    f.write('\n')
" "$SPIRAL_ITER" "$ITER_START" "$_iter_end" "$_iter_dur" \
    "$_attempted" "${RALPH_PROGRESS:-0}" "$_failed" \
    "$_phases_json" "$SCRATCH_DIR/_iteration_summary.json" "${_PHASE_V_SKIPPED:-0}" \
    "${_PHASE_R_PRE_MODEL:-none}" "${SCRATCH_DIR}/_context_stats.json" \
    "$_phase_timings_json" 2>/dev/null || {
    echo "  [C] WARNING: Failed to write _iteration_summary.json (non-fatal)"
  }
}

# ── Helper: write checkpoint ────────────────────────────────────────────────
# ── Helper: write empty test output in the configured format (US-367) ────────
# Uses $TEST_OUTPUT and $SPIRAL_TEST_OUTPUT_FORMAT (set before Phase T runs).
_write_empty_test_output() {
  if [[ "${SPIRAL_TEST_OUTPUT_FORMAT:-json}" == "yaml" ]]; then
    printf 'stories: []\n' >"$TEST_OUTPUT"
  else
    printf '{"stories":[]}\n' >"$TEST_OUTPUT"
  fi
}

write_checkpoint() {
  local iter="$1" phase="$2"
  # AC1: Atomic write via tmp + mv to prevent corruption if SIGINT fires mid-write
  local _ckpt_tmp
  _ckpt_tmp="${CHECKPOINT_FILE}.tmp.$$"
  printf '{"schema_version":1,"iter":%d,"phase":"%s","ts":"%s","run_id":"%s","spiralVersion":"%s","log_level":"%s","phaseDurations":{"R":%d,"T":%d,"M":%d,"I":%d,"V":%d,"C":%d}}\n' \
    "$iter" "$phase" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "${SPIRAL_RUN_ID:-}" \
    "${SPIRAL_VERSION:-unknown}" \
    "${SPIRAL_LOG_LEVEL:-INFO}" \
    "${_PHASE_DUR_R:-0}" "${_PHASE_DUR_T:-0}" "${_PHASE_DUR_M:-0}" \
    "${_PHASE_DUR_I:-0}" "${_PHASE_DUR_V:-0}" "${_PHASE_DUR_C:-0}" \
    >"$_ckpt_tmp" 2>/dev/null && mv "$_ckpt_tmp" "$CHECKPOINT_FILE" 2>/dev/null || true
}

<<<<<<< Updated upstream
# ── load_checkpoint: validate and load checkpoint with fallback to iter 1 ────
# Reads $CHECKPOINT_FILE, validates JSON structure, and populates CKPT_* vars.
# Returns 0 on success, 1 if no checkpoint exists or JSON is malformed.
# On malformed JSON, logs a warning and removes the corrupt file.
load_checkpoint() {
  [[ -f "$CHECKPOINT_FILE" ]] || return 1

  # Validate that the file contains parseable JSON
  if ! "$JQ" -e '.' "$CHECKPOINT_FILE" >/dev/null 2>&1; then
    echo "  [checkpoint] WARNING: Malformed JSON in checkpoint — starting fresh from iter 1" >&2
=======
# ── Helper: load and validate checkpoint (AC2 of US-1106) ────────────────────
# Reads $CHECKPOINT_FILE, validates JSON structure, and sets globals.
# Returns 0 on success (sets CKPT_ITER, CKPT_PHASE, SPIRAL_ITER, SPIRAL_RUN_ID).
# Returns 1 if no checkpoint, malformed JSON, or missing iter field (resets to iter 1).
load_checkpoint() {
  [[ -f "$CHECKPOINT_FILE" ]] || return 1

  local _raw
  _raw=$(cat "$CHECKPOINT_FILE" 2>/dev/null) || {
    echo "  [checkpoint] WARNING: Cannot read checkpoint — resetting to iteration 1" >&2
    rm -f "$CHECKPOINT_FILE"
    return 1
  }

  # Validate JSON — reject truncated/corrupt files (simulated crash scenario)
  if ! echo "$_raw" | "$JQ" -e . >/dev/null 2>&1; then
    echo "  [checkpoint] WARNING: Malformed JSON in checkpoint — resetting to iteration 1" >&2
>>>>>>> Stashed changes
    rm -f "$CHECKPOINT_FILE"
    return 1
  fi

<<<<<<< Updated upstream
  CKPT_ITER=$("$JQ" -r '.iter // 0' "$CHECKPOINT_FILE" 2>/dev/null) || CKPT_ITER=""
  CKPT_PHASE=$("$JQ" -r '.phase // ""' "$CHECKPOINT_FILE" 2>/dev/null) || CKPT_PHASE=""

  # Validate iter is a non-negative integer
  if [[ ! "$CKPT_ITER" =~ ^[0-9]+$ ]]; then
    echo "  [checkpoint] WARNING: Checkpoint has invalid iter ('$CKPT_ITER') — starting fresh from iter 1" >&2
=======
  # Validate required 'iter' field is a non-negative integer
  local _ckpt_iter _ckpt_phase
  _ckpt_iter=$(echo "$_raw" | "$JQ" -r '.iter // empty' 2>/dev/null) || _ckpt_iter=""
  _ckpt_phase=$(echo "$_raw" | "$JQ" -r '.phase // empty' 2>/dev/null) || _ckpt_phase=""
  if [[ -z "$_ckpt_iter" ]] || ! [[ "$_ckpt_iter" =~ ^[0-9]+$ ]]; then
    echo "  [checkpoint] WARNING: Checkpoint missing 'iter' field — resetting to iteration 1" >&2
>>>>>>> Stashed changes
    rm -f "$CHECKPOINT_FILE"
    return 1
  fi

<<<<<<< Updated upstream
  # Validate phase is non-empty
  if [[ -z "$CKPT_PHASE" ]]; then
    echo "  [checkpoint] WARNING: Checkpoint has empty phase field — starting fresh from iter 1" >&2
    rm -f "$CHECKPOINT_FILE"
    return 1
  fi

  CKPT_RUN_ID=$("$JQ" -r '.run_id // ""' "$CHECKPOINT_FILE" 2>/dev/null || echo "")
  CKPT_TS=$("$JQ" -r '.ts // 0' "$CHECKPOINT_FILE" 2>/dev/null || echo 0)
  CKPT_SPIRAL_VERSION=$("$JQ" -r '.spiralVersion // ""' "$CHECKPOINT_FILE" 2>/dev/null || echo "")
=======
  # Valid checkpoint — export globals
  CKPT_ITER="$_ckpt_iter"
  CKPT_PHASE="${_ckpt_phase:-}"
  echo "  [checkpoint] Resuming from iter=$CKPT_ITER phase=$CKPT_PHASE"
  SPIRAL_ITER=$((CKPT_ITER - 1)) # loop will increment to CKPT_ITER on first pass

  # Restore run_id from checkpoint so all events share the same correlation ID
  local _ckpt_run_id
  _ckpt_run_id=$(echo "$_raw" | "$JQ" -r '.run_id // empty' 2>/dev/null) || _ckpt_run_id=""
  if [[ -n "$_ckpt_run_id" ]]; then
    SPIRAL_RUN_ID="$_ckpt_run_id"
    export SPIRAL_RUN_ID
  fi

  # Warn if checkpoint is older than 24 hours
  local _ckpt_ts _ckpt_age
  _ckpt_ts=$(echo "$_raw" | "$JQ" -r '.ts // 0' 2>/dev/null) || _ckpt_ts=0
  _ckpt_age=$(($(date +%s) - ${_ckpt_ts%.*}))
  if [[ "$_ckpt_age" -gt 86400 ]]; then
    local _age_hours=$((_ckpt_age / 3600))
    echo "  [spiral] WARNING: Resuming from checkpoint written ${_age_hours}h ago. Pass --reset to start fresh." >&2
  fi

  # Warn if SPIRAL version changed since checkpoint was written
  local _ckpt_version
  _ckpt_version=$(echo "$_raw" | "$JQ" -r '.spiralVersion // empty' 2>/dev/null) || _ckpt_version=""
  if [[ -n "$_ckpt_version" && "$_ckpt_version" != "${SPIRAL_VERSION:-unknown}" ]]; then
    echo "  [checkpoint] WARNING: checkpoint written by SPIRAL $_ckpt_version, current is ${SPIRAL_VERSION:-unknown}" >&2
  fi

  echo ""
>>>>>>> Stashed changes
  return 0
}

# ── Helper: POST a JSON notification to SPIRAL_NOTIFY_WEBHOOK (US-100) ──────
# Usage: notify_webhook PHASE EVENT [STATUS] [EXTRA_FIELDS]
#   PHASE:        R, T, M, G, I, V, C
#   EVENT:        start | end
#   STATUS:       ok | failed | skipped  (default: ok)
#   EXTRA_FIELDS: additional jq-compatible key=value pairs (optional)
# Non-fatal: logs a warning on failure and returns 0.
notify_webhook() {
  [[ -z "${SPIRAL_NOTIFY_WEBHOOK:-}" ]] && return 0
  local phase="$1" event="$2" status="${3:-ok}" extra_arg="${4:-}"
  local ts body curl_args=()
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  # Build JSON body using jq for correct escaping
  body="$("$JQ" -n \
    --arg run_id "${SPIRAL_RUN_ID:-}" \
    --arg phase "$phase" \
    --arg event "$event" \
    --arg status "$status" \
    --arg ts "$ts" \
    --argjson iter "${SPIRAL_ITER:-0}" \
    '{run_id: $run_id, phase: $phase, event: $event, status: $status, timestamp_iso: $ts, iteration: $iter}' 2>/dev/null)" || {
    echo "  [webhook] WARNING: Failed to build JSON body (non-fatal)" >&2
    return 0
  }
  # Merge extra fields (e.g., gate_report_path) if provided
  if [[ -n "$extra_arg" ]]; then
    body="$("$JQ" --argjson x "{$extra_arg}" '. + $x' <<<"$body" 2>/dev/null || echo "$body")"
  fi
  # Build curl args
  curl_args=(-s -o /dev/null --max-time "${SPIRAL_NOTIFY_WEBHOOK_TIMEOUT:-5}"
    -X POST -H "Content-Type: application/json" -d "$body")
  if [[ -n "${SPIRAL_NOTIFY_WEBHOOK_HEADERS:-}" ]]; then
    curl_args+=(-H "$SPIRAL_NOTIFY_WEBHOOK_HEADERS")
  fi
  # HMAC-SHA256 signing (US-207): add X-Spiral-Signature-256 header when secret is set
  if [[ -n "${SPIRAL_NOTIFY_WEBHOOK_SECRET:-}" ]]; then
    local _sig
    _sig="$("$SPIRAL_PYTHON" -c "
import hmac, hashlib, sys
key = sys.argv[1].encode()
body = sys.argv[2].encode()
print('sha256=' + hmac.new(key, body, hashlib.sha256).hexdigest())
" "$SPIRAL_NOTIFY_WEBHOOK_SECRET" "$body" 2>/dev/null)" || _sig=""
    if [[ -n "$_sig" ]]; then
      curl_args+=(-H "X-Spiral-Signature-256: $_sig")
    fi
  fi
  curl_args+=("$SPIRAL_NOTIFY_WEBHOOK")
  if ! curl "${curl_args[@]}" 2>/dev/null; then
    echo "  [webhook] WARNING: POST to SPIRAL_NOTIFY_WEBHOOK failed (non-fatal)" >&2
  fi
}

# ── Phase hook runner (US-132) ─────────────────────────────────────────────────
# Usage: run_phase_hook PRE|POST PHASE
# Executes SPIRAL_PRE_PHASE_HOOK (PRE) or SPIRAL_POST_PHASE_HOOK (POST).
# Exports SPIRAL_CURRENT_PHASE, SPIRAL_CURRENT_STORY_ID, SPIRAL_RUN_ID, SPIRAL_ITERATION.
# PRE hooks: non-zero exit = caller should abort current story attempt (continue).
# POST hooks: non-zero exit = warning logged; execution continues.
# Returns the hook's exit code (0 if hook is unset or not executable).
run_phase_hook() {
  local hook_type="$1" # PRE or POST
  local phase="$2"
  local hook_path event_type
  if [[ "$hook_type" == "PRE" ]]; then
    hook_path="${SPIRAL_PRE_PHASE_HOOK:-}"
    event_type="phase_hook_pre"
  else
    hook_path="${SPIRAL_POST_PHASE_HOOK:-}"
    event_type="phase_hook_post"
  fi
  [[ -z "$hook_path" ]] && return 0
  if [[ ! -x "$hook_path" ]]; then
    echo "  [hook] WARNING: $event_type '$hook_path' is not executable — skipping" >&2
    return 0
  fi
  # Export context for the hook script
  export SPIRAL_CURRENT_PHASE="$phase"
  export SPIRAL_CURRENT_STORY_ID="${_NEXT_SID:-}"
  export SPIRAL_ITERATION="${SPIRAL_ITER:-0}"
  local _hook_ts _hook_rc=0
  _hook_ts=$(date +%s)
  timeout "${SPIRAL_HOOK_TIMEOUT:-30}" "$hook_path" || _hook_rc=$?
  local _hook_dur=$(($(date +%s) - _hook_ts))
  log_spiral_event "$event_type" \
    "\"phase\":\"$phase\",\"hook\":\"$hook_path\",\"exit_code\":$_hook_rc,\"duration_s\":$_hook_dur,\"iteration\":${SPIRAL_ITER:-0}"
  if [[ "$_hook_rc" -ne 0 ]]; then
    if [[ "$hook_type" == "PRE" ]]; then
      echo "  [hook] pre-phase $phase hook exited $_hook_rc — aborting story attempt" >&2
    else
      echo "  [hook] post-phase $phase hook exited $_hook_rc (non-fatal)" >&2
    fi
  fi
  return $_hook_rc
}

# ── Helper: returns 0 if current iter already completed this phase ───────────
checkpoint_phase_done() {
  local phase="$1"
  # US-182: R and T have independent marker files so parallel resume skips only what finished
  if [[ "$phase" == "R" && -f "$SCRATCH_DIR/_phase_R_${SPIRAL_ITER}.ckpt" ]]; then
    return 0
  fi
  if [[ "$phase" == "T" && -f "$SCRATCH_DIR/_phase_T_${SPIRAL_ITER}.ckpt" ]]; then
    return 0
  fi
  [[ -f "$CHECKPOINT_FILE" ]] || return 1
  local ckpt_iter ckpt_phase
  ckpt_iter=$("$JQ" -r '.iter // 0' "$CHECKPOINT_FILE" 2>/dev/null) || ckpt_iter=""
  ckpt_phase=$("$JQ" -r '.phase // ""' "$CHECKPOINT_FILE" 2>/dev/null) || ckpt_phase=""
  # Guard: if jq failed or returned non-numeric, treat as no checkpoint
  [[ "$ckpt_iter" =~ ^[0-9]+$ ]] || return 1
  [[ "$ckpt_iter" -eq "$SPIRAL_ITER" ]] || return 1
  # Phase order: A R T S E M X G I V C
  local -A PHASE_ORDER=([A]=1 [R]=2 [T]=3 [S]=4 [E]=5 [M]=6 [X]=7 [G]=8 [I]=9 [V]=10 [C]=11)
  [[ "${PHASE_ORDER[$ckpt_phase]:-0}" -ge "${PHASE_ORDER[$phase]:-0}" ]]
}

# ── US-262: SAST gate check — run Semgrep on story-branch diff ───────────────
# Scans files changed vs origin/main for each pending story.
# HIGH/CRITICAL → story blocked; MEDIUM → warning in _sast_warnings.
# Results written to $SCRATCH_DIR/gate-reports/<story-id>_sast.json.
# Returns: 0 = all pass/warn, 1 = at least one story blocked.
run_sast_gate_check() {
  if [[ "${SPIRAL_SAST_ENABLED:-true}" == "false" ]]; then
    echo "  [SAST] Disabled (SPIRAL_SAST_ENABLED=false) — skipping"
    return 0
  fi

  if ! command -v semgrep >/dev/null 2>&1; then
    echo "  [SAST] semgrep not found in PATH — skipping (install semgrep to enable)"
    return 0
  fi

  local gate_reports_dir="$SCRATCH_DIR/gate-reports"
  mkdir -p "$gate_reports_dir"

  # Get list of changed files vs origin/main
  local changed_files
  changed_files=$(git diff --name-only origin/main 2>/dev/null || true)
  if [[ -z "$changed_files" ]]; then
    echo "  [SAST] No changed files vs origin/main — skipping"
    return 0
  fi

  # Get pending story IDs
  local pending_ids
  pending_ids=$("$JQ" -r '.userStories[] | select(.passes != true) | .id' "$PRD_FILE" 2>/dev/null)
  if [[ -z "$pending_ids" ]]; then
    echo "  [SAST] No pending stories — skipping"
    return 0
  fi

  local any_blocked=0

  echo "  [SAST] Scanning $(echo "$changed_files" | wc -l | tr -d ' ') changed files with Semgrep..."

  # Run a single scan over all changed files, then attribute per-story
  local scan_report="$gate_reports_dir/_sast_scan.json"
  # shellcheck disable=SC2086
  semgrep scan --config auto --json --output="$scan_report" $changed_files >/dev/null 2>&1 || true

  if [[ ! -f "$scan_report" ]]; then
    echo "  [SAST] Semgrep produced no output — skipping"
    return 0
  fi

  local high_count medium_count
  high_count=$("$JQ" '[.results[] | select(.extra.severity == "ERROR" or .extra.severity == "CRITICAL")] | length' "$scan_report" 2>/dev/null || echo "0")
  medium_count=$("$JQ" '[.results[] | select(.extra.severity == "WARNING")] | length' "$scan_report" 2>/dev/null || echo "0")

  # Write per-story report (copy the full scan — all findings are from story branch)
  while IFS= read -r sid; do
    [[ -z "$sid" ]] && continue
    local story_report="$gate_reports_dir/${sid}_sast.json"
    cp "$scan_report" "$story_report"

    if [[ "${high_count:-0}" -gt 0 ]]; then
      echo "  [SAST] FAIL: $high_count HIGH/CRITICAL finding(s) — blocking story $sid"
      # Set story status to blocked-by-sast
      "$JQ" --arg sid "$sid" \
        '(.userStories[] | select(.id == $sid)) |= . + {"_sast_status": "blocked-by-sast"}' \
        "$PRD_FILE" >"${PRD_FILE}.sast.tmp" && mv "${PRD_FILE}.sast.tmp" "$PRD_FILE"
      any_blocked=1
    elif [[ "${medium_count:-0}" -gt 0 ]]; then
      echo "  [SAST] WARN: $medium_count MEDIUM finding(s) for story $sid (non-blocking)"
      # Add _sast_warnings to story
      local warnings
      warnings=$("$JQ" '[.results[] | select(.extra.severity == "WARNING") | {rule: .check_id, file: .path, line: .start.line, message: .extra.message}]' "$scan_report" 2>/dev/null || echo "[]")
      "$JQ" --arg sid "$sid" --argjson warnings "$warnings" \
        '(.userStories[] | select(.id == $sid)) |= . + {"_sast_warnings": $warnings, "_sast_status": "warn"}' \
        "$PRD_FILE" >"${PRD_FILE}.sast.tmp" && mv "${PRD_FILE}.sast.tmp" "$PRD_FILE"
    else
      echo "  [SAST] PASS: No findings for story $sid"
      "$JQ" --arg sid "$sid" \
        '(.userStories[] | select(.id == $sid)) |= . + {"_sast_status": "pass"}' \
        "$PRD_FILE" >"${PRD_FILE}.sast.tmp" && mv "${PRD_FILE}.sast.tmp" "$PRD_FILE"
    fi
  done <<<"$pending_ids"

  log_spiral_event "sast_gate_check" "\"iteration\":$SPIRAL_ITER,\"high\":${high_count:-0},\"medium\":${medium_count:-0},\"blocked\":$any_blocked"

  rm -f "$scan_report"
  return "$any_blocked"
}

# ── Helper: CodeQL deep semantic analysis ────────────────────────────────────
# Runs CodeQL CLI as a "serious judge" scan after Phase V tests pass.
# Complements Semgrep (fast pattern-matching) with deeper data-flow analysis
# that catches variant-style vulnerabilities autonomous code may generate.
#
# Modes:
#   SPIRAL_CODEQL_MODE=validate  — run every iteration in Phase V (default)
#   SPIRAL_CODEQL_MODE=gate      — run only in Phase G gate check
#   SPIRAL_CODEQL_MODE=nightly   — skip unless SPIRAL_CODEQL_FORCE=true
#
# Returns: 0 = pass/warn, 1 = HIGH/CRITICAL findings (blocks if SPIRAL_CODEQL_BLOCKING=true)
run_codeql_scan() {
  if [[ "${SPIRAL_CODEQL_ENABLED:-false}" == "false" ]]; then
    return 0
  fi

  if ! command -v codeql >/dev/null 2>&1; then
    echo "  [CodeQL] codeql CLI not found in PATH — skipping (install: gh extension install github/gh-codeql)"
    return 0
  fi

  local mode="${SPIRAL_CODEQL_MODE:-validate}"
  if [[ "$mode" == "nightly" && "${SPIRAL_CODEQL_FORCE:-false}" != "true" ]]; then
    echo "  [CodeQL] Skipping (mode=nightly, set SPIRAL_CODEQL_FORCE=true to run)"
    return 0
  fi

  # Determine languages to scan
  local languages="${SPIRAL_CODEQL_LANGUAGES:-python}"
  local query_suite="${SPIRAL_CODEQL_QUERY_SUITE:-security-and-quality}"
  local severity_threshold="${SPIRAL_CODEQL_SEVERITY:-error}"
  local codeql_db_dir="$SCRATCH_DIR/codeql-db"
  local codeql_results="$SCRATCH_DIR/gate-reports/codeql-results.sarif"
  local codeql_csv="$SCRATCH_DIR/gate-reports/codeql-results.csv"

  mkdir -p "$SCRATCH_DIR/gate-reports"

  # Get changed files for targeted scan
  local changed_files
  changed_files=$(git diff --name-only HEAD~1 2>/dev/null || git diff --name-only origin/main 2>/dev/null || true)
  if [[ -z "$changed_files" ]]; then
    echo "  [CodeQL] No changed files — skipping"
    return 0
  fi

  local file_count
  file_count=$(echo "$changed_files" | wc -l | tr -d ' ')
  echo "  [CodeQL] Scanning $file_count changed files (suite: $query_suite, languages: $languages)..."

  local _codeql_start
  _codeql_start=$(date +%s)
  local any_critical=0

  # Process each language
  local lang
  for lang in $languages; do
    local db_path="$codeql_db_dir/$lang"
    local sarif_path="$SCRATCH_DIR/gate-reports/codeql-${lang}.sarif"

    # Create CodeQL database
    echo "  [CodeQL] Creating $lang database..."
    rm -rf "$db_path" 2>/dev/null || true
    if ! codeql database create "$db_path" \
      --language="$lang" \
      --source-root="$REPO_ROOT" \
      --overwrite \
      --threads=0 2>/dev/null; then
      echo "  [CodeQL] WARNING: Database creation failed for $lang — skipping"
      continue
    fi

    # Run analysis
    echo "  [CodeQL] Analyzing $lang with $query_suite queries..."
    if ! codeql database analyze "$db_path" \
      --format=sarifv2.1.0 \
      --output="$sarif_path" \
      --threads=0 \
      "codeql/${lang}-queries:codeql-suites/${lang}-${query_suite}.qls" 2>/dev/null; then
      echo "  [CodeQL] WARNING: Analysis failed for $lang — skipping"
      continue
    fi

    if [[ ! -f "$sarif_path" ]]; then
      echo "  [CodeQL] No SARIF output for $lang — skipping"
      continue
    fi

    # Parse results
    local high_count medium_count low_count total_count
    high_count=$("$JQ" '[.runs[].results[] | select(.level == "error")] | length' "$sarif_path" 2>/dev/null || echo "0")
    medium_count=$("$JQ" '[.runs[].results[] | select(.level == "warning")] | length' "$sarif_path" 2>/dev/null || echo "0")
    low_count=$("$JQ" '[.runs[].results[] | select(.level == "note")] | length' "$sarif_path" 2>/dev/null || echo "0")
    total_count=$("$JQ" '[.runs[].results[]] | length' "$sarif_path" 2>/dev/null || echo "0")

    if [[ "${high_count:-0}" -gt 0 ]]; then
      echo "  [CodeQL] FAIL ($lang): $high_count error(s), $medium_count warning(s), $low_count note(s)"
      # Extract top findings for log
      "$JQ" -r '.runs[].results[] | select(.level == "error") | "    → \(.ruleId): \(.message.text[0:120]) (\(.locations[0].physicalLocation.artifactLocation.uri // "unknown"):\(.locations[0].physicalLocation.region.startLine // "?"))"' \
        "$sarif_path" 2>/dev/null | head -5
      any_critical=1
    elif [[ "${medium_count:-0}" -gt 0 ]]; then
      echo "  [CodeQL] WARN ($lang): $medium_count warning(s), $low_count note(s) (non-blocking)"
    else
      echo "  [CodeQL] PASS ($lang): No findings ($total_count results at note level)"
    fi
  done

  local _codeql_dur=$(($(date +%s) - _codeql_start))
  echo "  [CodeQL] Scan completed in ${_codeql_dur}s"

  log_spiral_event "codeql_scan" "\"iteration\":$SPIRAL_ITER,\"duration_s\":$_codeql_dur,\"critical\":$any_critical,\"languages\":\"$languages\",\"suite\":\"$query_suite\""

  # Block if critical findings and blocking mode is on
  if [[ "$any_critical" -eq 1 && "${SPIRAL_CODEQL_BLOCKING:-false}" == "true" ]]; then
    echo "  [CodeQL] BLOCKED: HIGH/CRITICAL findings detected (set SPIRAL_CODEQL_BLOCKING=false to warn-only)"
    return 1
  fi

  # Clean up database (can be large)
  if [[ "${SPIRAL_CODEQL_KEEP_DB:-false}" != "true" ]]; then
    rm -rf "$codeql_db_dir" 2>/dev/null || true
  fi

  return 0
}

# ── Helper: scan text for prompt injection via LLM Guard (US-198) ────────────
# Usage: scan_web_content <text_var_name> <source_label>
# Reads the named variable, scans it, and updates the variable in-place.
# Logs the scan result to spiral_events.jsonl. Returns 0 always (non-fatal).
scan_web_content() {
  local var_name="$1"
  local source_label="$2"
  local content="${!var_name}"

  [[ -z "$content" ]] && return 0

  local scan_result scan_json
  scan_result=$(
    export SPIRAL_INJECTION_THRESHOLD
    printf '%s' "$content" |
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/llm_guard_scanner.py" \
        --source "$source_label" \
        --threshold "$SPIRAL_INJECTION_THRESHOLD" \
        --output json 2>/dev/null
  ) || {
    echo "  [R] llm-guard scan skipped (scanner unavailable) — source: $source_label" >&2
    return 0
  }

  [[ -z "$scan_result" ]] && return 0

  local truncated score
  truncated=$(printf '%s' "$scan_result" | "$JQ" -r '.truncated' 2>/dev/null || echo "false")
  score=$(printf '%s' "$scan_result" | "$JQ" -r '.score' 2>/dev/null || echo "0")

  # Update the caller's variable with sanitized text
  local sanitized_text
  sanitized_text=$(printf '%s' "$scan_result" | "$JQ" -r '.text' 2>/dev/null)
  if [[ -n "$sanitized_text" ]]; then
    printf -v "$var_name" '%s' "$sanitized_text"
  fi

  # Log the scan event
  scan_json=$(printf '%s' "$scan_result" |
    "$JQ" -c '{score:.score,threshold:.threshold,truncated:.truncated,source:.source,duration_ms:.duration_ms}' 2>/dev/null || true)
  log_spiral_event "phase_r_injection_scan" \
    "\"source\":\"$source_label\",\"score\":$score,\"threshold\":\"${SPIRAL_INJECTION_THRESHOLD}\",\"truncated\":$truncated,\"iteration\":$SPIRAL_ITER"

  if [[ "$truncated" == "true" ]]; then
    echo "  [R] llm-guard: BLOCKED injection in $source_label (score=$score, threshold=$SPIRAL_INJECTION_THRESHOLD)"
  else
    echo "  [R] llm-guard: OK $source_label (score=$score)"
  fi
  return 0
}

# ── Helper: inject placeholders into research prompt ─────────────────────────
build_research_prompt() {
  local iter="$1"
  local output_path="$2"

  local next_id_num
  next_id_num=$("$JQ" "[.userStories[].id | ltrimstr(\"${SPIRAL_STORY_PREFIX}-\") | tonumber] | max + 1" "$PRD_FILE")

  local existing_titles
  existing_titles=$("$JQ" -r '[.userStories[].title] | join("\n- ")' "$PRD_FILE")

  local pending_titles
  pending_titles=$("$JQ" -r '[.userStories[] | select(.passes != true) | .title] | join("\n- ")' "$PRD_FILE")

  # Build injected prompt via sed substitutions
  local prompt_content
  prompt_content=$(cat "$SPIRAL_RESEARCH_PROMPT")
  prompt_content="${prompt_content//__SPIRAL_ITER__/$iter}"
  prompt_content="${prompt_content//__NEXT_ID_NUM__/$next_id_num}"
  prompt_content="${prompt_content//__OUTPUT_PATH__/$output_path}"
  prompt_content="${prompt_content//__STORY_PREFIX__/$SPIRAL_STORY_PREFIX}"
  local focus_section=""
  if [[ -n "$SPIRAL_FOCUS" ]]; then
    focus_section="## FOCUS DIRECTIVE\n\n**This iteration is scoped to: \"$SPIRAL_FOCUS\"**\n\nYou MUST only discover stories directly related to this theme. Skip any story that does not clearly improve or relate to \"$SPIRAL_FOCUS\". When in doubt, omit rather than include."
  fi

  # Extract goals + overview from prd.json (if present)
  local goals_section=""
  local goals_json
  goals_json=$("$JQ" -r '
    if ((.goals // []) | length) > 0 then
      "Overview: " + (.overview // "N/A") + "\n\nGoals:\n" +
      ([.goals[] | "- " + .] | join("\n"))
    else "" end
  ' "$PRD_FILE" 2>/dev/null || echo "")
  if [[ -n "$goals_json" ]]; then
    goals_section="## Project Goals (from prd.json)\n\nEvery story you propose MUST serve at least one of these goals.\n\n${goals_json}"
  fi

  # Replace __EXISTING_TITLES__, __PENDING_TITLES__, __SPIRAL_FOCUS_SECTION__, and __SPIRAL_GOALS_SECTION__ placeholders
  printf '%s' "$prompt_content" |
    awk -v existing="$existing_titles" -v pending="$pending_titles" -v focus="$focus_section" -v goals="$goals_section" \
      '{gsub(/__EXISTING_TITLES__/, existing); gsub(/__PENDING_TITLES__/, pending); gsub(/__SPIRAL_FOCUS_SECTION__/, focus); gsub(/__SPIRAL_GOALS_SECTION__/, goals); print}'
}

# ── Helper functions (moved from spiral.sh) ──────────────────────────────

# ── Helper: per-story complexity-based timeout ───────────────────────────────
# Returns the wall-clock timeout (seconds) to use for a single ralph invocation
# based on the story's estimatedComplexity field in prd.json.
# Falls back to SPIRAL_IMPL_TIMEOUT when story_id is empty or not found.
get_story_timeout() {
  local story_id="${1:-}"
  local prd="${2:-${PRD_FILE:-prd.json}}"
  if [[ -z "$story_id" ]]; then
    echo "${SPIRAL_IMPL_TIMEOUT:-600}"
    return
  fi
  local complexity
  complexity=$("$JQ" -r --arg id "$story_id" \
    '.userStories[] | select(.id == $id) | .estimatedComplexity // "medium"' \
    "$prd" 2>/dev/null | tr -d '\r' || echo "medium")
  case "$complexity" in
    small) echo ${SPIRAL_STORY_TIMEOUT_SMALL:-600} ;;
    large) echo ${SPIRAL_STORY_TIMEOUT_LARGE:-1200} ;;
    *) echo ${SPIRAL_STORY_TIMEOUT_MEDIUM:-900} ;;
  esac
}

# ── Helper: stats from prd.json ─────────────────────────────────────────────
prd_stats() {
  TOTAL=$("$JQ" '[.userStories | length] | .[0]' "$PRD_FILE")
  DONE=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE")
  # Exclude manually-skipped stories from pending count
  if [[ -n "$SPIRAL_SKIP_STORY_IDS" ]]; then
    local _manual_skip_count
    _manual_skip_count=$("$JQ" --arg ids "$SPIRAL_SKIP_STORY_IDS" \
      '[.userStories[] | select(.passes != true) | select(.id as $sid | ($ids | split(",") | map(gsub("^\\s+|\\s+$";"")) | any(. == $sid)))] | length' \
      "$PRD_FILE" 2>/dev/null || echo 0)
    PENDING=$((TOTAL - DONE - _manual_skip_count))
  else
    PENDING=$((TOTAL - DONE))
  fi
}

# ── Helper: create annotated git tag on successful run completion (US-137) ──
# Creates tag spiral/run-{SPIRAL_RUN_ID}-complete with run metadata.
# Controlled by SPIRAL_CREATE_TAGS=true (default: false).
create_run_tag() {
  [[ "${SPIRAL_CREATE_TAGS:-false}" != "true" ]] && return 0

  local tag_name="spiral/run-${SPIRAL_RUN_ID}-complete"
  local ts story_count commit_sha annotation
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  story_count=$("$JQ" '[.userStories[] | select(.passes == true)] | length' "$PRD_FILE" 2>/dev/null || echo "0")
  commit_sha=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")

  annotation="$(printf 'SPIRAL run complete: %s stories in %s iterations\nRun ID: %s\nDuration: %sm\nFinal commit: %s\nCompleted: %s' \
    "$story_count" "$SPIRAL_ITER" "$SPIRAL_RUN_ID" "${SESSION_MINUTES:-0}" "$commit_sha" "$ts")"

  echo "  [tag] Creating annotated tag: $tag_name"
  if git -C "$REPO_ROOT" tag -a "$tag_name" -m "$annotation" --force 2>/dev/null; then
    echo "  [tag] Tag created: $tag_name"
    log_spiral_event "run_complete_tagged" \
      "\"tag\":\"$tag_name\",\"stories\":$story_count,\"iterations\":$SPIRAL_ITER,\"duration_min\":${SESSION_MINUTES:-0},\"commit\":\"$commit_sha\",\"pushed\":false"
    if [[ "${SPIRAL_AUTO_PUSH_TAGS:-false}" == "true" ]]; then
      if git -C "$REPO_ROOT" push origin "$tag_name" 2>/dev/null; then
        echo "  [tag] Tag pushed to origin"
        log_spiral_event "run_complete_tagged" \
          "\"tag\":\"$tag_name\",\"stories\":$story_count,\"iterations\":$SPIRAL_ITER,\"duration_min\":${SESSION_MINUTES:-0},\"commit\":\"$commit_sha\",\"pushed\":true"
      else
        echo "  [tag] WARNING: Tag push to origin failed"
      fi
    fi
  else
    echo "  [tag] WARNING: Tag creation failed for $tag_name"
  fi
}

# ── Helper: cleanup workspace artifacts after successful run (US-136) ───────
# Prunes transient .spiral/ artifacts: expired research cache, old iteration
# summaries (keeps 5 most-recent), and zero-byte log files.
# Controlled by SPIRAL_WORKSPACE_CLEANUP=true (default: false).
cleanup_workspace() {
  [[ "${SPIRAL_WORKSPACE_CLEANUP:-false}" != "true" ]] && return 0

  local spiral_dir="$SCRATCH_DIR"
  echo "  [cleanup] Running workspace cleanup..."

  # Measure size before
  local bytes_before=0
  if command -v du &>/dev/null; then
    bytes_before=$(du -sb "$spiral_dir" 2>/dev/null | awk '{print $1}' || echo 0)
  fi

  # 1. Remove research_cache entries older than SPIRAL_CACHE_TTL days
  local cache_dir="$spiral_dir/research_cache"
  if [[ -d "$cache_dir" ]]; then
    find "$cache_dir" -maxdepth 1 -type f -mtime +"${SPIRAL_CACHE_TTL:-7}" -delete 2>/dev/null || true
    echo "  [cleanup] Pruned research_cache entries older than ${SPIRAL_CACHE_TTL:-7} days"
  fi

  # 2. Archive iteration summary JSONs, keeping the 5 most recent
  local summary_files
  summary_files=$(ls -t "$spiral_dir"/_iteration_summary_*.json 2>/dev/null || true)
  if [[ -n "$summary_files" ]]; then
    local old_summaries
    old_summaries=$(echo "$summary_files" | tail -n +6)
    if [[ -n "$old_summaries" ]]; then
      mkdir -p "$spiral_dir/archive"
      local archive_name="$spiral_dir/archive/iter_summaries_$(date +%Y%m%d_%H%M%S).tar.gz"
      echo "$old_summaries" | tr '\n' '\0' | xargs -0 tar -czf "$archive_name" 2>/dev/null || true
      echo "$old_summaries" | tr '\n' '\0' | xargs -0 rm -f 2>/dev/null || true
      echo "  [cleanup] Archived old iteration summaries to $(basename "$archive_name")"
    fi
  fi

  # 3. Remove zero-byte log files
  find "$spiral_dir" -maxdepth 1 -name "*.log" -size 0 -delete 2>/dev/null || true
  echo "  [cleanup] Removed zero-byte log files"

  # Measure size after and compute bytes freed
  local bytes_after=0
  if command -v du &>/dev/null; then
    bytes_after=$(du -sb "$spiral_dir" 2>/dev/null | awk '{print $1}' || echo 0)
  fi
  local bytes_freed=$((bytes_before - bytes_after))
  [[ $bytes_freed -lt 0 ]] && bytes_freed=0

  echo "  [cleanup] Workspace cleanup complete. Freed: ${bytes_freed} bytes"
  log_spiral_event "workspace_cleanup" \
    "\"bytes_freed\":${bytes_freed},\"cache_ttl_days\":${SPIRAL_CACHE_TTL:-7}"
}

# ── Helper: compress old iteration artifacts with gzip (US-172) ─────────────
# At the start of iteration N, gzip-compresses per-iteration files from
# iterations N-2 and older to reduce .spiral/ disk usage. Keeps the last
# 2 iterations uncompressed for easy inspection and checkpoint resume.
#
# Compressed files are named <original>.gz; originals are removed.
# Skips: _checkpoint.json, gate-reports/latest-review.html (needed at runtime).
# Skips silently when gzip is unavailable (logs a warning and returns).
compress_old_artifacts() {
  local current_iter="${1:-$SPIRAL_ITER}"
  # Need at least iteration 3 before there is anything to compress (N-2 >= 1)
  [[ "$current_iter" -lt 3 ]] && return 0

  # Skip if gzip is unavailable
  if ! command -v gzip &>/dev/null; then
    echo "  [compress] WARNING: gzip not available — skipping artifact compression"
    return 0
  fi

  local threshold=$((current_iter - 2))
  local compressed=0

  for iter_n in $(seq 1 "$threshold"); do
    # Phase R/T checkpoint and endtime files
    for f in \
      "$SCRATCH_DIR/_phase_R_${iter_n}.ckpt" \
      "$SCRATCH_DIR/_phase_T_${iter_n}.ckpt" \
      "$SCRATCH_DIR/_phase_R_${iter_n}.endtime" \
      "$SCRATCH_DIR/_phase_T_${iter_n}.endtime"; do
      if [[ -f "$f" && ! -f "${f}.gz" ]]; then
        gzip "$f" 2>/dev/null && compressed=$((compressed + 1)) || true
      fi
    done

    # prd-backup JSON for this iteration
    local backup="$SCRATCH_DIR/prd-backups/prd-iter${iter_n}.json"
    if [[ -f "$backup" && ! -f "${backup}.gz" ]]; then
      gzip "$backup" 2>/dev/null && compressed=$((compressed + 1)) || true
    fi
  done

  # Log disk usage when SPIRAL_LOG_LEVEL=DEBUG
  if [[ "${SPIRAL_LOG_LEVEL:-}" == "DEBUG" ]]; then
    local total_kb=0
    if command -v du &>/dev/null; then
      total_kb=$(du -sk "$SCRATCH_DIR" 2>/dev/null | awk '{print $1}' || echo 0)
    fi
    echo "  [compress] Compressed ${compressed} artifact(s) from iters 1-${threshold}; .spiral/ total: ${total_kb}K"
  fi
}

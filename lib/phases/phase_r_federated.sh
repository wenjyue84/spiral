#!/usr/bin/env bash
# lib/phases/phase_r_federated.sh — Phase R Federated: parallel Gemini research per sub-project
#
# Extends Phase R to discover stories independently per sub-project in federated prd.json.
# Spawns parallel Gemini calls (one per sub-project, configurable timeout), then aggregates
# results into _research_output.json with sub_project field on each story.
# Detects duplicate story IDs across sub-projects and emits conflict warnings.
#
# Inputs (globals):
#   $SPIRAL_SUB_PROJECTS   — comma-separated sub-project names (e.g. "api,frontend")
#                            Falls back to extracting from prd.json if not set.
#   $PRD_FILE              — current prd.json
#   $RESEARCH_OUTPUT       — output path for aggregated _research_output.json
#   $SCRATCH_DIR           — runtime scratch directory
#   $SPIRAL_HOME           — SPIRAL installation directory
#   $SPIRAL_PYTHON         — Python interpreter (uv run python)
#   $JQ                    — jq binary path
#   $_phase_r_ckpt         — checkpoint file for Phase R completion
#   $SPIRAL_ITER           — current iteration number
#
# Config vars (spiral.config.sh):
#   SPIRAL_SUB_PROJECTS          — comma-separated sub-project names
#   SPIRAL_FEDERATED_TIMEOUT     — per-sub-project Gemini timeout in seconds (default: 60)
#   SPIRAL_GEMINI_PROMPT         — base Gemini research prompt (scoped per sub-project)
#   SPIRAL_RESEARCH_MODEL        — Claude model for synthesis fallback (default: haiku)
#
# Outputs:
#   $RESEARCH_OUTPUT       — aggregated research JSON with sub_project fields
#   $_phase_r_ckpt         — touched on completion
#   $SCRATCH_DIR/_phase_R_${SPIRAL_ITER}.endtime — epoch timestamp

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_research_federated() {
  local _FED_TIMEOUT="${SPIRAL_FEDERATED_TIMEOUT:-60}"
  local _FED_SCRATCH="${SCRATCH_DIR}/_fed_research"
  mkdir -p "$_FED_SCRATCH"

  # ── Determine sub-projects list ──────────────────────────────────────────
  local _FED_SUB_PROJECTS=""
  if [[ -n "${SPIRAL_SUB_PROJECTS:-}" ]]; then
    _FED_SUB_PROJECTS="$SPIRAL_SUB_PROJECTS"
    echo "  [R-fed] Using SPIRAL_SUB_PROJECTS: $_FED_SUB_PROJECTS"
  else
    # Extract distinct sub_project values from prd.json stories
    _FED_SUB_PROJECTS=$(
      "$JQ" -r '[.userStories[].sub_project // empty] | unique | .[]' \
        "$PRD_FILE" 2>/dev/null | tr '\n' ',' | sed 's/,$//'
    )
    if [[ -n "$_FED_SUB_PROJECTS" ]]; then
      echo "  [R-fed] Discovered sub-projects from prd.json: $_FED_SUB_PROJECTS"
    fi
  fi

  # Fall back to single-project research if no sub-projects configured
  if [[ -z "$_FED_SUB_PROJECTS" ]]; then
    echo "  [R-fed] No sub-projects configured — falling back to standard Phase R"
    run_phase_research
    return
  fi

  # ── Split into array ──────────────────────────────────────────────────────
  IFS=',' read -ra _SUB_PROJ_ARRAY <<< "$_FED_SUB_PROJECTS"

  # ── Spawn parallel Gemini calls per sub-project ───────────────────────────
  declare -A _FED_PIDS
  for _SP in "${_SUB_PROJ_ARRAY[@]}"; do
    _SP="${_SP// /}"  # trim spaces
    [[ -z "$_SP" ]] && continue

    local _SP_OUTPUT="${_FED_SCRATCH}/_research_${_SP}.json"
    local _SP_LOG="${_FED_SCRATCH}/_research_${_SP}.log"

    (
      _BASE_PROMPT="${SPIRAL_GEMINI_PROMPT:-Discover user story candidates for this software project.}"
      _SCOPED_PROMPT="${_BASE_PROMPT}

Sub-project context: Research is scoped to the '${_SP}' sub-project.
Focus on story candidates relevant to the '${_SP}' component and its interfaces.
Each discovered story must include a sub_project field set to '${_SP}'.
Output format: JSON object { \"stories\": [ { \"id\": null, \"title\": \"...\", \"description\": \"...\", \"priority\": \"medium\", \"sub_project\": \"${_SP}\" } ] }"

      echo "  [R-fed:${_SP}] Starting research (timeout: ${_FED_TIMEOUT}s)..."

      _SP_RESEARCH=""
      if command -v gemini &>/dev/null && [[ -n "${SPIRAL_GEMINI_PROMPT:-}" ]]; then
        _GEMINI_ERR=$(mktemp)
        _SP_RESEARCH=$(
          timeout --kill-after=10 "${_FED_TIMEOUT}" \
            gemini -m gemini-2.5-pro -p "$_SCOPED_PROMPT" -y --output-format text \
            2>"$_GEMINI_ERR" || true
        )
        rm -f "$_GEMINI_ERR"
      fi

      if [[ -z "$_SP_RESEARCH" ]]; then
        echo "  [R-fed:${_SP}] Gemini unavailable — writing empty output"
        echo '{"stories":[]}' >"$_SP_OUTPUT"
        exit 0
      fi

      echo "  [R-fed:${_SP}] Gemini research complete ($(echo "$_SP_RESEARCH" | wc -l) lines)"

      # Synthesize Gemini output into story JSON via Claude
      _SYNTH_PROMPT="Convert the following research into a JSON object with format:
{\"stories\": [{\"id\": null, \"title\": \"...\", \"description\": \"...\", \"priority\": \"medium\", \"sub_project\": \"${_SP}\"}]}
Return ONLY valid JSON — no prose or markdown fences.

Research for sub-project '${_SP}':
${_SP_RESEARCH}"

      _OUT_TMP=$(mktemp)
      (
        unset CLAUDECODE
        timeout --kill-after=30 120 \
          claude -p "$_SYNTH_PROMPT" \
          --model "${SPIRAL_RESEARCH_MODEL:-haiku}" \
          --allowedTools "Write" \
          --max-turns 5 \
          --dangerously-skip-permissions \
          </dev/null 2>/dev/null
      ) >"$_OUT_TMP" || true

      # Extract JSON from synthesis output
      if "$SPIRAL_PYTHON" - "$_OUT_TMP" "$_SP_OUTPUT" 2>/dev/null <<'PYEOF'
import json, re, sys
content = open(sys.argv[1], encoding='utf-8').read()
content = re.sub(r'```[a-z]*\n?', '', content).strip()
m = re.search(r'\{[^{}]*"stories"[^{}]*\}|\{.*\}', content, re.DOTALL)
if m:
    try:
        data = json.loads(m.group(0))
        if isinstance(data, dict) and 'stories' in data:
            with open(sys.argv[2], 'w', encoding='utf-8') as f:
                json.dump(data, f)
            sys.exit(0)
    except Exception:
        pass
try:
    arr = json.loads(content)
    if isinstance(arr, list):
        with open(sys.argv[2], 'w', encoding='utf-8') as f:
            json.dump({"stories": arr}, f)
        sys.exit(0)
except Exception:
    pass
sys.exit(1)
PYEOF
      then
        echo "  [R-fed:${_SP}] Synthesis complete"
      else
        echo "  [R-fed:${_SP}] JSON extraction failed — writing empty output"
        echo '{"stories":[]}' >"$_SP_OUTPUT"
      fi
      rm -f "$_OUT_TMP"
    ) >"$_SP_LOG" 2>&1 &
    _FED_PIDS["$_SP"]=$!
  done

  # ── Await all sub-project background jobs ─────────────────────────────────
  for _SP in "${!_FED_PIDS[@]}"; do
    wait "${_FED_PIDS[$_SP]}" || true
    [[ -f "${_FED_SCRATCH}/_research_${_SP}.log" ]] && cat "${_FED_SCRATCH}/_research_${_SP}.log"
  done

  # ── Aggregate per-sub-project outputs ─────────────────────────────────────
  echo "  [R-fed] Aggregating research outputs for: $_FED_SUB_PROJECTS"
  "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/phases/federated_research_aggregator.py" \
    --outputs-dir "$_FED_SCRATCH" \
    --sub-projects "${_SUB_PROJ_ARRAY[@]}" \
    --output "$RESEARCH_OUTPUT" 2>&1 || {
    echo "  [R-fed] Aggregation failed — using empty output"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
  }

  _RESEARCH_COUNT=$("$JQ" '.stories | length' "$RESEARCH_OUTPUT" 2>/dev/null || echo "?")
  echo "  [R-fed] Federated research complete — ${_RESEARCH_COUNT} story candidates across ${#_SUB_PROJ_ARRAY[@]} sub-projects"

  # Mark Phase R complete and record end time
  touch "$_phase_r_ckpt"
  date +%s >"$SCRATCH_DIR/_phase_R_${SPIRAL_ITER}.endtime"
}

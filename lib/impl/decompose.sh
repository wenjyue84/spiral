#!/usr/bin/env bash
# lib/impl/decompose.sh — Phase I sub-stage: STORY DECOMPOSITION
#
# Breaks oversized stories into smaller sub-stories before ralph attempts them.
# Called by phase_i_implement.sh before spawning workers.
#
# When a story fails 2+ times and is flagged as "too large", this module:
#   1. Calls lib/workers/decompose_story.py to split it into sub-stories
#   2. Marks the parent story with _decomposed: true (skipped by ralph)
#   3. Injects sub-stories into prd.json with _decomposedFrom: parent_id
#   4. Sub-stories are picked up automatically in the next worker dispatch
#
# Sub-stories follow the parent's priority and inherit its dependencies.
# Ralph ignores parent stories marked _decomposed: true (see ralph/CLAUDE.md rule 12).
#
# Inputs:
#   $PRD_FILE       — prd.json (read + write)
#   story_id        — ID of story to decompose (passed as argument)
#
# Outputs:
#   $PRD_FILE (patched: parent marked _decomposed, sub-stories added)
#
# Reference: lib/workers/decompose_story.py (existing implementation)

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# check_story_budget <story_id>
# US-530: Check if a story's estimated cost exceeds remaining budget.
# Returns 0 if within budget, 2 if over budget, 1 if check cannot be performed.
#
# Environment:
#   PRD_FILE               — path to prd.json (default: prd.json)
#   SPIRAL_COST_CEILING    — max budget in USD (optional; 0 or unset = skip check)
#   SPIRAL_HOME            — repo root (default: .)
#   SPIRAL_PYTHON          — Python interpreter (default: python3)
#   RESULTS_TSV            — path to results.tsv (default: results.tsv)
check_story_budget() {
  local story_id="$1"
  local prd_file="${PRD_FILE:-prd.json}"
  local spiral_home="${SPIRAL_HOME:-.}"
  local python="${SPIRAL_PYTHON:-python3}"
  local results_tsv="${RESULTS_TSV:-results.tsv}"
  local predict_cost_script="$spiral_home/lib/predict_cost.py"

  # Skip check if ceiling is unset or zero
  if [[ -z "$SPIRAL_COST_CEILING" || "$SPIRAL_COST_CEILING" == "0" ]]; then
    return 0
  fi

  if [[ ! -f "$prd_file" ]]; then
    echo "[Phase I / budget] ERROR: $prd_file not found" >&2
    return 1
  fi

  if [[ ! -f "$predict_cost_script" ]]; then
    echo "[Phase I / budget] ERROR: $predict_cost_script not found" >&2
    return 1
  fi

  # Calculate remaining budget
  local current_spend=0.0
  if [[ -f "$results_tsv" ]]; then
    # Sum cost_usd column from results.tsv (if present) or estimate from duration
    current_spend=$(awk -F'\t' 'NR>1 {if ($6 ~ /^[0-9.]+$/) sum += $6} END {print sum + 0}' "$results_tsv" 2>/dev/null || echo "0")
  fi

  local remaining_budget=$(echo "$SPIRAL_COST_CEILING - $current_spend" | bc 2>/dev/null || echo "$SPIRAL_COST_CEILING")

  # Call predict-cost with budget check
  local predict_output
  predict_output=$("$python" "$predict_cost_script" \
    --story-id "$story_id" \
    --prd "$prd_file" \
    --history "$results_tsv" \
    --budget-remaining "$remaining_budget" 2>&1) || {
    local exit_code=$?
    if [[ $exit_code -eq 2 ]]; then
      # Budget exceeded
      local estimated_cost=$(echo "$predict_output" | "$spiral_home/ralph/jq" -r '.estimated_cost // 0' 2>/dev/null || echo "0")
      echo "[Phase I / budget] BUDGET_EXCEEDED: estimated \$$(printf '%.2f' "$estimated_cost") > remaining \$$(printf '%.2f' "$remaining_budget")" >&2
      return 2
    else
      # Other error
      return 1
    fi
  }

  return 0
}

# decompose_story <story_id> [model]
# Calls lib/workers/decompose_story.py and patches prd.json with sub-stories.
# Returns 0 on success, 1 on failure.
#
# Environment:
#   PRD_FILE       — path to prd.json (default: prd.json)
#   PROGRESS_FILE  — path to progress.txt (default: progress.txt)
#   SPIRAL_HOME    — repo root (default: .)
#   SPIRAL_PYTHON  — Python interpreter (default: python3)
decompose_story() {
  local story_id="$1"
  local model="${2:-sonnet}"
  local prd_file="${PRD_FILE:-prd.json}"
  local progress_file="${PROGRESS_FILE:-progress.txt}"
  local spiral_home="${SPIRAL_HOME:-.}"
  local python="${SPIRAL_PYTHON:-python3}"
  local decompose_script="$spiral_home/lib/workers/decompose_story.py"

  echo "[Phase I / decompose] Decomposing $story_id into sub-stories (model=$model)"

  if [[ ! -f "$prd_file" ]]; then
    echo "[Phase I / decompose] ERROR: $prd_file not found" >&2
    return 1
  fi

  if [[ ! -f "$decompose_script" ]]; then
    echo "[Phase I / decompose] ERROR: $decompose_script not found" >&2
    return 1
  fi

  local learning_path="${spiral_home}/.spiral/learning.md"
  "$python" "$decompose_script" \
    --story-id "$story_id" \
    --prd "$prd_file" \
    --model "$model" \
    --progress "$progress_file" \
    --learning-path "$learning_path"
}

# validate_plan <plan_json> <story_id> [files_to_touch]
# US-1153: Validates a plan block emitted by Ralph before code is written.
# Returns 0 if plan is within scope limits, 1 if oversized and should be decomposed.
# On oversizing, triggers auto-decomposition immediately.
#
# Inputs:
#   plan_json       — JSON string: {files_to_create, files_to_modify, functions_to_add, estimated_loc}
#   story_id        — Story ID for decomposition
#   files_to_touch  — Space-separated list of expected files (optional, for drift detection)
#
# Environment:
#   SPIRAL_PLAN_FILE_LIMIT  — max file count (default 8)
#   Other: PRD_FILE, SPIRAL_HOME, SPIRAL_PYTHON (from parent)
#
# Example:
#   plan='{"files_to_create":["a.py"],"files_to_modify":["b.py"],"functions_to_add":["f"],"estimated_loc":50}'
#   validate_plan "$plan" "US-123" "a.py b.py"
validate_plan() {
  local plan_json="$1"
  local story_id="$2"
  local files_to_touch="${3:-}"

  local plan_limit="${SPIRAL_PLAN_FILE_LIMIT:-8}"
  local spiral_home="${SPIRAL_HOME:-.}"
  local jq="$spiral_home/ralph/jq"

  # Fallback to jq if ralph/jq doesn't exist
  if [[ ! -f "$jq" ]]; then
    jq="jq"
  fi

  # Parse plan
  local files_to_create
  local files_to_modify
  files_to_create=$(echo "$plan_json" | "$jq" -r '.files_to_create | length // 0' 2>/dev/null || echo "0")
  files_to_modify=$(echo "$plan_json" | "$jq" -r '.files_to_modify | length // 0' 2>/dev/null || echo "0")

  if [[ ! "$files_to_create" =~ ^[0-9]+$ ]] || [[ ! "$files_to_modify" =~ ^[0-9]+$ ]]; then
    echo "[Phase I / plan-gate] ERROR: invalid plan JSON" >&2
    return 1
  fi

  local total_files=$((files_to_create + files_to_modify))

  # Check against limit
  if ((total_files > plan_limit)); then
    echo "[Phase I / plan-gate] PLAN_REJECTED: $story_id touches $total_files files (limit: $plan_limit)" >&2
    echo "[Phase I / plan-gate] Triggering auto-decomposition..."
    decompose_story "$story_id" "sonnet"
    return 1
  fi

  # Plan drift detection: check if plan touches files not in filesTouch
  if [[ -n "$files_to_touch" ]]; then
    local plan_files
    plan_files=$(echo "$plan_json" | "$jq" -r '(.files_to_create // []) + (.files_to_modify // []) | .[]' 2>/dev/null)

    while read -r plan_file; do
      [[ -z "$plan_file" ]] && continue

      # Check if this file is in the filesTouch list
      if ! echo "$files_to_touch" | grep -qw "$plan_file"; then
        echo "[Phase I / plan-gate] plan_drift: $plan_file not in filesTouch; proceeding with warning" >&2
      fi
    done <<<"$plan_files"
  fi

  echo "[Phase I / plan-gate] Plan accepted: $total_files files (limit: $plan_limit)"
  return 0
}

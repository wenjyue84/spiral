#!/bin/bash
# SPIRAL — Pre-flight Validation
# Source this file in spiral.sh, then call spiral_preflight_check.
# Validates prd.json schema, checkpoint integrity, and config sanity before main loop.

spiral_preflight_check() {
  local prd_file="${1:-$PRD_FILE}"
  local scratch_dir="${2:-$SCRATCH_DIR}"
  local exit_on_fail=1

  echo "  [preflight] Validating prd.json schema..."
  if ! "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd_schema.py" "$prd_file" --quiet; then
    echo "  [preflight] FATAL: prd.json schema validation failed — aborting"
    exit 1
  fi
  echo "  [preflight] prd.json schema: OK"

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
        R|T|M|G|I|V|C) ;;
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
      auto|haiku|sonnet|opus) ;;
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

  echo "  [preflight] All checks passed"
}

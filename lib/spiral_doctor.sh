#!/bin/bash
# SPIRAL — Doctor utility for dependency verification
# Source this file in spiral.sh, then call spiral_doctor to check all runtime dependencies.
# Validates required tools (claude, jq, python3/uv, node) and configuration files.

spiral_doctor() {
  local error_count=0
  local warn_count=0

  echo ""
  echo "  [doctor] Checking SPIRAL runtime dependencies..."
  echo ""

  # ── Check claude CLI ───────────────────────────────────────────────────────
  if command -v claude >/dev/null 2>&1; then
    echo "  [doctor] [OK] claude CLI found in PATH"
  else
    echo "  [doctor] [ERROR] claude CLI not found in PATH"
    echo "           → Fix: Install Claude CLI (npm install -g @anthropic-ai/claude-cli) or add to PATH"
    error_count=$((error_count + 1))
  fi

  # ── Check jq (minimum 1.6 for --stream support) ────────────────────────────
  if command -v jq >/dev/null 2>&1; then
    local jq_version
    jq_version=$(jq --version 2>/dev/null | sed 's/jq-//')
    local jq_major jq_minor
    jq_major=$(echo "$jq_version" | cut -d. -f1)
    jq_minor=$(echo "$jq_version" | cut -d. -f2 | grep -o '^[0-9]*')
    if [[ "$jq_major" -gt 1 || ( "$jq_major" -eq 1 && "${jq_minor:-0}" -ge 6 ) ]]; then
      echo "  [doctor] [OK] jq found in PATH (version: ${jq_version}, --stream supported)"
    else
      echo "  [doctor] [WARN] jq ${jq_version} found but 1.6+ is required for SPIRAL_PRD_STREAM_THRESHOLD_KB (--stream support)"
      echo "           → Fix: Upgrade jq to 1.6+ (brew upgrade jq, apt-get install jq, or choco upgrade jq)"
    fi
  else
    echo "  [doctor] [ERROR] jq not found in PATH"
    echo "           → Fix: Install jq 1.6+ (brew install jq, apt-get install jq, or choco install jq)"
    error_count=$((error_count + 1))
  fi

  # ── Check python3 or uv ────────────────────────────────────────────────────
  local has_python=0
  local has_uv=0

  if command -v python3 >/dev/null 2>&1; then
    has_python=1
    echo "  [doctor] [OK] python3 found in PATH"
  fi

  if command -v uv >/dev/null 2>&1; then
    has_uv=1
    if [[ "$has_python" -eq 1 ]]; then
      echo "  [doctor] [OK] uv found in PATH"
    else
      echo "  [doctor] [OK] uv found in PATH (python3 not required when uv is present)"
    fi
  fi

  if [[ "$has_python" -eq 0 && "$has_uv" -eq 0 ]]; then
    echo "  [doctor] [ERROR] Neither python3 nor uv found in PATH"
    echo "           → Fix: Install python3 or uv (https://docs.astral.sh/uv/getting-started/)"
    error_count=$((error_count + 1))
  fi

  # ── Check node ─────────────────────────────────────────────────────────────
  if command -v node >/dev/null 2>&1; then
    echo "  [doctor] [OK] node found in PATH"
  else
    echo "  [doctor] [ERROR] node not found in PATH"
    echo "           → Fix: Install Node.js (https://nodejs.org/) or add to PATH"
    error_count=$((error_count + 1))
  fi

  # ── Check prd.json (if it exists) ──────────────────────────────────────────
  if [[ -f "prd.json" ]]; then
    if "$JQ" empty prd.json >/dev/null 2>&1; then
      echo "  [doctor] [OK] prd.json exists and is valid JSON"
    else
      echo "  [doctor] [ERROR] prd.json exists but is not valid JSON"
      echo "           → Fix: Check prd.json syntax or regenerate with 'spiral.sh --init'"
      error_count=$((error_count + 1))
    fi
  else
    echo "  [doctor] [WARN] prd.json not found in current directory"
    echo "           → Info: Run 'spiral.sh --init' to generate prd.json from .md files"
    warn_count=$((warn_count + 1))
  fi

  # ── Check python jsonschema package ─────────────────────────────────────────
  if "$SPIRAL_PYTHON" -c "import jsonschema" >/dev/null 2>&1; then
    echo "  [doctor] [OK] python jsonschema package is importable"
  else
    echo "  [doctor] [WARN] python jsonschema package not installed"
    echo "           → Fix: uv add jsonschema (or pip install jsonschema)"
    echo "           → Info: Formal JSON Schema validation (prd.schema.json) requires this package."
    echo "                   Built-in stdlib validation still works without it."
    warn_count=$((warn_count + 1))
  fi

  # ── Check prd.schema.json ──────────────────────────────────────────────────
  if [[ -f "${SPIRAL_HOME:-$PWD}/prd.schema.json" ]]; then
    echo "  [doctor] [OK] prd.schema.json found"
  else
    echo "  [doctor] [WARN] prd.schema.json not found"
    echo "           → Info: Formal JSON Schema file for prd.json validation"
    warn_count=$((warn_count + 1))
  fi

  # ── Check spiral.config.sh ─────────────────────────────────────────────────
  if [[ -f "spiral.config.sh" ]]; then
    echo "  [doctor] [OK] spiral.config.sh found in current directory"
  else
    echo "  [doctor] [WARN] spiral.config.sh not found in current directory"
    echo "           → Fix: Copy spiral.config.sh from templates/spiral.config.example.sh or run 'spiral.sh --init'"
    warn_count=$((warn_count + 1))
  fi

  # ── Check shellcheck ────────────────────────────────────────────────────────
  if command -v shellcheck >/dev/null 2>&1; then
    local sc_version
    sc_version=$(shellcheck --version | awk '/^version:/{print $2}')
    echo "  [doctor] [OK] shellcheck found in PATH (version: ${sc_version})"
  else
    echo "  [doctor] [WARN] shellcheck not found in PATH"
    echo "           → Fix: Install shellcheck (brew install shellcheck, apt-get install shellcheck, or choco install shellcheck)"
    echo "           → Info: shellcheck is required for static analysis of bash scripts"
    warn_count=$((warn_count + 1))
  fi

  # ── Check shfmt ─────────────────────────────────────────────────────────────
  if command -v shfmt >/dev/null 2>&1; then
    local shfmt_version
    shfmt_version=$(shfmt --version 2>/dev/null || echo "unknown")
    echo "  [doctor] [OK] shfmt found in PATH (version: ${shfmt_version})"
  else
    echo "  [doctor] [WARN] shfmt not found in PATH"
    echo "           → Fix: go install mvdan.cc/sh/v3/cmd/shfmt@latest"
    echo "                  or: brew install shfmt (macOS)"
    echo "                  or: apt-get install shfmt (Ubuntu 20.04+)"
    echo "           → Info: shfmt enforces consistent formatting on all .sh files"
    warn_count=$((warn_count + 1))
  fi

  # ── Check gitleaks ──────────────────────────────────────────────────────────
  if command -v gitleaks >/dev/null 2>&1; then
    local gl_version
    gl_version=$(gitleaks version 2>/dev/null || echo "unknown")
    echo "  [doctor] [OK] gitleaks found in PATH (version: ${gl_version})"
  else
    echo "  [doctor] [WARN] gitleaks not found in PATH"
    echo "           → Fix: Install gitleaks (https://github.com/gitleaks/gitleaks#installing)"
    echo "           → Info: Secret scanning gate in ralph.sh requires gitleaks; set SPIRAL_SKIP_SECRET_SCAN=true to bypass"
    warn_count=$((warn_count + 1))
  fi

  # ── Check Ollama reachability (when SPIRAL_OLLAMA_FALLBACK_MODEL is set) ────
  if [[ -n "${SPIRAL_OLLAMA_FALLBACK_MODEL:-}" ]]; then
    local ollama_base="${SPIRAL_OLLAMA_HOST:-http://localhost:11434/v1}"
    ollama_base="${ollama_base%/v1}"  # strip /v1 suffix to get base URL
    if curl -sf --connect-timeout 3 --max-time 5 "${ollama_base}/api/tags" >/dev/null 2>&1; then
      echo "  [doctor] [OK] Ollama reachable at $ollama_base (model: $SPIRAL_OLLAMA_FALLBACK_MODEL)"
    else
      echo "  [doctor] [WARN] Ollama not reachable at $ollama_base (SPIRAL_OLLAMA_FALLBACK_MODEL=$SPIRAL_OLLAMA_FALLBACK_MODEL)"
      echo "           → Fix: Start Ollama with 'ollama serve' and pull: ollama pull $SPIRAL_OLLAMA_FALLBACK_MODEL"
      warn_count=$((warn_count + 1))
    fi
  fi

  # ── Story count health ───────────────────────────────────────────────────────
  if [[ -f "prd.json" ]]; then
    local story_count total_count passed_count
    total_count=$("$JQ" '.userStories | length' prd.json 2>/dev/null || echo "0")
    passed_count=$("$JQ" '[.userStories[] | select(.passes == true)] | length' prd.json 2>/dev/null || echo "0")
    story_count=$total_count
    local max_stories="${SPIRAL_MAX_STORIES:-100}"
    if [[ "$story_count" -gt "$max_stories" ]]; then
      echo "  [doctor] [WARN] prd.json has $story_count stories ($passed_count passed) — exceeds threshold $max_stories; consider archiving passed stories"
      warn_count=$((warn_count + 1))
    else
      echo "  [doctor] [OK] prd.json story count: $story_count total ($passed_count passed), threshold: $max_stories"
    fi
  fi

  # ── Exit code reference table ────────────────────────────────────────────
  echo ""
  echo "  [doctor] Exit code reference:"
  echo "  ┌─────┬─────────────────────┬──────────────────────────────────────────────┐"
  echo "  │ Code│ Constant            │ Meaning                                      │"
  echo "  ├─────┼─────────────────────┼──────────────────────────────────────────────┤"
  echo "  │   0 │ (success)           │ All stories passed / operation completed OK  │"
  echo "  │   2 │ ERR_BAD_USAGE       │ Wrong CLI arguments or unknown flag          │"
  echo "  │   3 │ ERR_CONFIG          │ Missing or invalid spiral.config.sh value    │"
  echo "  │   4 │ ERR_MISSING_DEP     │ Required tool not found (jq, ralph.sh, …)   │"
  echo "  │   5 │ ERR_PRD_NOT_FOUND   │ prd.json file not found                      │"
  echo "  │   6 │ ERR_PRD_CORRUPT     │ prd.json corrupt and unrecoverable           │"
  echo "  │   7 │ ERR_SCHEMA_VERSION  │ prd.json schemaVersion too new for SPIRAL    │"
  echo "  │   8 │ ERR_COST_CEILING    │ Spend cap (SPIRAL_COST_CEILING) reached      │"
  echo "  │   9 │ ERR_ZERO_PROGRESS   │ Zero-progress stall — all pending blocked    │"
  echo "  │  10 │ ERR_REPLAY_FAILED   │ --replay mode: story implementation failed   │"
  echo "  │  11 │ ERR_STORY_NOT_FOUND │ Story ID passed to --replay not in prd.json  │"
  echo "  │ 130 │ (signal)            │ Interrupted by SIGINT (Ctrl-C) — shell std   │"
  echo "  └─────┴─────────────────────┴──────────────────────────────────────────────┘"

  # ── Summary ────────────────────────────────────────────────────────────────
  echo ""
  if [[ "$error_count" -eq 0 ]]; then
    if [[ "$warn_count" -eq 0 ]]; then
      echo "  [doctor] ✓ All checks passed — SPIRAL is ready to run"
      echo ""
      return 0
    else
      echo "  [doctor] ✓ No errors found, but $warn_count warning(s) above"
      echo ""
      return 0
    fi
  else
    echo "  [doctor] ✗ Found $error_count error(s) — fix above before running SPIRAL"
    echo ""
    return 1
  fi
}

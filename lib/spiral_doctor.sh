#!/bin/bash
# SPIRAL — Doctor utility for dependency verification
# Source this file in spiral.sh, then call spiral_doctor to check all runtime dependencies.
# Validates required tools (claude, jq, python3/uv, node) and configuration files.

# ── check_claude_api — reachability probe (US-179) ──────────────────────────
# Returns 0 (PASS) or 1 (FAIL).  Skipped when SPIRAL_SKIP_API_CHECK=true.
# Does NOT count against SPIRAL_RESEARCH_RETRIES.
check_claude_api() {
  if [[ "${SPIRAL_SKIP_API_CHECK:-}" == "true" ]]; then
    echo "  [doctor] [SKIP] Claude API check skipped (SPIRAL_SKIP_API_CHECK=true)"
    return 0
  fi

  if [[ -z "${ANTHROPIC_API_KEY:-}" ]] && command -v claude &>/dev/null; then
    # Claude Code users: the claude CLI handles auth — no API key needed
    echo "  [doctor] [OK] Claude CLI detected — using Claude Code auth (no API key needed)"
    return 0
  fi

  if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "  [doctor] [ERROR] ANTHROPIC_API_KEY is not set and claude CLI not found"
    echo "           → If using Claude Code: install claude CLI (https://claude.ai/code) and log in"
    echo "           → If using API directly: export ANTHROPIC_API_KEY=<your-key>"
    return 1
  fi

  # Probe the Anthropic API with a 5-second timeout.
  # Any HTTP response (even 401) means the network path is open.
  if curl -sf --connect-timeout 5 --max-time 5 \
      -H "x-api-key: ${ANTHROPIC_API_KEY}" \
      -H "anthropic-version: 2023-06-01" \
      "https://api.anthropic.com/v1/models" >/dev/null 2>&1; then
    echo "  [doctor] [OK] Claude API reachable"
    return 0
  else
    echo "  [doctor] [ERROR] Claude API not reachable (5-second probe failed)"
    echo "           → Fix: Check network connectivity and ANTHROPIC_API_KEY"
    echo "           → Skip: Set SPIRAL_SKIP_API_CHECK=true to bypass this check"
    return 1
  fi
}

# ── check_git_author — git identity validation (US-211) ─────────────────────
# Returns 0 (PASS) or 1 (FAIL).
# When SPIRAL_GIT_AUTHOR="Name <email>" is set, it is used as a fallback.
check_git_author() {
  local git_name git_email

  # If SPIRAL_GIT_AUTHOR is set, parse it and auto-configure git identity.
  if [[ -n "${SPIRAL_GIT_AUTHOR:-}" ]]; then
    git_name="${SPIRAL_GIT_AUTHOR%%<*}"
    git_name="${git_name%% }"   # strip trailing space
    git_email="${SPIRAL_GIT_AUTHOR#*<}"
    git_email="${git_email%>*}"
    if [[ -n "$git_name" && -n "$git_email" ]]; then
      git config user.name "$git_name" 2>/dev/null || true
      git config user.email "$git_email" 2>/dev/null || true
      echo "  [doctor] [OK] git identity set from SPIRAL_GIT_AUTHOR: $git_name <$git_email>"
      return 0
    else
      echo "  [doctor] [WARN] SPIRAL_GIT_AUTHOR='${SPIRAL_GIT_AUTHOR}' could not be parsed — expected format: 'Name <email>'"
    fi
  fi

  # Check git config for user.name and user.email (local or global).
  git_name=$(git config user.name 2>/dev/null || true)
  git_email=$(git config user.email 2>/dev/null || true)

  if [[ -z "$git_name" || -z "$git_email" ]]; then
    local missing=""
    [[ -z "$git_name" ]]  && missing+=" user.name"
    [[ -z "$git_email" ]] && missing+=" user.email"
    echo "  [doctor] [ERROR] git identity not configured (missing:${missing})"
    echo "           → Fix: git config --global user.name  \"Your Name\""
    echo "           → Fix: git config --global user.email \"you@example.com\""
    echo "           → Alt: set SPIRAL_GIT_AUTHOR=\"Your Name <you@example.com>\" to auto-configure"
    return 1
  fi

  echo "  [doctor] [OK] git identity: ${git_name} <${git_email}>"
  return 0
}

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

  # ── Check prd.json file size (US-156) ───────────────────────────────────────
  if [[ -f "${PRD_FILE:-prd.json}" ]]; then
    local _prd_size_bytes
    _prd_size_bytes=$(wc -c < "${PRD_FILE:-prd.json}" 2>/dev/null || echo "0")
    if [[ "$_prd_size_bytes" -gt 1048576 ]]; then
      local _prd_size_kb=$(( _prd_size_bytes / 1024 ))
      echo "  [doctor] [WARN] prd.json is ${_prd_size_kb} KB (>1 MB) — consider running 'spiral compact-prd'"
      echo "           → Info: Transient runtime fields accumulate over many runs and inflate file size."
      warn_count=$((warn_count + 1))
    fi
  fi

  # ── Check prd.json for duplicate story IDs (US-180) ─────────────────────────
  if [[ -f "${PRD_FILE:-prd.json}" ]]; then
    local _prd_for_dup="${PRD_FILE:-prd.json}"
    local _dup_count
    _dup_count=$("$JQ" '[.userStories | group_by(.id)[] | select(length > 1)] | length' "$_prd_for_dup" 2>/dev/null || echo "0")
    if [[ "$_dup_count" -eq 0 ]]; then
      echo "  [doctor] [OK] prd.json: no duplicate story IDs"
    else
      local _dup_list
      _dup_list=$("$JQ" -r '[.userStories | group_by(.id)[] | select(length > 1) | .[0].id] | join(", ")' "$_prd_for_dup" 2>/dev/null || echo "?")
      echo "  [doctor] [ERROR] prd.json has $_dup_count duplicate ID group(s): $_dup_list"
      echo "           → Fix: Run with SPIRAL_DEDUP_IDS=lenient to auto-resolve at startup"
      error_count=$((error_count + 1))
    fi
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

  # ── Git author identity (US-211) ────────────────────────────────────────────
  if check_git_author; then
    : # result already printed inside check_git_author
  else
    error_count=$((error_count + 1))
  fi

  # ── Claude API reachability (US-179) ────────────────────────────────────────
  if check_claude_api; then
    : # result already printed inside check_claude_api
  else
    error_count=$((error_count + 1))
  fi

  # ── Report SPIRAL_GEMINI_FALLBACK_MODEL (US-206) ─────────────────────────────
  local _gemini_fb_model="${SPIRAL_GEMINI_FALLBACK_MODEL:-claude-haiku-4-5-20251001}"
  echo "  [doctor] [OK] SPIRAL_GEMINI_FALLBACK_MODEL=${_gemini_fb_model} (Claude fallback when Gemini returns 503)"

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

  # ── Parallel test execution dependencies (US-148) ────────────────────────────
  local _xdist_ver
  if "$SPIRAL_PYTHON" -c "import xdist; print(xdist.__version__)" >/dev/null 2>&1; then
    _xdist_ver=$("$SPIRAL_PYTHON" -c "import xdist; print(xdist.__version__)" 2>/dev/null || echo "?")
    if [[ "${SPIRAL_PARALLEL_TESTS:-false}" == "true" ]]; then
      echo "  [doctor] [OK] pytest-xdist $_xdist_ver — parallel pytest active (SPIRAL_PARALLEL_TESTS=true)"
    else
      echo "  [doctor] [OK] pytest-xdist $_xdist_ver (inactive — set SPIRAL_PARALLEL_TESTS=true to enable)"
    fi
  else
    if [[ "${SPIRAL_PARALLEL_TESTS:-false}" == "true" ]]; then
      echo "  [doctor] [WARN] SPIRAL_PARALLEL_TESTS=true but pytest-xdist not installed — pytest will run serial"
      echo "           → Fix: uv add pytest-xdist  OR  pip install pytest-xdist"
      warn_count=$((warn_count + 1))
    else
      echo "  [doctor] [INFO] pytest-xdist not installed (optional — set SPIRAL_PARALLEL_TESTS=true to enable)"
    fi
  fi
  if command -v parallel &>/dev/null; then
    local _par_ver
    _par_ver=$(parallel --version 2>/dev/null | head -1 || echo "unknown version")
    if [[ "${SPIRAL_PARALLEL_TESTS:-false}" == "true" ]]; then
      echo "  [doctor] [OK] GNU parallel ($_par_ver) — parallel bats active (SPIRAL_PARALLEL_TESTS=true)"
    else
      echo "  [doctor] [OK] GNU parallel found (inactive — set SPIRAL_PARALLEL_TESTS=true to enable)"
    fi
  else
    if [[ "${SPIRAL_PARALLEL_TESTS:-false}" == "true" ]]; then
      echo "  [doctor] [WARN] SPIRAL_PARALLEL_TESTS=true but GNU parallel not found — bats will run serial"
      echo "           → Fix: choco install parallel  OR  brew install parallel"
      warn_count=$((warn_count + 1))
    else
      echo "  [doctor] [INFO] GNU parallel not found (optional — set SPIRAL_PARALLEL_TESTS=true to enable parallel bats)"
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

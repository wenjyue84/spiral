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

  # ── Check jq ───────────────────────────────────────────────────────────────
  if command -v jq >/dev/null 2>&1; then
    echo "  [doctor] [OK] jq found in PATH"
  else
    echo "  [doctor] [ERROR] jq not found in PATH"
    echo "           → Fix: Install jq (brew install jq, apt-get install jq, or choco install jq)"
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

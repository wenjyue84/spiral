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

  # ── Check spiral.config.sh ─────────────────────────────────────────────────
  if [[ -f "spiral.config.sh" ]]; then
    echo "  [doctor] [OK] spiral.config.sh found in current directory"
  else
    echo "  [doctor] [WARN] spiral.config.sh not found in current directory"
    echo "           → Fix: Copy spiral.config.sh from templates/spiral.config.example.sh or run 'spiral.sh --init'"
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

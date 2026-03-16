#!/bin/bash
# ralph-config.sh — Project-specific quality gates for ralph
#
# Place this file in your project root. ralph.sh sources it automatically if present.
# Uncomment and customize run_project_quality_checks() to add per-project gates.
#
# run_project_quality_checks() is called after implementation, before commit.
# Return 0 to allow the commit, non-zero to reject and trigger a retry.

# run_project_quality_checks() {
#   local pre_error_count="${1:-0}"
#
#   # Run your test suite
#   uv run pytest tests/ -q --tb=short || return 1
#
#   # Optional: TypeScript check
#   # npx tsc --noEmit || return 1
#
#   # Optional: Lint (fail on any warning)
#   # npx eslint src/ --max-warnings 0 || return 1
#
#   # Optional: Rust
#   # cargo clippy -- -D warnings || return 1
#
#   return 0
# }

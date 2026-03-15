#!/usr/bin/env bash
# check_shell_injection.sh — CI check: fail if any Python file uses shell=True
# without a '# spiral-allow-shell' inline comment.
#
# Usage: bash lib/check_shell_injection.sh [search_root]
#
# Exit 0 = clean; Exit 1 = violations found.

set -euo pipefail

SEARCH_ROOT="${1:-.}"

# Find shell=True occurrences, excluding lines with the allow annotation.
# Use grep exit codes: 0=match found, 1=no match, 2=error.
VIOLATIONS=$(
  grep -rn "shell=True" \
    --include="*.py" \
    "$SEARCH_ROOT" \
    | grep -v "# spiral-allow-shell" \
    | grep -v "^Binary" \
    || true
)

if [[ -n "$VIOLATIONS" ]]; then
  echo "ERROR: shell=True without '# spiral-allow-shell' annotation found:"
  echo "$VIOLATIONS"
  echo ""
  echo "Fix: either migrate the call site to exec-form (list args + shell=False),"
  echo "or add '# spiral-allow-shell' inline if shell interpretation is intentional."
  exit 1
fi

echo "OK: No unsafe shell=True usage found in Python files."

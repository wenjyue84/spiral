#!/usr/bin/env bash
# .claude/hooks/protect-spiral-files.sh — PreToolUse hook for US-378
#
# Blocks Edit/Write tool calls targeting protected SPIRAL system files.
# Reads tool input JSON from stdin, extracts file_path, and checks
# against the protected list.
#
# Exit codes:
#   0 — allow (file is not protected)
#   2 — block (file is protected; reason sent to stderr)

set -euo pipefail

# ── Environment variable gate ────────────────────────────────────────────────
# Only enforce protection when running inside a SPIRAL worker (Ralph).
# When the user edits files manually via Claude Code, SPIRAL_WORKER_ACTIVE is
# absent and the hook exits immediately -- no files are blocked.
if [[ "${SPIRAL_WORKER_ACTIVE:-}" != "1" ]]; then
  exit 0
fi

# ── Protected paths ──────────────────────────────────────────────────────────
# Exact file matches and directory prefixes that ralph workers must not modify.
PROTECTED_FILES=(
  "spiral.sh"
  "spiral.config.sh"
  "prd.json"
  "prd.schema.json"
  "ralph/ralph.sh"
  ".pre-commit-config.yaml"
  "constitution.md"
  "pyproject.toml"
)

PROTECTED_PREFIXES=(
  ".spiral/"
  "lib/"
  "ralph/"
  ".claude/hooks/"
  ".github/"
  "tests/core/"
  ".specify/"
)

# ── Read tool input from stdin ───────────────────────────────────────────────
INPUT="$(cat)"

# Extract file_path from the JSON payload
if command -v jq &>/dev/null; then
  FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty')"
else
  # Fallback: lightweight regex extraction (no jq)
  FILE_PATH="$(printf '%s' "$INPUT" | grep -oP '"file_path"\s*:\s*"[^"]*"' | head -1 | sed 's/.*"file_path"\s*:\s*"//;s/"$//')"
fi

# If we couldn't extract a path, allow (don't block unknown formats)
if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# ── Normalize path ───────────────────────────────────────────────────────────
# Strip leading ./ and convert backslashes to forward slashes for Windows compat
FILE_PATH="${FILE_PATH//\\//}"
FILE_PATH="${FILE_PATH#./}"

# ── Check exact matches ─────────────────────────────────────────────────────
for protected in "${PROTECTED_FILES[@]}"; do
  if [[ "$FILE_PATH" == "$protected" ]]; then
    echo "BLOCKED: '$FILE_PATH' is a protected SPIRAL system file. Ralph workers must not modify it." >&2
    exit 2
  fi
done

# ── Check prefix matches ────────────────────────────────────────────────────
for prefix in "${PROTECTED_PREFIXES[@]}"; do
  if [[ "$FILE_PATH" == "$prefix"* ]]; then
    echo "BLOCKED: '$FILE_PATH' is inside protected directory '$prefix'. Ralph workers must not modify files there." >&2
    exit 2
  fi
done

# ── Not protected — allow ────────────────────────────────────────────────────
exit 0

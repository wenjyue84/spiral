#!/usr/bin/env bash
# .claude/hooks/config_audit.sh — ConfigChange hook for SPIRAL settings protection
# Audits every config change to ~/.spiral/config-audit.jsonl and blocks (exit 2)
# modifications to .claude/settings.json and .claude/settings.local.json.
# Not wired into settings.json by default; tests/test_config_audit.bats covers it.

set -euo pipefail

AUDIT_DIR="${HOME}/.spiral"
AUDIT_FILE="${AUDIT_DIR}/config-audit.jsonl"

# Read stdin JSON payload
PAYLOAD="$(cat)"

FILE_PATH="$(echo "$PAYLOAD" | jq -r '.file_path // ""')"
SESSION_ID="$(echo "$PAYLOAD" | jq -r '.session_id // ""')"
SOURCE="$(echo "$PAYLOAD" | jq -r '.source // "unknown"')"
TIMESTAMP="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

mkdir -p "$AUDIT_DIR"

# Append audit entry
printf '%s\n' "$(jq -n \
  --arg ts "$TIMESTAMP" \
  --arg src "$SOURCE" \
  --arg fp "$FILE_PATH" \
  --arg sid "$SESSION_ID" \
  '{timestamp:$ts, source:$src, file_path:$fp, session_id:$sid}')" >>"$AUDIT_FILE"

# Block changes to protected settings files
case "$FILE_PATH" in
  *".claude/settings.json" | *".claude/settings.local.json")
    echo "BLOCKED: modification of $FILE_PATH is not allowed (SPIRAL settings protection)" >&2
    exit 2
    ;;
esac

exit 0

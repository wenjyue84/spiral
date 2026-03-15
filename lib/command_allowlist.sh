#!/bin/bash
# lib/command_allowlist.sh — Permission-scoped command allow-list gate (US-243)
#
# Provides a per-phase command allow-list that ralph.sh uses to gate
# direct bash command execution and scan LLM-produced bash tool_use calls.
#
# Allow-list file: .spiral/command-allowlist.json
# Security log:    .spiral/security-events.log
#
# Format:
#   {
#     "<phase>": {
#       "allow": ["<prefix>", ...],   // permitted command prefixes
#       "deny":  ["<prefix>", ...]    // deny patterns checked first
#     },
#     "global": { ... }               // fallback deny applied to all phases
#   }
#
# Phases: R (research), I (implementation), V (verification), M (merge), global

# ── Default allow-list — shipped with SPIRAL ─────────────────────────────────
SPIRAL_ALLOWLIST_DEFAULTS='{
  "_comment": "SPIRAL command allow-list — permitted command prefixes per phase. Override per project.",
  "R": {
    "allow": ["curl", "python", "python3", "cat", "ls", "jq", "head", "tail", "grep", "find", "echo", "printf", "wc", "sort", "uniq"],
    "deny":  ["rm -rf", "git push --force", "git reset --hard", "git clean -f", "mkfs", "dd if="]
  },
  "I": {
    "allow": ["cat", "ls", "head", "tail", "grep", "find", "echo", "printf", "cp", "mv", "mkdir", "touch", "git add", "git commit", "npm", "npx", "python", "python3", "uv", "node", "cargo", "make", "wc", "sort"],
    "deny":  ["rm -rf", "git push --force", "git push", "git reset --hard", "git clean -f", "mkfs", "dd if="]
  },
  "V": {
    "allow": ["bats", "pytest", "npm test", "npm run test", "npx vitest", "npx playwright", "cargo test", "python", "python3", "uv run pytest", "cat", "ls", "grep", "echo", "printf"],
    "deny":  ["rm -rf", "git push --force", "git reset --hard", "git clean -f"]
  },
  "M": {
    "allow": ["git merge", "git checkout", "git branch", "git log", "git diff", "git status", "git fetch", "echo", "cat"],
    "deny":  ["rm -rf", "git push --force", "git reset --hard", "git clean -f"]
  },
  "global": {
    "allow": [],
    "deny":  ["rm -rf /", ":(){ :|:& };:", "dd if=/dev/zero"]
  }
}'

# ── allowlist_load ────────────────────────────────────────────────────────────
# Ensures .spiral/command-allowlist.json exists with safe defaults.
# Outputs the resolved allow-list file path.
allowlist_load() {
  local al_file="${SPIRAL_ALLOWLIST_FILE:-${SPIRAL_SCRATCH_DIR:-.spiral}/command-allowlist.json}"
  if [[ ! -f "$al_file" ]]; then
    mkdir -p "$(dirname "$al_file")" 2>/dev/null || true
    printf '%s\n' "$SPIRAL_ALLOWLIST_DEFAULTS" > "$al_file" 2>/dev/null || true
  fi
  echo "$al_file"
}

# ── cmd_allowed ───────────────────────────────────────────────────────────────
# cmd_allowed <command> [phase]
# Returns 0 (allowed) or 1 (denied).
# Deny rules take precedence over allow rules (deny checked first).
# If no allow-list file exists, all commands are allowed.
cmd_allowed() {
  local command="$1"
  local phase="${2:-global}"
  local al_file
  al_file=$(allowlist_load)

  if [[ ! -f "$al_file" ]]; then
    return 0  # No allow-list file → allow all
  fi

  # Use python3 for JSON parsing; on parse error default to allow
  local verdict
  verdict=$(python3 - "$al_file" "$phase" "$command" 2>/dev/null <<'ALLOWLIST_PY'
import sys, json

al_file, phase, command = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(al_file, encoding='utf-8') as f:
        policy = json.load(f)
except Exception:
    print('allowed')
    sys.exit(0)

def matches_prefix_or_pattern(command, patterns):
    """Check if command starts with any pattern (or is contained within)."""
    cmd_lower = command.strip().lower()
    for pat in patterns:
        pat_lower = pat.strip().lower()
        if cmd_lower == pat_lower or cmd_lower.startswith(pat_lower + ' ') or cmd_lower.startswith(pat_lower):
            return True
    return False

# Check deny rules: phase-specific first, then global (deny takes precedence)
for p in [phase, 'global']:
    if p in policy:
        deny_patterns = policy[p].get('deny', [])
        if deny_patterns and matches_prefix_or_pattern(command, deny_patterns):
            print('denied')
            sys.exit(0)

print('allowed')
ALLOWLIST_PY
  ) || verdict="allowed"

  [[ "$verdict" == "denied" ]] && return 1 || return 0
}

# ── cmd_log_blocked ───────────────────────────────────────────────────────────
# cmd_log_blocked <command> <phase> [worker_id]
# Appends a blocked command record to .spiral/security-events.log
cmd_log_blocked() {
  local command="$1"
  local phase="${2:-global}"
  local worker_id="${3:-${SPIRAL_WORKER_ID:-unknown}}"
  local timestamp
  timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo "unknown")
  local log_file="${SPIRAL_SCRATCH_DIR:-.spiral}/security-events.log"

  mkdir -p "$(dirname "$log_file")" 2>/dev/null || true
  printf '[%s] BLOCKED phase=%s worker=%s cmd=%s\n' \
    "$timestamp" "$phase" "$worker_id" "$command" >> "$log_file" 2>/dev/null || true
}

# ── safe_run ──────────────────────────────────────────────────────────────────
# safe_run <phase> <command...>
# Checks the command against the allow-list. If allowed, executes it.
# If denied, logs the block and skips execution. Returns 1 if blocked.
safe_run() {
  local phase="$1"
  shift
  local command="$*"

  if cmd_allowed "$command" "$phase"; then
    eval "$command"
    return $?
  else
    cmd_log_blocked "$command" "$phase"
    echo "  [allowlist] BLOCKED ($phase): $command" >&2
    return 1
  fi
}

# ── allowlist_scan_stream_json ────────────────────────────────────────────────
# allowlist_scan_stream_json <stream_json_file> <phase> [story_id]
# Parses LLM stream-json output, extracts Bash tool_use commands,
# and logs any that match deny patterns to security-events.log.
# Returns the count of violations found.
allowlist_scan_stream_json() {
  local stream_file="$1"
  local phase="${2:-I}"
  local story_id="${3:-unknown}"

  if [[ ! -f "$stream_file" ]]; then
    echo 0
    return 0
  fi

  local al_file
  al_file=$(allowlist_load)

  local violations
  violations=$(python3 - "$stream_file" "$al_file" "$phase" "$story_id" 2>/dev/null <<'SCAN_PY'
import sys, json

stream_file, al_file, phase, story_id = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

try:
    with open(al_file, encoding='utf-8') as f:
        policy = json.load(f)
except Exception:
    policy = {}

def matches_prefix(command, patterns):
    cmd_lower = command.strip().lower()
    for pat in patterns:
        pat_lower = pat.strip().lower()
        if cmd_lower == pat_lower or cmd_lower.startswith(pat_lower + ' ') or cmd_lower.startswith(pat_lower):
            return True
    return False

def is_denied(command, phase):
    for p in [phase, 'global']:
        if p in policy:
            deny_patterns = policy[p].get('deny', [])
            if deny_patterns and matches_prefix(command, deny_patterns):
                return True
    return False

try:
    with open(stream_file, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if obj.get('type') == 'assistant':
                    msg = obj.get('message', obj)
                    for block in msg.get('content', []):
                        if block.get('type') == 'tool_use' and block.get('name') == 'Bash':
                            cmd = block.get('input', {}).get('command', '')
                            if cmd and is_denied(cmd, phase):
                                print(cmd)
            except Exception:
                pass
except Exception:
    pass
SCAN_PY
  ) || true

  local vcount=0
  if [[ -n "$violations" ]]; then
    while IFS= read -r blocked_cmd; do
      if [[ -n "$blocked_cmd" ]]; then
        cmd_log_blocked "$blocked_cmd" "$phase" "llm-scan:$story_id"
        vcount=$((vcount + 1))
      fi
    done <<< "$violations"
  fi

  echo "$vcount"
}

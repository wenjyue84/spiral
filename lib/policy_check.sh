#!/bin/bash
# lib/policy_check.sh — Policy adherence gate for SPIRAL (US-242)
#
# Checks ralph.sh operations against .spiral/policy.json before execution.
# Denied operations are skipped and recorded under _policyViolations in prd.json.
#
# Policy file format (JSON):
#   {
#     "<phase>": {
#       "allow": ["<operation>", ...],   // explicit allow patterns (shell glob)
#       "deny":  ["<operation>", ...]    // deny patterns checked first
#     },
#     "global": { ... }                  // fallback applied to all phases
#   }
#
# Operations: git_commit, git_merge, git_push, story_reset, branch_delete
# Phases:     I (implementation), M (merge), R (research), V (verification), global

# ── Default policy — safe defaults shipped with SPIRAL ───────────────────────
# All operations allowed by default; no deny rules.  Override per project via
# .spiral/policy.json to add restrictions (e.g. deny git_push in phase I).
SPIRAL_POLICY_DEFAULTS='{
  "_comment": "SPIRAL policy gate — define per-phase allow/deny rules. Docs: .spiral/policy.json",
  "global": {
    "allow": ["*"],
    "deny": []
  }
}'

# ── policy_load ───────────────────────────────────────────────────────────────
# Ensures .spiral/policy.json exists with safe defaults.
# Outputs the resolved policy file path.
policy_load() {
  local policy_file="${SPIRAL_POLICY_FILE:-${SPIRAL_SCRATCH_DIR:-.spiral}/policy.json}"
  if [[ ! -f "$policy_file" ]]; then
    mkdir -p "$(dirname "$policy_file")" 2>/dev/null || true
    printf '%s\n' "$SPIRAL_POLICY_DEFAULTS" > "$policy_file" 2>/dev/null || true
  fi
  echo "$policy_file"
}

# ── policy_check ─────────────────────────────────────────────────────────────
# policy_check <operation> [phase]
# Returns 0 (allowed) or 1 (denied).
# Deny rules in the phase block take precedence over global allow.
# An empty deny list means no operations are blocked.
policy_check() {
  local operation="$1"
  local phase="${2:-global}"
  local policy_file
  policy_file=$(policy_load)

  if [[ ! -f "$policy_file" ]]; then
    return 0  # No policy file → allow all
  fi

  # Use python3 for JSON parsing; on parse error default to allow
  local verdict
  verdict=$(python3 - "$policy_file" "$phase" "$operation" 2>/dev/null <<'POLICY_PY'
import sys, json, fnmatch

policy_file, phase, operation = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(policy_file, encoding='utf-8') as f:
        policy = json.load(f)
except Exception:
    print('allowed')
    sys.exit(0)

def matches_any(operation, patterns):
    for pat in patterns:
        if fnmatch.fnmatch(operation, pat) or pat == operation:
            return True
    return False

# Check deny rules: phase-specific first, then global (deny takes precedence)
for p in [phase, 'global']:
    if p in policy:
        deny_patterns = policy[p].get('deny', [])
        if deny_patterns and matches_any(operation, deny_patterns):
            print('denied')
            sys.exit(0)

print('allowed')
POLICY_PY
  ) || verdict="allowed"

  [[ "$verdict" == "denied" ]] && return 1 || return 0
}

# ── policy_log_violation ──────────────────────────────────────────────────────
# policy_log_violation <prd_file> <story_id> <operation> <phase> [jq_bin]
# Appends a violation record to ._policyViolations[] in the story entry.
policy_log_violation() {
  local prd_file="$1"
  local story_id="$2"
  local operation="$3"
  local phase="${4:-global}"
  local jq_bin="${5:-${JQ:-jq}}"
  local timestamp
  timestamp=$(date -u '+%Y-%m-%dT%H:%M:%SZ' 2>/dev/null || echo "unknown")

  if [[ -f "$prd_file" ]]; then
    "$jq_bin" \
      --arg op "$operation" \
      --arg ph "$phase" \
      --arg ts "$timestamp" \
      '(.userStories[] | select(.id == "'"$story_id"'") | ._policyViolations) |=
         (. // []) + [{"operation": $op, "phase": $ph, "timestamp": $ts, "blocked": true}]' \
      "$prd_file" >"${prd_file}.tmp" && mv "${prd_file}.tmp" "$prd_file" || true
  fi
}

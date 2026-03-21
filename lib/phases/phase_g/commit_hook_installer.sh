#!/bin/bash
# lib/phases/phase_g/commit_hook_installer.sh
# Installs prepare-commit-msg hook to enforce story ID prefix validation

set -euo pipefail

main() {
  local git_hooks_dir="${1:-.git/hooks}"
  local hook_file="${git_hooks_dir}/prepare-commit-msg"

  # Ensure hooks directory exists
  mkdir -p "$git_hooks_dir"

  # Create or update the prepare-commit-msg hook
  cat >"$hook_file" <<'HOOK_EOF'
#!/bin/bash
# Pre-commit hook: enforce story ID prefix in commit messages
# Validates message matches regex ^(US|UT)-[0-9]+:

set -euo pipefail

# Get the commit message file path (passed by git)
COMMIT_MSG_FILE="${1:-.git/COMMIT_EDITMSG}"

# Read the commit message
COMMIT_MSG=$(cat "$COMMIT_MSG_FILE" 2>/dev/null || echo "")

# Trim leading/trailing whitespace for validation
COMMIT_MSG_TRIMMED=$(echo "$COMMIT_MSG" | sed -e 's/^[[:space:]]*//')

# Check if message matches regex ^(US|UT)-[0-9]+:
if [[ ! "$COMMIT_MSG_TRIMMED" =~ ^(US|UT)-[0-9]+: ]]; then
  echo "Commit message must start with US-NNN: or UT-NNN:" >&2
  exit 1
fi

exit 0
HOOK_EOF

  # Make hook executable
  chmod +x "$hook_file"

  echo "✓ Pre-commit hook installed at $hook_file"
}

main "$@"

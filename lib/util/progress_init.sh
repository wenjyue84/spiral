#!/usr/bin/env bash
# lib/util/progress_init.sh — Auto-generate progress.txt skeleton on first run
#
# Functions: init_progress_file
# Globals used: REPO_ROOT, PRD_FILE, JQ

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# ── Auto-generate progress.txt skeleton on first run ─────────────────────────
# Detects tech stack from manifest files and writes a template progress.txt.
# No-op if progress.txt already exists.
init_progress_file() {
  if [[ ! -f "$REPO_ROOT/progress.txt" ]]; then
    _OVERVIEW=$("$JQ" -r '.overview // "No overview provided"' "$PRD_FILE" 2>/dev/null || echo "No overview provided")
    _STACK=""
    [[ -f "$REPO_ROOT/pyproject.toml" ]] && _STACK="${_STACK}Python "
    [[ -f "$REPO_ROOT/package.json" ]] && _STACK="${_STACK}Node.js "
    [[ -f "$REPO_ROOT/Cargo.toml" ]] && _STACK="${_STACK}Rust "
    [[ -f "$REPO_ROOT/go.mod" ]] && _STACK="${_STACK}Go "
    [[ -f "$REPO_ROOT/Gemfile" ]] && _STACK="${_STACK}Ruby "
    [[ -z "$_STACK" ]] && _STACK="Unknown"
    cat >"$REPO_ROOT/progress.txt" <<PROGRESS_EOF
## Codebase Patterns

Project: $_OVERVIEW

Tech Stack: ${_STACK% }

- (patterns will be added by ralph agents as they discover them)

---

## Gotchas

- (gotchas will be added by ralph agents as they discover them)

---

PROGRESS_EOF
    echo "  [spiral] Generated progress.txt skeleton (tech stack: ${_STACK% })"
  fi
}

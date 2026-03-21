#!/bin/bash
# run_parallel_ralph_federated.sh — Federated mode entry point for parallel Ralph workers
#
# Routes stories from a federated prd.json to dedicated sub-project workers.
# Each sub-project gets isolated git worktrees named worker-{sub_project}-{N}.
# Stories are only processed by workers matching their sub_project field.
#
# Worktree naming: .spiral-workers/worker-{sub_project}-{N}
# Partition files:  {SCRATCH_DIR}/workers/worker-{sub_project}-{N}.json
#
# Usage: Same as run_parallel_ralph.sh — delegates to it after federated validation.
#   bash run_parallel_ralph_federated.sh WORKERS MAX_ITERS REPO_ROOT PRD_FILE SCRATCH_DIR RALPH_SKILL JQ PYTHON MONITOR SPIRAL_HOME [RALPH_MODEL]
#
# Enforces:
#   - PRD has at least one pending story with sub_project field
#   - Worker filenames: worker-{sub_project}-{N}.json
#   - Worktree paths: .spiral-workers/worker-{sub_project}-{N}
#   - No story appears in multiple sub-project worker slices
#   - results.tsv includes sub_project column for all processed stories

set -euo pipefail

RALPH_WORKERS="${1:-1}"
PRD_FILE="${4:-prd.json}"
JQ="${7:-jq}"
SPIRAL_HOME="${10:-$(dirname "$(dirname "$0")")}"

# ── Validate PRD file exists ───────────────────────────────────────────────────
if [[ ! -f "$PRD_FILE" ]]; then
  echo "  [federated] ERROR: PRD file not found: $PRD_FILE" >&2
  exit 1
fi

# ── Extract sub-projects from pending stories ──────────────────────────────────
_SUB_PROJECTS=$("$JQ" -r \
  '.userStories[] | select(.passes != true and .sub_project != null and .sub_project != "") | .sub_project' \
  "$PRD_FILE" 2>/dev/null | sort -u | tr '\n' ' ')

if [[ -z "$_SUB_PROJECTS" ]]; then
  echo "  [federated] ERROR: No pending stories with sub_project field found in $PRD_FILE" >&2
  echo "  [federated] Federated mode requires stories with sub_project field set." >&2
  echo "  [federated] Use run_parallel_ralph.sh for standard (non-federated) mode." >&2
  exit 1
fi

# ── Log federated setup ────────────────────────────────────────────────────────
_TOTAL_PENDING=$("$JQ" '[.userStories[] | select(.passes != true)] | length' "$PRD_FILE" 2>/dev/null || echo "?")
_TOTAL_WORKERS=0

echo "  [federated] ═══════════════════════════════════════════════════"
echo "  [federated]  FEDERATED MODE — Distributing stories by sub-project"
echo "  [federated]  Sub-projects:         $_SUB_PROJECTS"
echo "  [federated]  Workers per project:  $RALPH_WORKERS"
echo "  [federated]  Worktree naming:      worker-{sub_project}-N"
echo "  [federated]  Total pending stories: $_TOTAL_PENDING"
echo "  [federated] ═══════════════════════════════════════════════════"

# Report per-sub-project story counts
for _sp in $_SUB_PROJECTS; do
  _COUNT=$("$JQ" -r --arg sp "$_sp" \
    '[.userStories[] | select(.passes != true and .sub_project == $sp)] | length' \
    "$PRD_FILE" 2>/dev/null || echo "?")
  echo "  [federated]  '$_sp': $_COUNT pending stories → workers: worker-${_sp}-{1..${RALPH_WORKERS}}"
  _TOTAL_WORKERS=$((_TOTAL_WORKERS + RALPH_WORKERS))
done

echo "  [federated]  Total worker worktrees: $_TOTAL_WORKERS"
echo "  [federated] ───────────────────────────────────────────────────"
echo "  [federated]  Delegating to run_parallel_ralph.sh (federated auto-detected)"
echo ""

# ── Delegate to run_parallel_ralph.sh ─────────────────────────────────────────
# Federated mode is auto-detected in run_parallel_ralph.sh when pending stories
# have sub_project fields set. This script provides an explicit federated entry
# point with upfront validation and logging.
exec bash "$SPIRAL_HOME/lib/run_parallel_ralph.sh" "$@"

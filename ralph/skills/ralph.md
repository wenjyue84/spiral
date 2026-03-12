---
name: ralph
description: >
  Run the Ralph autonomous agent loop to implement PRD user stories.
  Use when the user says "run ralph", "start ralph", "ralph fix this",
  "implement prd", or wants to autonomously fix bugs from a prd.json.
---

# Ralph — Autonomous Agent Loop

Implements user stories from `prd.json` one at a time using fresh Claude instances.

## First-Run Detection

**Before running Ralph**, check if `prd.json` exists at the project root (use Glob for `prd.json`).

- If `prd.json` **does NOT exist**: Tell the user this project hasn't been set up for SPIRAL yet, and invoke the `/spiral-init` skill to run the setup wizard. Do NOT proceed with Ralph until the wizard completes.
- If `prd.json` **exists**: Proceed normally with Ralph below.

## Usage

From any project root that has a `prd.json`:

```bash
# If spiral is installed at ~/.ai/Skills/spiral/ (default):
bash ~/.ai/Skills/spiral/ralph/ralph.sh

# With options:
bash ~/.ai/Skills/spiral/ralph/ralph.sh 5          # max 5 iterations
bash ~/.ai/Skills/spiral/ralph/ralph.sh --dry-run   # preview stories only
bash ~/.ai/Skills/spiral/ralph/ralph.sh --prd custom-prd.json
bash ~/.ai/Skills/spiral/ralph/ralph.sh --tool auto  # auto-route: UT-*->Codex, US-*->Qwen, retry->Claude
```

## Project Setup

Each project needs:

1. **`prd.json`** at project root — user stories with `passes: false`
2. **`scripts/ralph/CLAUDE.md`** — project-specific prompt (optional; falls back to global CLAUDE.md)
3. **`ralph-config.sh`** at project root — custom quality gates (optional)

## prd.json Format

```json
{
  "productName": "My Project",
  "branchName": "feature/my-feature",
  "overview": "What we are building",
  "goals": ["Goal 1", "Goal 2"],
  "userStories": [
    {
      "id": "US-001",
      "title": "Short title",
      "priority": 1,
      "description": "What needs to be done and why",
      "acceptanceCriteria": ["Criterion 1", "Criterion 2"],
      "technicalNotes": ["File to edit", "How to fix"],
      "dependencies": [],
      "estimatedComplexity": "small",
      "passes": false
    }
  ]
}
```

## How Ralph Works

1. Reads `prd.json` — finds next story with `passes: false` (sorted by priority)
2. Creates/switches to the feature branch
3. Spawns a fresh Claude instance with the project's `CLAUDE.md` prompt
4. Claude implements the story, runs quality checks, marks `passes: true`
5. Ralph verifies quality gates (TypeScript, lint)
6. On success: commits the change, moves to next story
7. On failure: increments retry count (max 3 retries, then skips)
8. Repeats until all stories complete

## Notes

- `progress.txt` accumulates learnings across iterations — read it first
- `retry-counts.json` tracks retries (auto-deleted when all done)
- Each Ralph iteration is a **fresh Claude instance** — only git history, progress.txt, and prd.json carry state

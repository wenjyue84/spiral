# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is SPIRAL?

**Self-iterating PRD Research & Implementation Autonomous Loop.** An autonomous AI development system that discovers requirements via web research, validates stories against a project constitution, implements them using parallel Claude workers (Ralph), and loops until all stories pass or a time/iteration limit is hit.

## Commands

```bash
# Run SPIRAL (main entry point)
bash spiral.sh 20 --gate proceed                    # 20 iterations, auto-proceed gates
bash spiral.sh 5 --gate proceed --ralph-workers 3   # parallel workers
bash spiral.sh 1 --gate skip --skip-research         # research-only, no implementation
bash spiral.sh 1 --gate proceed --dry-run             # test control flow, no API calls

# Status & estimation
python main.py status       # PRD completion summary
python main.py estimate     # Pre-flight cost projection

# Python tests
uv run pytest tests/ -v --tb=short                    # all tests
uv run pytest tests/test_merge_stories.py -v          # single file
uv run pytest tests/test_merge_stories.py::test_dedup_by_overlap -v  # single test
uv run pytest tests/ --cov=lib --cov-report=html      # with coverage (min 48%)

# Bash tests (bats-core, vendored as submodule)
tests/bats-core/bin/bats tests/*.bats tests/lib/*.bats

# Type checking
uv run mypy lib/ --strict

# Shell linting (CI runs these)
shellcheck --severity=error spiral.sh setup.sh lib/*.sh
shfmt -d -i 2 -ci spiral.sh ralph/ralph.sh lib/*.sh

# PRD validation
uv run python lib/prd_schema.py prd.json
```

## Architecture

### Phase Loop (per iteration)

```
Phase 0: CLARIFY  (startup only, interactive — skipped with --gate proceed/skip)
  └─ Constitution → Focus → Clarify → Stories → Options

Phase R: RESEARCH     → Gemini web search + Claude synthesis → _research_output.json
Phase T: TEST SYNTH   → Scan test failures → _test_stories_output.json
Phase S: STORY VALID  → Constitution/goal/dedup checks → _validated_stories.json
Phase M: MERGE        → Patch prd.json (capped by SPIRAL_MAX_PENDING)
Phase I: IMPLEMENT    → Decompose → Ralph workers → Retry (haiku→sonnet→opus) → Commit/Revert
Phase V: VALIDATE     → Run SPIRAL_VALIDATE_CMD (pytest) + optional screenshots
Phase C: CHECK DONE   → All pass? Exit. Else loop to Phase R.
```

### Key Components

- **`spiral.sh`** — Main orchestrator (monolith; phase modules in `lib/phases/` are stubs pending migration)
- **`ralph/ralph.sh`** — Implementation engine. One Claude CLI invocation per story. Uses `ralph/CLAUDE.md` as agent prompt.
- **`lib/run_parallel_ralph.sh`** — Parallel worker manager using git worktrees (`.spiral-workers/worker-N/`)
- **`lib/phases/*.sh`** — Phase orchestration stubs (logic still in spiral.sh)
- **`lib/impl/`** — Phase I sub-stages: `decompose.sh`, `retry.sh`, `commit_revert.sh`
- **`lib/*.py`** — Python modules for story management (merge, decompose, validate, route, DAG check, cost tracking)
- **`plugins/`** — Hook-based plugin system. Manifest in `plugin.toml`, hooks: `pre-phase`, `post-phase`, `post-story`

### Story Flow

Stories in `prd.json` carry a `_source` field for prioritization:
- **test-fix** (highest) — from Phase T test failures
- **research** — from Phase R web research
- **ai-example** (lowest) — AI-suggested during Phase 0
- **seed** — user-provided, no validation needed

Phase M merge order: test-fix > research > ai-example. Stories are validated against `constitution.md` before merge.

### Parallel Workers

Each worker gets an isolated git worktree, a PRD slice (`lib/slice_prd.py`), and its own branch. Workers use a shared docker lock (`mkdir` mutex). Memory-aware launch: staggered if free RAM is low. Worker timeout and heartbeat monitoring via `lib/worker_heartbeat.sh`.

### Model Routing

`SPIRAL_MODEL_ROUTING=auto` starts with haiku, escalates to sonnet on retry 1, opus on retry 2, skip on retry 3. Optional multi-tool routing (`--tool auto`) tries Qwen/Codex before Claude.

## Configuration

- **`spiral.config.sh`** — All runtime settings. Key vars: `SPIRAL_VALIDATE_CMD`, `SPIRAL_MODEL_ROUTING`, `SPIRAL_MAX_PENDING`, `SPIRAL_STORY_BATCH_SIZE`, `SPIRAL_COST_CEILING`, `SPIRAL_SPECKIT_CONSTITUTION`
- **`prd.json`** — Product backlog. Schema: `prd.schema.json`. Story IDs: `US-NNN` or `UT-NNN`
- **`.spiral/_checkpoint.json`** — Crash recovery state (iteration, phase, timestamps)
- **`results.tsv`** — Telemetry: one row per story attempt (model, tokens, cost, duration, status)
- **`retry-counts.json`** — Per-story retry counters

## Tech Stack

- **Bash 4+** (Git Bash on Windows) — orchestration layer
- **Python 3.13+** (via `uv`) — story management, validation, analysis
- **Node.js 20+** — Claude CLI (`@anthropic-ai/claude-code`), stream formatter
- **jq** — JSON processing (bundled at `ralph/jq.exe` on Windows)
- **Testing**: pytest + hypothesis (Python), bats-core (Bash)
- **CI**: GitHub Actions — shellcheck, shfmt, mypy --strict, pytest with coverage, SARIF (semgrep + shellcheck), pip-audit, bats

## Important Conventions

- Python deps managed via `uv` exclusively (never raw pip)
- Shell scripts: 2-space indent, checked by shfmt and shellcheck
- mypy strict mode with gradual adoption (relaxed modules listed in `pyproject.toml [[tool.mypy.overrides]]`)
- Coverage minimum: 48% (`--cov-fail-under=48`)
- GitHub Actions pinned to full commit SHAs (CI enforces this)
- `.spiral/` is scratch/runtime state (gitignored). `.spiral-workers/` holds git worktrees.
- Ralph's agent prompt lives at `ralph/CLAUDE.md` — edit this to change how the implementation agent behaves
- Templates for new projects: `templates/prd.example.json`, `templates/spiral.config.example.sh`

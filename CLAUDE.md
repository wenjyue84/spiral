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

## Development Setup

### Local Quality Gate Enforcement (Pre-commit)

To catch linting, formatting, and type errors **before** push to CI:

```bash
# One-time setup
uv run pre-commit install

# Hooks run automatically on every commit
# To run manually on all files:
uv run pre-commit run --all-files

# To skip pre-commit (not recommended):
git commit --no-verify
```

Hooks installed:
- **Ruff**: lint (`--fix`) and format
- **MyPy**: static type checking (`--strict`)
- **Shellcheck**: shell script linting (`--severity=error`)
- **Shfmt**: shell script formatting (`-i 2 -ci`)
- **Trailing whitespace** and **EOF fixer**

This mirrors the same checks run in CI (`.github/workflows/`), shifting feedback from CI minutes to sub-second local iteration.

## Architecture

### Phase Loop (per iteration)

```
Phase 0: CLARIFY  (startup only, interactive — skipped with --gate proceed/skip)
  └─ Constitution → Focus → Clarify → Stories → Options

Phase A: AI SUGGEST   → Per-iteration story candidates + test story generation
Phase R: RESEARCH     → Gemini web search + Claude synthesis (parallel with T)
Phase T: TEST SYNTH   → Scan test failures (parallel with R)
Phase S: STORY VALID  → Constitution/goal/dedup checks → _validated_stories.json
Phase E: ENRICHMENT   → Populate hints & context on validated stories
Phase M: MERGE        → Patch prd.json (capped by SPIRAL_MAX_PENDING)
Phase X: CONTEXT BUILD→ Dependency inference
Phase G: GATE         → Human checkpoint (skipped with --gate proceed)
Phase I: IMPLEMENT    → Decompose → Ralph workers → Retry (haiku→sonnet→opus) → Commit/Revert
Phase V: VALIDATE     → Run SPIRAL_VALIDATE_CMD (pytest) + optional screenshots
Phase C: CHECK DONE   → All pass? Exit. Else continue.
Phase L: LEARNING     → Episodic memory extraction (optional, SPIRAL_EPISODIC_MEMORY)
→ Loop back to Phase A
```

> **CRITICAL**: The phase order above is the source of truth. If you change it,
> update ALL copies listed in the comment block at spiral.sh line ~1390.

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

## CPU Profiling (py-spy)

To profile a slow SPIRAL Python phase without modifying source code:

1. Start a SPIRAL run in one terminal.
2. Find the Python PID:
   ```bash
   ps aux | grep spiral   # Linux/macOS
   Get-Process python     # Windows PowerShell
   ```
3. In a second terminal, capture a 30-second flamegraph:
   ```bash
   task profile PID=<pid>
   # or directly:
   py-spy record --pid <pid> --duration 30 --output flamegraph.svg --format speedscope
   ```
4. Open `flamegraph.svg` via [speedscope.app](https://www.speedscope.app/) (drag-and-drop) to explore call stacks interactively.

> `flamegraph.svg` is gitignored. py-spy attaches non-invasively with no application restart required.

## Important Conventions

- Python deps managed via `uv` exclusively (never raw pip)
- Shell scripts: 2-space indent, checked by shfmt and shellcheck
- mypy strict mode with gradual adoption (relaxed modules listed in `pyproject.toml [[tool.mypy.overrides]]`)
- Coverage minimum: 48% (`--cov-fail-under=48`)
- GitHub Actions pinned to full commit SHAs (CI enforces this)
- `.spiral/` is scratch/runtime state (gitignored). `.spiral-workers/` holds git worktrees.
- Ralph's agent prompt lives at `ralph/CLAUDE.md` — edit this to change how the implementation agent behaves
- Templates for new projects: `templates/prd.example.json`, `templates/spiral.config.example.sh`

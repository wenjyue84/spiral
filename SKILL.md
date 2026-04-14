---
name: spiral
version: 4.3.385
description: >
  Run the SPIRAL autonomous development loop on any project. Handles setup,
  generates prd.json and spiral.config.sh if missing, then launches the
  self-iterating research + implementation loop autonomously.
  Use when user says "run spiral", "start spiral", "use spiral to build this",
  "implement my PRD with spiral", "spiral loop", or "spiral this".
---

# Spiral — Autonomous Development Loop

SPIRAL is a self-iterating development loop: AI Suggestions → Research → Implement → Validate → repeat.
Each iteration generates AI story suggestions, researches web context, validates and enriches new stories,
implements pending user stories with ralph workers, runs tests, and generates a metrics dashboard.

## Resolve SPIRAL_HOME

Before running any SPIRAL commands, resolve where Spiral is installed:

```bash
# Find SPIRAL_HOME — check standard install locations
for _candidate in "$HOME/.ai/Skills/spiral" "$HOME/.spiral" "$HOME/.local/share/spiral"; do
  if [ -f "$_candidate/spiral.sh" ]; then
    SPIRAL_HOME="$_candidate"
    break
  fi
done
if [ -z "${SPIRAL_HOME:-}" ]; then
  echo "SPIRAL not found. Install: git clone https://github.com/wenjyue84/spiral.git ~/.ai/Skills/spiral && bash ~/.ai/Skills/spiral/setup.sh"
  exit 1
fi
```

Use `$SPIRAL_HOME` for ALL paths to Spiral scripts and tools throughout this skill.

## Directory Layout

```
$SPIRAL_HOME/
├── spiral.sh              # Main orchestrator (bash — CLI parsing, phase loop, all orchestration)
├── main.py                # Python CLI entrypoint for subcommands (status, estimate, monitor, etc.)
├── lib/
│   ├── cli/              # Python CLI argument parsers (parsers.py)
│   ├── commands/          # Python subcommand implementations (dlq, status, worktree, etc.)
│   ├── phases/*.sh        # Phase orchestration bash stubs
│   │   ├── phase_x_contextbuild.sh  # Phase X: AST-based symbol map generation
│   │   └── phase_g_version_bump.py  # Phase G: semantic version bump from CHANGELOG.md
│   ├── modes/*.sh         # Mode handlers (replay, oneshot, ops)
│   ├── impl/              # Phase I sub-stages: decompose.sh, retry.sh, commit_revert.sh
│   ├── context/           # Phase X symbol map generation
│   │   └── repo_map.py    # Per-story export/import/caller/boundary maps
│   ├── spiral/            # Python: evals, results TSV validation
│   ├── {prd,core,routing,security,research,observability,quality,resilience,workers,tools,importers,ui}/
│   │                      # Domain modules — each has its own CLAUDE.md
│   ├── gen_changelog.py   # Custom changelog generation (Phase G)
│   ├── run_parallel_ralph.sh  # Parallel worker manager (git worktrees)
│   ├── spiral_helpers.sh  # Shared bash utilities
│   ├── spiral_startup.sh  # Startup checks and initialization
│   ├── monitor.py         # Unified monitoring snapshot for progress checks
│   └── (150+ Python/bash helpers for story mgmt, validation, cost tracking, etc.)
├── ralph/                 # Bundled ralph implementation agent
│   ├── ralph.sh           # Implementation engine (one Claude CLI invocation per story)
│   └── CLAUDE.md          # Ralph agent prompt
└── templates/
    ├── prd.example.json           # prd.json schema reference
    └── spiral.config.example.sh   # Config template with all options
```

## How to Run This Skill

When invoked, follow these three phases exactly.

---

## Phase 1 — Detect Project State

Check which setup files exist in the current working directory:

```bash
ls prd.json spiral.config.sh 2>/dev/null
```

Determine state:
- **State A**: Neither file exists → full onboarding needed
- **State B**: `prd.json` exists, no `spiral.config.sh` → config-only setup
- **State C**: Both exist → minimal setup (just run parameters)

---

## Phase 2 — Dual Setup (GUI + CLI simultaneously)

For states that need setup (A or B): launch the GUI **and** ask CLI questions at the same time. The user picks whichever they prefer — both paths produce `spiral.config.sh`.

---

### Step 1 — Launch GUI in background (always, for State A and B)

Before asking any questions, start the SPIRAL UI server with `SPIRAL_PROJECT_ROOT` set to the project root:

```bash
SPIRAL_PROJECT_ROOT="<REPO_ROOT>" npm --prefix "$SPIRAL_HOME/spiral-ui" run dev -- --port 5299
```

Replace `<REPO_ROOT>` with the absolute path of the project. If port 5299 is in use, Vite will auto-try 5300, 5301, etc. — note the actual URL from output.

---

### Step 2 — Announce both paths, then ask CLI questions immediately

Tell the user:

> "✅ SPIRAL config UI is running at **http://localhost:5299**
>
> **GUI path:** Open the link → Settings tab → configure → Config Output tab → 💾 Save to Project → tell me **'ready'**
> **CLI path:** Just answer my questions below — I'll generate the config for you
>
> Use whichever you prefer!"

Then **immediately** ask the CLI questions below — do not wait for the user to choose first.

---

### CLI Questions by State

#### State A — No prd.json, no config

Ask in sequence:
1. **What to build**: "Describe what you want Spiral to build. Be specific about features, tech stack, and constraints."
2. **Test command**: "What command runs your tests? (e.g., `npm test`, `pytest`, `uv run pytest`) [skip if unsure]"
3. **Story prefix**: "Story ID prefix? Options: US (User Story), FE (Frontend), BE (Backend), UT (Unit Test) [US]"
4. **Reports directory**: "Where should test reports be written? (relative to project root) [test-reports]"
5. **Deploy command**: "Run a deploy command after each parallel-worker wave? e.g., `docker cp ./app/. container:/app/ && docker exec c clear-cache` [none — skip]"
6. **Patch directories**: "In parallel mode, limit git patches to specific directories? e.g., `src/ tests/` Helps reduce merge conflicts. [all files — skip]"
7. **GitNexus repo**: "GitNexus repo name for smarter file-to-story mapping? Requires `gitnexus` CLI and prior `gitnexus analyze`. [none — skip]"

#### State B — Has prd.json, no config

Ask only:
1. **Test command**: "What command runs your tests?"
2. **Reports directory**: "Where should test reports be written? [test-reports]"
3. **Deploy command**: "Run a deploy command after parallel workers? [none — skip]"

#### State C — Both files exist

Skip Phase 2 entirely — go straight to Phase 3.

---

### Step 3 — Accept either response

**CLI path** — user answers the questions above:
Use their answers to generate `prd.json` (State A) and `spiral.config.sh`, then continue to Phase 3.

**GUI path** — user says "ready", "done", "launch", "go", or similar at any point:
Stop asking remaining CLI questions. Verify `spiral.config.sh` exists in the project root:
```bash
ls -la "$REPO_ROOT/spiral.config.sh"
```

If it doesn't exist (user didn't click Save), fall back to creating a minimal one:
```bash
cat > "$REPO_ROOT/spiral.config.sh" << 'EOF'
#!/usr/bin/env bash
# spiral.config.sh — minimal defaults
EOF
```

---

## Phase 3 — Launch

### 3-pre — Start spiral-ui (ALWAYS, before anything else)

Before launching spiral.sh, **always** ensure spiral-ui is running. Check port 5299 first — if it's not responding, start it:

```bash
# Check if already running
curl -s -o /dev/null -w "%{http_code}" http://localhost:5299/ 2>/dev/null
```

If not 200, start it in the background:

```bash
cd "$SPIRAL_HOME/spiral-ui" && npm run dev -- --port 5299 &
```

Wait for it to respond (up to 10s), then continue. This applies to ALL states (A, B, C) — spiral-ui must always be running when spiral.sh launches.

---

The GUI has already written `spiral.config.sh` to the project root with all settings.
Read the key CLI parameters from the saved config, then build and run the launch command.

### 3a — Read CLI parameters from spiral.config.sh

Source the config to get these values (they become CLI flags, not env vars for spiral.sh):

```bash
source "$REPO_ROOT/spiral.config.sh" 2>/dev/null || true
MAX_ITERS="${MAX_SPIRAL_ITERS:-20}"
TIME_LIMIT="${TIME_LIMIT_MINS:-720}"           # default 12 hours
RALPH_ITERS="${SPIRAL_RALPH_ITERS:-120}"
GATE_MODE="${SPIRAL_GATE_MODE:-interactive}"   # interactive | proceed | skip
WORKERS=1  # ALWAYS default to 1 — never auto-read multi-worker from config
MODEL="${SPIRAL_MODEL_ROUTING:-auto}"
CAPACITY="${SPIRAL_CAPACITY_LIMIT:-50}"
```

### 3b — Build and show launch command

Build flags:
- `--gate proceed` if `GATE_MODE=proceed`; `--gate skip` if `skip`; omit if `interactive`
- `--ralph-iters N` only if N ≠ 120
- `--ralph-workers N` — **NEVER include unless the user explicitly requested multiple workers AND you have confirmed with them** (see Worker Safety Rule below)
- `--model M` only if M ≠ auto
- `--capacity-limit N` only if N ≠ 50

**Worker Safety Rule:** Always launch with `--ralph-workers 1` (the default — omit the flag entirely). If the user requests more than 1 worker, you MUST:
1. Warn them: *"Multiple workers use significantly more RAM and can cause OOM/fork exhaustion on Windows. Are you sure you want N workers?"*
2. Wait for explicit confirmation before adding `--ralph-workers N` to the command.
3. Never exceed 3 workers regardless of user request (hard cap per system constraints).

**Note:** `--time-limit` is NOT a supported flag in spiral.sh — omit it. Control runtime via max_iters only.

Show user the exact command before running. Example:
```bash
bash "$SPIRAL_HOME/spiral.sh" 20 --gate proceed
```

### 3c — Run spiral.sh

Use the MSYS path format (`/c/Users/...`) — NOT `C:/Users/...` — or the script won't be found:

```bash
bash "$SPIRAL_HOME/spiral.sh" $MAX_ITERS   [--gate proceed|skip]   [--ralph-iters $RALPH_ITERS]   [--ralph-workers $WORKERS]   [--model $MODEL]   [--capacity-limit $CAPACITY]
```

**Important:** Spiral runs in the terminal and blocks until done or Ctrl+C. It can run for hours — this is expected.

### 3c-register — Register project with UI (ALWAYS do after launching)

After running spiral.sh, register the project with the UI so the dashboard works. Get the `productName` from `prd.json`:

```bash
PROJECT_NAME=$(jq -r '.productName' "$REPO_ROOT/prd.json")
curl -s -X POST http://localhost:5299/api/register-project \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"$PROJECT_NAME\",\"root\":\"$REPO_ROOT\"}"
```

This persists in `~/.spiral/ui-projects.json` — only needs to be done once per project.

### 3c-browser — Open spiral-ui in browser (ALWAYS do after registering)

Open the project dashboard in the user's default browser so they can follow along:

```bash
powershell -Command "Start-Process 'http://localhost:5299/<PROJECT_NAME>'"
```

This opens the live dashboard immediately — the user doesn't have to manually navigate to it.

### 3d — Screenshot project dashboard (ALWAYS do this right after opening browser)

After opening the browser, take a screenshot of the dashboard and show it to the user. Use the dev-browser skill server (start if not running) and run:

```bash
cd "/c/Users/Jyue/.claude/skills/dev-browser" && npx tsx <<'EOF'
import { connect, waitForPageLoad } from "@/client.js";
const client = await connect();
const page = await client.page("spiral-dashboard", { viewport: { width: 1440, height: 900 } });
await page.goto("http://localhost:5299/<PROJECT_NAME>");
await waitForPageLoad(page);
await page.waitForTimeout(3000);
await page.screenshot({ path: "tmp/spiral-dashboard.png", fullPage: true });
console.log("Screenshot saved");
await client.disconnect();
EOF
```

Then read and display `tmp/spiral-dashboard.png` to the user with the Read tool.

Tell the user:
> "Your live project dashboard is at **http://localhost:5299/<project-name>** — it refreshes every 30s."

The dashboard shows:
- **Progress** tab — story completion %, pending/done list with completion timestamps, progress history (last 5 rows, expand for more)
- **Phase Trace** tab — per-phase timing breakdown with SLA breach detection
- **Workers** tab — live per-worker console streams
- **Tokens** tab — token burn by model, phase, story, cumulative spend chart, cost tips
- **Graph** tab — story dependency DAG with interactive node inspection
- **Tests** tab — list all pytest tests grouped by file; run individual tests or all; live console output
- **Settings** tab — active config vars from `spiral.config.sh`
- **Constitution** tab — the project constitution/rules
- **Skills** tab — integrated skill/tool discovery and documentation
- **Activity Log** tab — live log tail with story filtering
- **Analytics** tab — agent telemetry, phase timing bars, failure/retry patterns, error breakdown charts, worker timeline

---

### 3e — Auto Progress Loop with Auto-Fix (ALWAYS set up after launch)

**This is mandatory — do it every time Spiral is launched, no exceptions.**

Immediately after launching, schedule a recurring progress check using `CronCreate` with:
- `cron`: pick interval based on run speed (see Adaptive Interval below)
- `recurring`: `true`

**Adaptive Interval:** Match the check frequency to the run speed:
| Story pace | Interval | Cron |
|------------|----------|------|
| < 5 min/story (fast, parallel workers) | 10 min | `*/10 * * * *` |
| 5–15 min/story (typical) | 15 min | `*/15 * * * *` |
| > 15 min/story (complex, opus-heavy) | 30 min | `*/30 * * * *` |

If unsure, default to 15 min. You can adjust later once you see the pace.

---

**Template for the CronCreate prompt** (substitute `PROJECT_ROOT`):

```
Check SPIRAL progress and auto-fix if stalled.

## Step 1 — Gather Data

Run in PROJECT_ROOT:
  uv run python main.py monitor --port 5299

Read the memory file `project_spiral_passes.md` for last known passes count.

## Step 2 — Report (plain English, no jargon)

Report format:
- "X new stories passed" (not "delta")
- Omit DLQ/skipped if zero
- Always compare passes count vs previous check

**Scoreboard:**
- Done: [passed] / [total] ([pass_pct]%)
- New since last check: +[new_passed] stories
- Pending: [pending] remaining

## Step 2.5 — Milestone Digest (every 10 stories)

After reporting, check if a new multiple-of-10 milestone was crossed since the last check:

- Read `prev_passes` from `project_spiral_passes.md`
- `milestone = (curr_passes // 10) * 10`
- Trigger only if `milestone > (prev_passes // 10) * 10` AND `milestone > 0`

If triggered:

1. **Extract the 10 most-recently-passed stories** from `prd.json` — all entries where `passes: true`, sorted by `_passedCommit` descending, take up to 10.
2. **Generate a Chinese digest** for each story — 2–3 plain sentences explaining *what it does* and *why it matters*, written for a non-technical reader (no code, no jargon).
3. **Write a closing summary** (`**本轮总结：**`) grouping the 10 improvements into 2–3 themes.
4. **Append to `10us.md`** in the project root (create if absent). Use this format exactly:

```
# SPIRAL 最近10个改进 — YYYY-MM-DD (第[milestone]个故事里程碑)

> 自动生成：SPIRAL 每完成10个故事后更新此文件。

---

**1. US-XXXX — [故事标题]**
[2–3句中文，说明功能作用和用户价值]

**2. US-XXXX — [故事标题]**
[...]

...（共10条）

---

**本轮总结：** [2–3句归纳主题]

**累计进度：** [passed]/[total] ([pass_pct]%) — 本次运行已完成 [new_passed] 个故事

---
```

After writing, tell the user: `📋 已生成第[milestone]个故事里程碑摘要，追加至 10us.md。`

## Step 3 — Investigate if Stalled (passes NOT increased)

If new_passed == 0 (no new stories since last check), investigate in this order:

### 3a. Is SPIRAL still running?
- Check `.spiral/_last_run.log` — if mtime > 300s old, SPIRAL likely stopped
- Check for active node/python processes: `powershell -Command "Get-Process node,python -ErrorAction SilentlyContinue | Select Name,Id,StartTime"`

### 3b. Check worker state
- Read `.spiral/workers/worker_*.log` tails for errors
- Read `.spiral/workers/worker_*.json` for queue state
- Check heartbeat files for staleness

### 3c. Check pending stories
- Read `prd.json` — identify which stories are pending and why
- Check `retry-counts.json` — stories hitting retry limits (>= 3 retries)
- Check `results.tsv` tail — recent failure patterns and error messages

### 3d. Check infrastructure
- Stale lock files: `prd.json.lock`, `.git/index.lock`
- Locked/orphaned worktrees: `git worktree list`
- Corrupt story titles (title == id)
- Uncommitted `spiral.config.sh` changes (auto-stash will revert them)
- Memory pressure: check free RAM vs worker budget

## Step 4 — Auto-Fix (safe fixes applied automatically)

Apply these fixes WITHOUT asking — they are always safe:

| Problem | Auto-Fix |
|---------|----------|
| **SPIRAL process died** | Restart: `bash spiral.sh 5 --gate proceed` (single worker default — never auto-add `--ralph-workers` without user confirmation) |
| **spiral-ui down** | Restart: `cd spiral-ui && npm run dev -- --port 5299` in background |
| **Stale lock files** (dead PID) | Delete: `rm prd.json.lock` or `rm .git/index.lock` |
| **Orphaned worktrees** | Unlock + remove: `git worktree unlock <path> && git worktree remove <path> --force` |
| **Orphaned worker branches** | Delete: `git branch -D spiral-worker-*` (only if no active worktrees reference them) |
| **Corrupt story titles** (title == id) | Fix in prd.json: set title to description first sentence, or a sensible summary |
| **Uncommitted config** | Commit: `git add spiral.config.sh && git commit -m "chore: commit spiral config"` |

## Step 5 — Escalate (ask before these)

These fixes need user confirmation:

| Problem | Ask Before |
|---------|------------|
| **Story failing 3+ times** | Suggest decomposition into 4 sub-stories (per feedback_story_too_large.md) |
| **Memory pressure blocking workers** | List top processes by RAM, suggest which to close, estimate extra workers gained |
| **Cost ceiling approaching** | Suggest raising SPIRAL_COST_CEILING or switching to haiku model |
| **All pending stories stuck** | Suggest focus change, skip-research mode, or manual story triage |

## Step 6 — Update Baseline

Update `project_spiral_passes.md` with new passes count.

## Rules
- Default 1 worker — NEVER add `--ralph-workers` > 1 without explicit user request + confirmation
- Report every check even if nothing changed (say "holding steady at X/Y")
- If status.pending == 0 and run_health.running is true: say SPIRAL is discovering new stories (normal), NOT stopped
- After auto-fix, wait one cycle before checking if fix worked — do NOT retry immediately
```

Tell the user: "Progress monitor with auto-fix scheduled (Job ID: `<job_id>`). Checks every [interval] — reports progress, investigates stalls, and auto-fixes safe issues. Cancel anytime with `CronDelete <job_id>`."

---

## Spiral Loop Phases (for reference)

The main loop is: `while SPIRAL_ITER < MAX_SPIRAL_ITERS` — it runs until your configured iteration count **or** `--time-limit`/`--until` wall-clock deadline is hit, whichever comes first. Phase C may trigger an **early exit** if everything is done ahead of schedule, but SPIRAL keeps going and discovering new stories via Phase R on every iteration until the time/iteration limit is reached.

**Startup (one-time before the loop):** Phase 0 (Clarify) runs once at launch — sets the focus area, time limit, and seeds the backlog from user input.

**Per-iteration order:** A → [R+T parallel] → S → E → M → X → I → V → C → loop back to A.

**Story preparation (A → R+T → S → E → M → X):** AI suggestions first, then research and test scanning in parallel; Phase S filters, Phase E enriches (optional), Phase M merges to prd.json, Phase X builds symbol maps for Ralph.

**Implementation loop (I → V → C):** Implements stories, validates, then checks if done.

### Phase 0 — Clarify (startup only)
One-time interactive phase before the main loop. Asks clarifying questions about the focus area and time limit, collects the user's initial story seeds, and performs a constitution check on those seeds. Skipped in `--gate proceed` or `--gate skip` (non-interactive) mode.

### Phase A — AI Suggestions (every iteration)
Runs at the start of each iteration before Phase R. Two sub-tasks run unconditionally:

1. **Gap analysis** (when `SPIRAL_SPECKIT_CONSTITUTION` is set): Calls Claude (`SPIRAL_AI_SUGGEST_MODEL`, default `haiku`) with the project constitution and current PRD state to generate up to `SPIRAL_MAX_AI_SUGGEST` (default 5) new story candidates that fill real gaps and comply with the constitution. Output: `_ai_suggest_output.json`.
2. **Test story candidates**: Calls `lib/research/generate_test_stories.py` to analyze passed stories and propose paired test stories. Output: `_test_story_candidates.json`.

These candidates flow into Phase M for deduplication and merge. Skipped if `SPIRAL_MAX_AI_SUGGEST=0`.

### Phase R — Research
Claude browses the web and reads documentation to discover new user stories. Injects the project's `goals[]` and `overview` from `prd.json` as context. If `SPIRAL_FOCUS` is set, Claude is instructed: *"You MUST only discover stories directly related to this theme."* Optional Gemini 2.5 Pro pre-fetch runs first to gather web context cheaply before Claude starts. Output: `_research_output.json`. Skipped if `--skip-research` or pending stories > `--capacity-limit`.

### Phase T — Test Synthesis
Scans `test-reports/*/report.json` for FAIL/ERROR test results and converts each one into a new user story to fix it. This is how Spiral heals itself — broken tests become actionable tasks automatically. Timeout: `SPIRAL_TEST_SYNTH_TIMEOUT` (default 60s). Skipped if `SPIRAL_SKIP_TEST_SYNTHESIS=1`.

### Phase S — Story Validate (between T and M)
Automated gate that reviews all story candidates from Phase R and Phase T before they are committed to `prd.json`. Runs `lib/validate_stories.py` which applies three checks:
1. **Constitution check** — rejects stories that violate `SPIRAL_SPECKIT_CONSTITUTION`
2. **Goal alignment check** — rejects stories with no clear keyword overlap with `prd.json goals[]` (threshold: `SPIRAL_STORY_VALIDATE_MIN_OVERLAP`, default 1)
3. **Quality check** — rejects vague or untestable stories

Accepted stories → `_validated_stories.json` (passed to Phase M). Rejected stories → `_story_rejected.json` (log only). If the validator script fails entirely, all stories pass through as a safe fallback.

### Phase E — Story Enrichment (optional)
Runs between Phase S and Phase M when `SPIRAL_STORY_ENRICHMENT=true` (default: disabled). Calls `lib/research/enrich_stories.py` using Claude (`SPIRAL_STORY_ENRICHMENT_MODEL`, default `sonnet`) to:
- Rewrite vague acceptance criteria into concrete, testable criteria
- Add exact file paths and test commands to sparse stories
- Split stories that touch 3+ files into smaller atomic sub-stories

On success, updates the validated stories file so Phase M picks up the richer stories. On failure, leaves the file unchanged and prints a warning — Phase M still runs.

### Phase M — Merge
Deduplicates stories from Phase S output (validated candidates) against existing `prd.json` (60% title similarity = skip), assigns sequential IDs, infers dependencies from `filesTouch` overlap (optional), and atomically patches `prd.json`. Backs up `prd.json` before each merge (keeps last 10 in `.spiral/prd-backups/`). Validates the dependency graph is acyclic after merging.

### Phase X — Context Build (between M and I)
Runs when `SPIRAL_REPO_MAP=true`. Parses `filesTouch` entries from pending stories and generates per-story symbol maps (exports, imports, test neighbors, callers, dependency boundaries) using Python AST — zero LLM cost. Results are written as markdown files in `$SCRATCH_DIR/_repo_map_<story_id>.md` and injected into Ralph's user prompt. Config: `SPIRAL_REPO_MAP`, `SPIRAL_REPO_MAP_MAX_LINES` (default 150).

### Phase G — Version Bump (utility, invoked via `--changelog`)
Release utility that generates `CHANGELOG.md` via git-cliff and auto-bumps the semantic version in `spiral-ui/package.json` and `pyproject.toml` from the first CHANGELOG.md heading. Not part of the regular phase loop — invoked explicitly with `--changelog` flag. Replaces the deprecated interactive gate checkpoint (now handled by Phase 0).

### Phase I — Implement (Ralph)
Runs the Ralph autonomous agent loop. Phase I has four explicit sub-stages:

1. **Decompose** — oversized stories (complexity=large, or failing 2+ times) are split into 2–4 smaller sub-stories via `lib/decompose_story.py` before attempting implementation
2. **Execute** — Ralph picks the highest-priority incomplete story, spawns a fresh Claude instance (with optional Gemini pre-analysis injected), and the agent writes code. Small stories (`estimatedComplexity: small`) skip Gemini pre-analysis for speed. Gemini results are cached per story ID to avoid redundant API calls on retry.
3. **Retry** — on failure, increments the retry counter and escalates the model (haiku → sonnet → opus). At attempt 3, story auto-decomposes or is skipped.
4. **Commit / Revert** — if all quality gates pass, the worktree branch is merged and committed. If any gate fails, the branch is dropped and the working tree is reverted.

Before committing, 5 quality gates must all pass:

| Gate | What it checks |
|------|---------------|
| 1. TypeScript | Error count ≤ pre-story baseline |
| 2. Lint | `npm run lint` passes (if present) |
| 3. Secret scan | Gitleaks finds 0 secrets in staged diff |
| 4. Test ratchet | Passing test count ≥ pre-story baseline |
| 5. Security scan | 0 HIGH-severity findings from semgrep/bandit (if enabled) |

If any gate fails → code is reverted (`git reset --hard`), story retried up to 3 times, with model escalating each retry (haiku → sonnet → opus). After 3 failures → story auto-decomposes into 2–4 smaller sub-stories. Per-story cost is tracked; hard-stops at `SPIRAL_STORY_COST_HARD_USD` (default $2.00). In parallel mode (`--ralph-workers N`), N workers run simultaneously in isolated git worktrees, each working on a different story.

### Phase V — Validate
Runs `SPIRAL_VALIDATE_CMD` (your project's test suite: pytest, vitest, bats, etc.). Results saved to `test-reports/`. Optional extras: Lighthouse audit (`SPIRAL_LIGHTHOUSE=1`), Chrome DevTools screenshot (`SPIRAL_DEV_URL`), Pinchtab shell-driven E2E assertions (`SPIRAL_PINCHTAB_URL`).

### Phase C — Check Done
Calls `check_done.py` which exits 0 only when: (1) every story in `prd.json` has `passes: true`, AND (2) the latest test report has 0 failed/errored tests.

- **All stories pass:** Prints completion banner, generates dashboard, runs `SPIRAL_ON_COMPLETE` hook — then **always loops back to Phase A**. Phase A (AI Suggestions) can always find improvements; there is no "perfect system". SPIRAL **never exits due to "no new stories"** — the only exits are: max iterations reached, time limit hit, cost ceiling exceeded, or user quits. Phase C never exits on its own.
- **Stories still pending:** Loops back to Phase A immediately for the next iteration.

---

## CLI Flags Reference

```
bash spiral.sh [max_iters] [flags...]
```

| Flag | Default | Description |
|------|---------|-------------|
| `max_iters` (positional) | 20 | Total iterations to run |
| `--gate proceed\|skip\|quit` | interactive | Auto-answer Phase G gate |
| `--ralph-iters N` | 120 | Max inner Ralph iterations per Phase I |
| `--ralph-workers N` | 1 | Parallel workers (>1 uses git worktrees) |
| `--skip-research` | off | Skip Phase R entirely |
| `--capacity-limit N` | 50 | Skip Phase R when pending stories > N |
| `--model haiku\|sonnet\|opus` | auto | Override model routing for all workers |
| `--focus TEXT` | none | Scope Phase R to a theme (injected as hard constraint) |
| `--focus-tags TAG,TAG` | none | Only implement stories with matching tags |
| `--time-limit N` | 0 | Stop after N minutes (wall clock) |
| `--until HH:MM` | none | Stop at specific time (e.g. `--until 23:00`) |
| `--continuous` | off | Never stop — loop back to Phase A after all stories pass |
| `--monitor` / `--no-monitor` | on | Open terminal per worker (parallel mode only) |
| `--prd PATH` | prd.json | Override PRD file path |
| `--config PATH` | spiral.config.sh | Override config file |
| `--skip-conflict-preflight` | off | Bypass pre-flight cross-story conflict detection (parallel mode) |
| `--allow-unsafe-stories` | off | Warn but do NOT block stories with prompt injection patterns |
| `--allow-exec-writes` | off | Allow LLM to write executable files outside src/ and tests/ |
| `--no-cascade-skip` | off | Disable dependency cascade skip |
| `--dry-run` | off | Run control flow without API calls (test loop logic) |
| `--reset` | off | Delete checkpoint and start fresh |
| `--replay STORY_ID` | none | Re-run a single story in isolation (Phases I+V) |
| `--rollback STORY_ID` | none | Revert a story's commit and reset its `passes` flag |
| `--status` | off | Print current run state and exit |
| `--version` | off | Print SPIRAL version (from git tag) |
| `--doctor` | off | Check all dependencies and exit |
| `--migrate` | off | Upgrade prd.json schema and exit |
| `--archive-done` | off | Move completed stories to prd-archive.json and exit |
| `--changelog` | off | Generate CHANGELOG.md via git-cliff and exit |
| `--stale-report` | off | Print stories inactive beyond `SPIRAL_STALE_DAYS` |
| `--from-phase PHASE` | I | Used with `--replay`: start from this phase (I or V); reuses existing worktree |
| `--hint TEXT` | none | Used with `--replay`: inject extra context into Phase I system prompt |
| `--undo STORY_ID` | none | Replay undo log in reverse, restoring worktree to pre-attempt state |
| `--benchmark STORY_ID` | none | Benchmark a story across multiple models and compare results |
| `--models M1,M2,...` | none | Used with `--benchmark`: comma-separated model names to compare |
| `--list-plugins` | off | List all loaded plugins and their hooks, then exit |
| `--show-docs` | off | List generated API documentation with story ID mappings and exit |
| `--flaky-tests report` | off | Print quarantined flaky test registry and exit |
| `--calibration-report` | off | Print actual vs estimated complexity calibration data and exit |
| `--log-level DEBUG\|INFO\|WARN\|ERROR` | INFO | Output verbosity |
| `search QUERY` | — | Subcommand: search story backlog by natural language |
| `compact-prd` | — | Subcommand: strip transient runtime fields from prd.json |
| `status` | — | Subcommand: print color-coded progress table and exit |

### main.py Subcommands

```
uv run python main.py <subcommand> [args...]
```

| Subcommand | Description |
|------------|-------------|
| `status` | PRD completion summary |
| `estimate` | Pre-flight API cost projection for pending stories |
| `graph` | Generate Mermaid dependency graph from prd.json |
| `monitor --port 5299` | Unified monitoring snapshot (used by progress cron) |
| `diagnose` | Print causal failure chain for a run |
| `complexity-trend` | Analyze story retry & duration patterns across iterations |
| `show-blockers` | Analyze story dependency graph and critical paths |
| `replay` | Re-run a failed phase with DEBUG=1 and full state capture |
| `phase-timing-report` | Phase timing report with SLA breach analysis |
| `analyze-failures` | Categorize retry failure root causes and recommend tuning |
| `validate-commits` | Detect orphan stories and squash-commit patterns |
| `validate-federated` | Validate federated prd.json structure |
| `analyze-batch-potential` | Show Phase S batch grouping potential: API call reduction % |
| `config export-env` | Export spiral.config.sh SPIRAL_* variables as a .env file |
| `worktree audit` | Audit all spiral worker worktrees for health anomalies |
| `memory list` | Show 20 most recent episodic records with pass/fail outcomes |
| `dlq promote` | Mark stories as permanently failed after exhausting retries |
| `dlq list` | Show all permanently failed stories with failure reason |
| `dlq replay` | Retry a permanently failed story after human review |
| `search QUERY` | Search story backlog by natural language query |
| `compact-prd` | Strip transient runtime fields from prd.json |
| `import-github OWNER/REPO` | Import GitHub issues as stories into prd.json |
| `import-jira URL` | Import Jira issues as stories into prd.json |
| `import-csv FILE` | Import stories from a CSV file |
| `export-report` | Export run results as a formatted report |
| `namespace-check` | Check for naming conflicts across story IDs and file paths |
| `validate-results-tsv` | Validate results.tsv structure and data integrity |
| `phase-audit` | Compare phase timing across iterations with SLA breach detection |
| `detect-anomalies` | Detect cost/duration anomalies in results.tsv via z-score analysis |
| `federated-merge-prd` | Merge multiple prd.json files from federated projects |
| `analyze-routing` | Analyze model routing metrics and effectiveness |
| `extract-failed-stories` | Extract failed stories from results.tsv for triage |
| `init` | Run the interactive setup wizard |
| `run` | Execute spiral.sh (forwards all flags) |
| `show-logs` | Show recent log entries |
| `federation-health` | Federation health check across sub-projects |
| `federated-status` | Aggregate story status across sub-projects |
| `validate-federated-order` | Report merge order for federated PRD |
| `check-federated-deps` | Detect cycles & orphans in multi-repo dependencies |
| `list-federation` | Display sub-project configuration |
| `archive create` | Archive completed stories to prd-archive.json |
| `archive restore` | Restore archived stories back to prd.json |
| `archive manifest` | Show archive manifest with metadata |
| `lint-prd` | Lint prd.json for quality and consistency issues |
| `predict-complexity` | Predict story complexity from description/criteria |
| `cost-forecast` | Forecast remaining budget and timeline |
| `forecast-ceiling` | Forecast cost ceiling breach timing |
| `trace-dependencies` | Resolve and visualize dependency chain for a story |
| `show-story-lineage` | Show decomposition lineage tree for a story |
| `show-merge-order` | Show pending stories in topologically sorted merge order |
| `validate-governance` | Enforce per-project quotas & ID patterns |
| `validate-phase-outputs` | Validate .spiral/ phase output files against schemas |
| `validate-scc-cycles` | Detect circular dependencies using Tarjan's SCC algorithm |
| `categorize-failures` | Categorize failure root causes with recommendations |
| `show-slowest-stories` | Identify bottleneck stories by total duration from results.tsv |
| `show-ac-results STORY_ID` | Display per-AC verification results for a story |
| `show-dead-features` | List all detected dead features across stories |
| `show-perf-baseline` | Display per-phase performance baseline statistics |
| `explain-retry` | Analyze retry sequence and suggest decomposition for a story |
| `list-orphan-commits` | List commits lacking US-/UT- story ID tags |
| `predict-model-escalation` | Predict next-attempt model escalation for a story |
| `preflight-check` | Validate SPIRAL runtime dependencies and configuration |
| `debug-worker-state` | Dump live worker state and diagnostics as JSON |
| `timing-report` | Cross-phase timing analyzer with bottleneck detection |
| `score-stories-for-validation` | Score each story 0-100 for validation confidence |
| `federation-health-check` | Validate federated PRD: sub-project refs, circular deps, ID namespaces |
| `federation-conflict-check` | Detect file conflicts across sub-projects with resolution hints |
| `federation-check-cycles` | Detect circular dependencies with cycle paths |
| `federation-impact-analyze` | Transitive dependency blast radius report for a sub-project |
| `federation-audit` | Query federation audit trail (filter by sub-project, action) |
| `validate-federated-schema` | Cross-project duplicate ID and namespace validation |
| `federated-cost-report` | Per-sub-project cost breakdown by phase |
| `deploy-docs` | Deploy CHANGELOG and pdoc outputs to gh-pages branch |

---

## Configurable Options Reference

### Loop & Iteration Control
| Config Var | Default | Description |
|------------|---------|-------------|
| positional arg | 20 | Max spiral iterations |
| `--time-limit N` | **720 (12 h)** | Stop after N minutes (0 = unlimited) |
| `--until HH:MM` | none | Stop at wall-clock time |
| `SPIRAL_STORY_BATCH_SIZE` | 0 (off) | Show only N highest-priority stories to Ralph per iter |
| `SPIRAL_MAX_PENDING` | **30** | Pause story pipeline (R→T→S→M) when undone stories ≥ N; resume when count drops below N. 0 = unlimited |
| `SPIRAL_MAX_STORIES` | 100 | Warn when total stories exceed N |
| `SPIRAL_MAX_STORIES_ABORT` | 0 | Hard-abort when story count exceeded (0 = warn only) |
| `SPIRAL_COST_CEILING` | — | Abort when cumulative API spend exceeds USD threshold |
| `SPIRAL_ZERO_PROGRESS_LIMIT` | 0 (disabled) | Abort after N consecutive zero-progress iterations. Disabled by default — Phase A always suggests improvements so SPIRAL loops indefinitely until time limit / max iters |
| `SPIRAL_CASCADE_FAN_OUT_LIMIT` | 5 | Max consecutive story failures before Phase I aborts (0 = disabled) |
| `SPIRAL_CONSECUTIVE_FAIL_ABORT` | 0 | Stop loop after N consecutive zero-progress iterations (0 = disabled) |
| `SPIRAL_CONTINUOUS` | false | Never stop on all-pass — loop back to Phase A for new story discovery (`--continuous`) |
| `SPIRAL_CONTINUOUS_COOLDOWN_SECS` | 60 | Cooldown seconds between discovery cycles when all stories pass |

### AI Suggestions (Phase A)
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_MAX_AI_SUGGEST` | 5 | Max AI-generated story suggestions per iteration (0 = disable Phase A) |
| `SPIRAL_AI_SUGGEST_MODEL` | haiku | Claude model for constitution-aware gap analysis |
| `SPIRAL_AI_SUGGEST_MIN_SCORE` | 0 | Quality filter score (0-100) for AI suggestions; reject below threshold |
| `SPIRAL_TEST_STORY_MIN_COMPLEXITY` | medium | Min complexity to generate paired test stories |
| `SPIRAL_TEST_SUITE_TYPES` | — | Comma-separated test suite types to populate (smoke,regression,security,performance) |

### Research (Phase R)
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_RESEARCH_MODEL` | sonnet | Model for Phase R |
| `SPIRAL_RESEARCH_TIMEOUT` | 300s | Phase R wall-clock timeout |
| `SPIRAL_RESEARCH_RETRIES` | 2 | Retry Phase R if output missing/invalid (3 total attempts) |
| `SPIRAL_RESEARCH_CACHE_TTL_HOURS` | 24 | Cache URL responses (0 = disabled) |
| `SPIRAL_MAX_RESEARCH_STORIES` | 0 | Cap new research stories per iteration (0 = unlimited) |
| `SPIRAL_FIRECRAWL_ENABLED` | 0 | Use Firecrawl MCP for scraping (requires `FIRECRAWL_API_KEY`) |
| `SPIRAL_GEMINI_PROMPT` | — | Gemini 2.5 Pro pre-research prompt (empty = skip Gemini) |
| `SPIRAL_GEMINI_ANNOTATE_PROMPT` | — | Gemini prompt for filesTouch annotation in parallel mode (empty = skip) |
| `SPIRAL_FOCUS` | — | Theme to scope research (also injectable via `--focus`) |
| `SPIRAL_CACHE_SIM_THRESHOLD` | 0.92 | Cosine similarity threshold for semantic cache hits (1.0 = exact only) |
| `SPIRAL_RESEARCH_SUMMARY_THRESHOLD` | 0 | Token threshold for hierarchical summarization of Phase R output (0 = disabled) |
| `SPIRAL_USE_FULL_RESEARCH` | 0 | Bypass summarization and pass full research to downstream phases |

### Story Validation (Phase S)
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_SPECKIT_CONSTITUTION` | — | Path to constitution.md — injected into Phase S, Phase R, and Ralph |
| `SPIRAL_STORY_VALIDATE_MIN_OVERLAP` | 1 | Min keyword overlap with `goals[]` for a story to be accepted |
| `SPIRAL_VALIDATION_VOTES` | 3 | Independent LLM validation calls per story; majority-vote consensus (1 = no voting) |
| `SPIRAL_SEMANTIC_DEDUP_THRESHOLD` | 0.85 | TF-IDF cosine similarity threshold for near-duplicate rejection (0 = disabled) |
| `SPIRAL_BATCH_VALIDATE` | 1 | Use Anthropic Message Batches API for Phase S (50% cost reduction) |

### Story Enrichment (Phase E)
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_STORY_ENRICHMENT` | false | `true` to enable Phase E enrichment pass |
| `SPIRAL_STORY_ENRICHMENT_MODEL` | sonnet | Claude model for story enrichment |

### Test Synthesis (Phase T)
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_SKIP_TEST_SYNTHESIS` | 0 | Skip Phase T entirely |
| `SPIRAL_SYNTHESIZE_TESTS_FOR_NEW` | 0 | Create paired UT- stories for each new feature story |
| `SPIRAL_TEST_SYNTH_TIMEOUT` | 60s | Phase T timeout |
| `SPIRAL_REPORTS_DIR` | test-reports | Where test reports are written |

### Implementation (Phase I / Ralph)
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_IMPL_TIMEOUT` | 600s | Phase I timeout |
| `SPIRAL_WORKER_TIMEOUT` | 600s | Per-worker timeout (parallel mode) |
| `SPIRAL_MODEL_ROUTING` | auto | Default model tier (auto\|haiku\|sonnet\|opus) |
| `SPIRAL_DECOMPOSE_THRESHOLD` | 2 | Auto-decompose story at this retry count (0 = disabled) |
| `SPIRAL_MAX_DIFF_LINES` | 500 | Abort commit if diff exceeds N lines (0 = disabled) |
| `SPIRAL_MAX_FILES_PER_STORY` | 10 | Warn/abort if story touches > N files (0 = disabled) |
| `SPIRAL_SCOPE_CREEP_ACTION` | warn | "warn" or "abort" on scope creep detection |
| `SPIRAL_STORY_COST_WARN_USD` | 0.50 | Warn when single story costs more than $N |
| `SPIRAL_STORY_COST_HARD_USD` | 2.00 | Abandon story when cost exceeds $N |
| `SPIRAL_SKIP_STORY_IDS` | — | Comma-separated IDs to permanently skip |
| `SPIRAL_AUTO_INFER_DEPS` | false | Infer story dependencies from filesTouch overlap |
| `SPIRAL_THINKING_EFFORT` | high | Thinking effort level for 4.6 models (low/medium/high/max) |
| `SPIRAL_THINKING_BUDGET_TOKENS` | 10000 | Maximum thinking tokens per story (0 = disable thinking) |
| `SPIRAL_MODEL_FALLBACK_CHAIN` | — | Colon-separated fallback models (e.g. `sonnet:haiku:opus`) |
| `SPIRAL_CACHE_TTL` | 7 | Days before research cache entries are pruned |
| `SPIRAL_STORY_TIMEOUT_SMALL` | 300 | Timeout (seconds) for small-complexity stories |
| `SPIRAL_STORY_TIMEOUT_MEDIUM` | 600 | Timeout (seconds) for medium-complexity stories |
| `SPIRAL_STORY_TIMEOUT_LARGE` | 1200 | Timeout (seconds) for large-complexity stories |
| `SPIRAL_ESCALATION_RETRY_SONNET` | 1 | Retry count at which haiku escalates to sonnet |
| `SPIRAL_ESCALATION_RETRY_OPUS` | 2 | Retry count at which sonnet escalates to opus |

### Validation (Phase V)
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_VALIDATE_CMD` | — | Test suite command (required) |
| `SPIRAL_VALIDATE_TIMEOUT` | 300s | Phase V timeout |
| `SPIRAL_INCREMENTAL_VALIDATE` | false | Only run tests for files touched in current iter |
| `SPIRAL_DEV_URL` | — | Dev server URL for Chrome DevTools screenshot |
| `SPIRAL_LIGHTHOUSE` | 0 | Run Lighthouse audit after tests |
| `SPIRAL_LIGHTHOUSE_URL` | — | Lighthouse target URL |
| `SPIRAL_LIGHTHOUSE_THRESHOLD` | 50 | Min Lighthouse score % |
| `SPIRAL_PINCHTAB_URL` | — | Pinchtab server for shell E2E assertions |
| `SPIRAL_PINCHTAB_E2E_CMD` | — | Custom Pinchtab E2E script |

### Git & Commits
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_GIT_AUTHOR` | git config | AI commit author name |
| `SPIRAL_GIT_EMAIL` | git config | AI commit author email |
| `SPIRAL_BRANCH_PREFIX` | spiral-worker | Prefix for per-story feature branch names |
| `SPIRAL_CREATE_PRS` | false | Auto-create GitHub PR per passed story |
| `SPIRAL_PR_BASE_BRANCH` | main | PR target branch |
| `SPIRAL_PR_DRAFT` | false | Create draft PRs |
| `SPIRAL_PATCH_DIRS` | all | Limit git diffs to these dirs (parallel mode) |
| `SPIRAL_DEPLOY_CMD` | — | Shell command to run after parallel workers complete |
| `SPIRAL_WORKSPACE_CLEANUP` | 0 | Auto-delete transient `.spiral/` artifacts on successful completion |

### Memory & Workers
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_WORKER_MEMORY_LIMIT` | 1024 MB | V8 heap cap per Claude process |
| `SPIRAL_MEMORY_THRESHOLD` | 1536 MB | Watchdog kill threshold |
| `SPIRAL_LOW_POWER_MODE` | 1 | Enable graduated memory pressure management |
| `SPIRAL_PRESSURE_THRESHOLDS` | 40,25,18,12 | % free RAM for pressure levels 1–4 |
| `SPIRAL_PREEMPTIVE_PRESSURE_MB` | 0 | Trigger level 1 if free RAM < N MB (0 = off) |
| `SPIRAL_QUEUE_STALL_WARN_SECS` | 600 | Alert if parallel worker queue stalls this long |
| `SPIRAL_WORK_STEALING` | false | Idle workers claim stories from a shared queue instead of sitting idle |
| `SPIRAL_DISPATCH_MODE` | dag | Worker scheduling: `dag` (tier-aware) or `parallel` (legacy all-parallel) |
| `SPIRAL_MEMORY_POOL` | true | Dynamic per-story memory reservation from shared pool |
| `SPIRAL_POOL_RESERVE_MB` | 1024 | RAM excluded from pool for OS + orchestrator overhead |
| `SPIRAL_POOL_TIER_SMALL` | 768 | Memory reservation (MB) for small/haiku stories |
| `SPIRAL_POOL_TIER_MEDIUM` | 1536 | Memory reservation (MB) for sonnet stories |
| `SPIRAL_POOL_TIER_LARGE` | 2560 | Memory reservation (MB) for opus stories |
| `SPIRAL_POOL_V8_HEAP_FRACTION` | 65 | V8 heap as percentage of reservation (remainder = non-heap overhead) |
| `SPIRAL_POOL_RECLAIM_INTERVAL` | 30 | Seconds between dead-PID reservation reclaim sweeps |
| `SPIRAL_MEMORY_GATE_MB` | 1536 | Per-worker free RAM required before launch |
| `SPIRAL_MEMORY_WAIT_MAX_MINS` | 2 | Max minutes to wait at memory gate (0 = wait forever) |

### Security Scanning
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_SECURITY_SCAN` | false | Enable security gate in Ralph (gate 5) |
| `SPIRAL_SECURITY_SCAN_TOOL` | semgrep | "semgrep" or "bandit" |
| `SPIRAL_SECURITY_SCAN_ARGS` | — | Extra flags for the scanner |

### Hooks & Notifications

> **Note:** The `peon-ping` sound hook (plays audio on Claude Code events) is **disabled by default**. Users who want sound notifications can enable it via `/peon-ping-toggle`. SPIRAL does not enable or manage peon-ping automatically.

| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_PRE_PHASE_HOOK` | — | Script run before each phase (non-zero = abort) |
| `SPIRAL_POST_PHASE_HOOK` | — | Script run after each phase (non-zero = warn) |
| `SPIRAL_ON_COMPLETE` | — | Shell command on successful completion |
| `SPIRAL_NOTIFY_WEBHOOK` | — | HTTP POST JSON at phase start/end |
| `SPIRAL_NOTIFY_WEBHOOK_HEADERS` | — | Extra HTTP headers for webhook |

### Logging & Display
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_LOG_LEVEL` | INFO | DEBUG\|INFO\|WARN\|ERROR |
| `SPIRAL_LOG_MAX_MB` | 50 | Rotate `ralph-run.log` when it exceeds N MB (0 = off) |
| `SPIRAL_OPEN_DASHBOARD` | 1 | Auto-open HTML dashboard after each iter |
| `SPIRAL_DASHBOARD_REFRESH_SECS` | 30 | Dashboard HTML auto-refresh interval |
| `SPIRAL_PROGRESS_MAX_LINES` | 2000 | Rotate progress.txt at N lines (0 = off) |
| `SPIRAL_STALE_DAYS` | — | Days before a story is flagged as stale |
| `SPIRAL_GITNEXUS_REPO` | — | GitNexus repo name for smarter file-story mapping |

### Tool & Inference
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_PROGRAMMATIC_TOOLS` | auto | Enable code_execution tool for orchestrated multi-tool calls (`true`/`false`/`auto`) |
| `SPIRAL_INTERLEAVED_THINKING` | false | Enable interleaved thinking between tool calls (doubles token consumption) |
| `SPIRAL_EPISODIC_MEMORY` | false | Inject top-3 similar past implementations from episodic memory DB |
| `SPIRAL_DEFERRED_TOOLS` | true | Enable deferred tool loading for reduced prompt size |

### Context Injection
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_CONTEXT_WINDOW_MARGIN` | 0.85 | Upgrade model when prompt exceeds this fraction of context window |
| `SPIRAL_CONTEXT_MODE` | diff | `diff` = inject git diff; `full` = inject full file contents |
| `SPIRAL_DIFF_DEPTH` | 3 | Number of commits to diff against (`git diff HEAD~N`) |
| `SPIRAL_REPO_MAP` | false | Enable Phase X per-story symbol map generation |
| `SPIRAL_REPO_MAP_MAX_LINES` | 150 | Max lines per story symbol map |

### Quality & Retry Strategy
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_ANTI_PATTERN_INJECT` | true | Append failure reasons as FORBIDDEN APPROACHES on retry |
| `SPIRAL_DECOMPOSE_ON_FIRST_FAIL` | true | Immediately decompose on first failure if complexity >= threshold |
| `SPIRAL_DECOMPOSE_FIRST_FAIL_COMPLEXITY` | medium | Min complexity for first-fail decomposition (`small`/`medium`/`large`) |
| `SPIRAL_STRICT_SCOPE_GUARD` | false | Strict scope enforcement beyond warn/abort |

### Observability (OTel)
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_OTEL_EMIT_MESSAGES` | false | Emit gen_ai input/output message attributes (opt-in for privacy) |
| `SPIRAL_OTEL_SCRUB_PATTERNS` | all | Comma-separated privacy scrub patterns (anthropic_api_key, github_token, etc.) |
| `SPIRAL_OTEL_SCRUB_FIELDS` | gen_ai.input/output.messages | Attribute names to fully redact |

### Local Fallback (Ollama)
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_OLLAMA_FALLBACK_MODEL` | — | Ollama model name for local fallback (requires `ollama serve`) |
| `SPIRAL_OLLAMA_HOST` | http://localhost:11434/v1 | Ollama API base URL |
| `SPIRAL_LOCAL_FALLBACK_POLICY` | — | Policy for local model fallback (`allow`/`deny`/unset) |

### ADR & Self-Review
| Config Var | Default | Description |
|------------|---------|-------------|
| `SPIRAL_SKIP_ADR` | false | Skip ADR (Architecture Decision Record) generation |
| `SPIRAL_ADR_MODEL` | haiku | Model for ADR generation |
| `SPIRAL_SKIP_SELF_REVIEW` | false | Skip post-implementation self-review pass |
| `SPIRAL_SELF_REVIEW_MODEL` | haiku | Model for self-review pass |

---

## prd.json Schema

```json
{
  "schemaVersion": 1,
  "productName": "string",
  "branchName": "string",
  "overview": "string",
  "goals": ["goal 1", "goal 2"],
  "epics": [{"id": "E-1", "title": "string", "description": "string"}],
  "userStories": [
    {
      "id": "US-001",
      "title": "Short imperative title (max 100 chars)",
      "description": "What and why",
      "priority": "critical|high|medium|low",
      "acceptanceCriteria": ["criterion 1"],
      "dependencies": ["US-000"],
      "passes": false,
      "filesTouch": ["path/to/file.py"],
      "estimatedComplexity": "small|medium|large",
      "technicalNotes": ["implementation hint"],
      "tags": ["tag1"],
      "epicId": "E-1",
      "model": "haiku|sonnet|opus"
    }
  ]
}
```

Internal fields written by SPIRAL (do not set manually): `_passedCommit`, `_decomposed`, `_decomposedFrom`, `_decomposedInto`, `_failureReason`, `_skipped`, `_scopeCreep`, `_prUrl`.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success — all stories pass + tests clean |
| 2 | Bad CLI arguments |
| 3 | Missing or invalid spiral.config.sh |
| 4 | Required tool not found (jq, claude, etc.) |
| 5 | prd.json not found |
| 6 | prd.json corrupted and unrecoverable |
| 7 | prd.json schema version too new |
| 8 | Cost ceiling exceeded |
| 9 | Zero-progress limit reached (stuck) |
| 10 | `--replay` mode: story failed |
| 11 | `--replay` mode: story ID not found |
| 12 | `--rollback` mode: git revert failed |
| 13 | Max iterations reached; stories still remain |
| 14 | Claude API unreachable at startup probe |
| 15 | Consecutive story failures exceeded cascade fan-out limit |
| 130 | Interrupted by Ctrl+C (checkpoint saved, run again to resume) |

---

## Example Launch Commands

```bash
# 5 iterations, auto-proceed
bash "$SPIRAL_HOME/spiral.sh" 5 --gate proceed

# Run until 11pm tonight
bash "$SPIRAL_HOME/spiral.sh" 99 --until 23:00 --gate proceed

# Run for 2 hours
bash "$SPIRAL_HOME/spiral.sh" 99 --time-limit 120 --gate proceed

# Focus on a specific area (scopes Phase R to that theme)
bash "$SPIRAL_HOME/spiral.sh" 10 --focus "performance" --gate proceed

# Parallel workers + monitor terminals (ONLY if user explicitly requests — confirm first)
bash "$SPIRAL_HOME/spiral.sh" 10 --ralph-workers 2 --monitor

# Skip research (implementation-only, faster)
bash "$SPIRAL_HOME/spiral.sh" 5 --skip-research --gate proceed

# Cap capacity to avoid research overload on large PRDs
bash "$SPIRAL_HOME/spiral.sh" 10 --capacity-limit 20 --ralph-iters 200

# Fast + cheap run (haiku model, no research)
bash "$SPIRAL_HOME/spiral.sh" 3 --model haiku --skip-research

# Rollback a specific story's commit
bash "$SPIRAL_HOME/spiral.sh" --rollback US-042

# Re-run a single story in isolation
bash "$SPIRAL_HOME/spiral.sh" --replay US-042

# Check current state
bash "$SPIRAL_HOME/spiral.sh" --status
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| All stories done but Spiral keeps running | Expected — Phase R discovers new stories each iteration. Set `--until HH:MM` or `--time-limit N` to stop at a specific time |
| Tests failing immediately | Check `SPIRAL_VALIDATE_CMD` in `spiral.config.sh` |
| Workers not merging cleanly | Reduce `--ralph-workers` to 1 |
| Research phase slow or unhelpful | Add `--skip-research`, reduce `--capacity-limit`, or set `SPIRAL_FOCUS` |
| OOM / out of memory | Reduce `--ralph-workers`, lower `SPIRAL_WORKER_MEMORY_LIMIT`, or set `SPIRAL_PREEMPTIVE_PRESSURE_MB` |
| Story keeps failing (3 retries) | It will auto-decompose into sub-stories; or rollback with `--rollback STORY_ID` |
| Story too expensive | Lower `SPIRAL_STORY_COST_HARD_USD`; use `--model haiku` |
| Dashboard not opening | Set `SPIRAL_OPEN_DASHBOARD=1` in `spiral.config.sh` |
| Firecrawl errors | Verify `FIRECRAWL_API_KEY` env var is set |
| GitNexus not annotating | Run `gitnexus analyze` first in the repo |
| `prd.json` corrupted after crash | Auto-restored from `.spiral/prd-backups/prd-iter*.json`; no manual fix needed |
| Stale `spiral-worker-*` branches | Auto-purged on next run startup |
| `index.lock` blocking git ops | Auto-removed before worktree creation on next run |
| Phase T hanging | Default 60s timeout auto-kills it; set `SPIRAL_TEST_SYNTH_TIMEOUT` to adjust |
| Deferred workers never launch | Check memory pressure — stalls warn after `SPIRAL_QUEUE_STALL_WARN_SECS` (600s) |
| `.rej` files after parallel run | Check `spiral_events.jsonl` for `patch_rejected` events; delete `.rej` files manually |
| Wrong time in iteration calculation | Run `date "+%H:%M"` manually — the skill uses real system time, not AI estimates |
| `prd.json.lock` blocking workers | Lock includes PID; stale locks from dead processes are auto-broken. Manual fix: `rm prd.json.lock` |
| Duplicate stories after crash | Transaction journal auto-recovers on next iteration; check `.spiral/_txn_journal.jsonl` |
| Worker idle while others have stories | Set `SPIRAL_WORK_STEALING=true` in `spiral.config.sh` to enable work-offering queue |
| Heartbeat shows 0 completed | Check that `SPIRAL_STORIES_COMPLETED` env var is incremented by the worker |

---

## Crash Recovery & Reliability

| Failure | Auto-Recovery |
|---------|--------------|
| `prd.json` corrupted mid-write | Validated with `jq empty` each iteration; restored from latest `.spiral/prd-backups/prd-iter*.json` |
| Interrupted run (Ctrl+C) | Checkpoint saved at last completed phase; re-run to resume from where it stopped |
| OOM-killed worker leaves `index.lock` | Removed before worktree creation on next run |
| OOM-killed worker leaves `prd.json.lock` | PID written to lock file; stale locks (dead PID) auto-broken on next acquisition attempt. `cleanup_parallel()` also removes all lock files |
| Orphaned `spiral-worker-*` branches | Auto-deleted at startup if not in any live worktree |
| Phase T hangs | Killed after `SPIRAL_TEST_SYNTH_TIMEOUT` seconds (default 60s); empty output used as fallback |
| Crash between overflow + prd.json writes (Phase M) | Write-ahead transaction journal (`_txn_journal.jsonl`) rolls back incomplete multi-file writes on next iteration startup |
| Stuck story never requeued | Force-reset if `.passes` not correctly set to `false`; check heartbeat log (now includes `completed` count and `phase`) |
| `/tmp` fill-up from previous runs | Temp files cleaned on startup |
| Deferred worker queue stalled | Warns with actionable message after `SPIRAL_QUEUE_STALL_WARN_SECS` (default 600s) |
| Worker finishes early, sits idle | `SPIRAL_WORK_STEALING=true` enables finished workers to claim uncompleted stories from a shared queue |
| Parallel worker retry counts lost | Per-worker `retry-counts.json` merged back to root after each parallel wave |
| **Locked worktrees block all workers** | Worktrees locked by crashed runs resist `--force` removal. Fix: `git worktree unlock <path>` before `git worktree remove`. The `run_parallel_ralph.sh` startup cleanup handles this automatically since 2026-03-20 |
| **Memory watchdog crashes under `set -e`** | `powershell.exe` watchdog exits immediately on Windows, triggering EXIT trap. Fix: `SPIRAL_MEMORY_WATCHDOG=0` env var to disable, or fix the watchdog to handle errors |
| **Auto-stash reverts uncommitted config changes** | `spiral.sh` auto-stashes dirty files before Phase I, then pops after. Config changes to `spiral.config.sh` get reverted each iteration. Fix: **commit config changes to git** so stash pop can't overwrite them |
| **`resolve_model` missing 3rd arg** | `ralph.sh:2190` calls `resolve_model` with 2 args but function expects 3. Crashes with `$3: unbound variable` under `set -u`. Fix: pass `$(get_escalation_count "$NEXT_STORY")` as 3rd arg |
| **Story timeout too short for complex stories** | Default medium=900s is insufficient for integration tests and CLI tools. Set in `spiral.config.sh` (not env vars — config overrides env). Recommended: small=1200s, medium=1800s, large=2400s |
| **Corrupt story title (ID as title)** | Phase M occasionally assigns story ID as title. Ralph can't implement "US-521". Fix: manually correct title in prd.json |

---

## Operations Guide (Monitoring & Auto-Restart)

Monitoring is built into the launch flow — see **Section 3e (Auto Progress Loop)** for the full cron template. The progress check automatically diagnoses and fixes common problems when no new stories pass.

For manual monitoring or when setting up a check outside the skill flow:

```bash
# Quick status (pass counts + completion %)
uv run python main.py status

# Check if UI dashboard is responding
curl -s -o /dev/null -w "%{http_code}" http://localhost:5299

# Check if Spiral process is still alive
tail -5 .spiral/_last_run.log   # recent timestamps = still running
```

### Recommended Launch Command (Low Memory / Windows)

```bash
SPIRAL_MEMORY_WATCHDOG=0 \
SPIRAL_STORY_ENRICHMENT=false \
SPIRAL_STORY_COST_HARD_USD=10.00 \
SPIRAL_STORY_COST_WARN_USD=5.00 \
bash spiral.sh 5 --gate proceed --ralph-workers 1
```

- `--ralph-workers 1`: Default and safest option — never use more without explicit user confirmation
- `SPIRAL_STORY_ENRICHMENT=false`: Skips Phase E (each enrichment spawns Claude CLI, memory risk)
- `SPIRAL_MEMORY_WATCHDOG=0`: Avoids powershell watchdog crash on Windows
- `SPIRAL_STORY_COST_HARD_USD=10.00`: Allows complex stories to complete (default $2 is too low)

### When No New Stories Are Passing

If a progress check shows no new stories passed, investigate in this order:

1. **Is Spiral still running?** → Check if `_last_run.log` has recent timestamps. If not, restart it.
2. **Worktrees locked?** → `git worktree list` — unlock and remove stale entries
3. **Ralph crashing?** → Check `.spiral/crashes/US-*` for error messages
4. **Timeout too short?** → Check `Budget: Ns` in output — increase in `spiral.config.sh` (must commit!)
5. **Story title corrupt?** → Check `prd.json` — fix manually if title equals story ID
6. **Config being reverted?** → Commit `spiral.config.sh` changes to git so auto-stash doesn't undo them
7. **Budget ran out?** → Raise `SPIRAL_STORY_COST_HARD_USD` (default $2 too low for sonnet/opus)

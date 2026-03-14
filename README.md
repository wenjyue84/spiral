# SPIRAL

[![CI](https://github.com/wenjyue84/spiral/actions/workflows/ci.yml/badge.svg)](https://github.com/wenjyue84/spiral/actions/workflows/ci.yml)

**Self-iterating PRD Research & Implementation Autonomous Loop**

SPIRAL autonomously discovers requirements, validates and merges user stories, then implements them. A one-time startup clarification aligns goals before the loop begins; the loop then runs Research → Test Synthesis → Story Validate → Merge → Implement → Validate → Check Done until all stories pass.

It ships with **Ralph** (the implementation engine) and **two skills** (`/ralph` and `/prd`) bundled — one `git clone` gives you everything.

## One-Command Install

```bash
bash <(curl -sL https://raw.githubusercontent.com/wenjyue84/spiral/main/setup.sh)
```

Or manually:

```bash
git clone https://github.com/wenjyue84/spiral.git ~/.ai/Skills/spiral
bash ~/.ai/Skills/spiral/setup.sh
```

## Prerequisites

| Tool | Required? | Install |
|------|-----------|---------|
| **git** | Yes | [git-scm.com](https://git-scm.com/downloads) |
| **bash** | Yes | Git Bash / MSYS2 (Windows), native (Mac/Linux) |
| **Python 3.10+** | Yes | `choco install python3` / `brew install python3` / `apt install python3` |
| **Node.js 16+** | Yes | `choco install nodejs` / `brew install node` / `apt install nodejs` |
| **jq** | Windows: bundled | `brew install jq` / `apt install jq` |
| **Claude CLI** | Yes | `npm install -g @anthropic-ai/claude-code` |
| **Gemini CLI** | Optional | `npm install -g @google/gemini-cli` |
| **Codex CLI** | Optional | `npm install -g @openai/codex` |
| **Firecrawl MCP** | Optional | See [Firecrawl setup](#firecrawl-mcp-optional) below |
| **Chrome DevTools MCP** | Optional | `npm i -g chrome-devtools-mcp` — see [Browser Testing](#browser-testing-optional) below |
| **agent-browser skill** | Optional | See [Browser Testing](#browser-testing-optional) below |
| **Pinchtab** | Optional | `npm i -g pinchtab` — shell-driven Phase V E2E assertions, see [Browser Testing](#browser-testing-optional) |
| **Lightpanda** | Optional | [lightpanda.io](https://lightpanda.io) — fast headless browser (Zig-based), drop-in Chrome alternative |
| **Peon Ping** | Optional | Claude Code skill — plays audio when Ralph finishes a story so you know when to check in |

`setup.sh` auto-installs everything except git.

## AI Model Strategy

SPIRAL uses multiple AI models to optimize cost, speed, and quality:

| Model | Role | When Used | Why |
|-------|------|-----------|-----|
| **Claude Haiku/Sonnet/Opus** | Primary engine | Phase I (implementation), Phase R (research fallback) | Auto-routes by story complexity — haiku for trivial, opus for hard |
| **Gemini 2.5 Pro** | Token saver | Phase R (web research pre-fetch) | Free-tier web search; feeds results to Claude so it skips URL browsing |
| **Firecrawl MCP** | Token saver | Phase R (URL scraping) | Returns clean LLM-optimized markdown; handles JS-rendered pages; offloads heavy scraping |
| **Codex (GPT-5)** | Token saver | Phase I (`UT-*` test stories via `--tool auto`) | Offloads simple test fixes from Claude |
| **Qwen Code** | Token saver | Phase I (first attempt via `--tool auto`) | Unlimited local/free-tier; Claude retries on failure |

**Default mode:** Claude handles everything. Use `--tool auto` in Ralph to enable multi-model routing.

**Token-saving strategy:**
1. **Phase R discovery:** Gemini runs free web search → Claude synthesizes results without browsing URLs
2. **Phase R scraping:** Firecrawl (optional) converts raw HTML → clean markdown before Claude reads it
3. **Phase I routing:** `--tool auto` sends simple stories to Qwen/Codex first; escalates to Claude on retry
4. **Model routing:** Ralph auto-selects haiku/sonnet/opus per story complexity; escalates on retry

## Quickstart

### Option A: Setup Wizard (Recommended)

In any project directory inside Claude Code, run:

```
/spiral-init
```

The wizard will:
1. **Scan your codebase** — detects language, framework, test runner, project structure
2. **Ask questions** — project goals, test command, model preferences (with pre-filled defaults from scan)
3. **Generate config files** — `spiral.config.sh`, `prd.json`, `progress.txt`, updates `.gitignore`

The wizard also triggers automatically if you run `/ralph` in a project that hasn't been set up yet.

### Option B: Manual Setup

```bash
# 1. Install
bash <(curl -sL https://raw.githubusercontent.com/wenjyue84/spiral/main/setup.sh)

# 2. Set up a test project
mkdir my-project && cd my-project
cp ~/.ai/Skills/spiral/templates/prd.example.json prd.json
cp ~/.ai/Skills/spiral/templates/spiral.config.example.sh spiral.config.sh
echo ".spiral/" >> .gitignore
git init && git add -A && git commit -m "init"

# 3. Run research + merge only (no implementation)
bash ~/.ai/Skills/spiral/spiral.sh 1 --gate skip

# 4. Run fully autonomous
bash ~/.ai/Skills/spiral/spiral.sh 20 --gate proceed

# 5. Run with 3 parallel workers
bash ~/.ai/Skills/spiral/spiral.sh 5 --gate proceed --ralph-workers 3
```

## How It Works

SPIRAL runs in two stages: a **one-time startup** to align on goals and stories, then a **repeating loop** that researches, validates, merges, implements, and checks until all stories pass.

```
  ┌─────────────────────────────────────────────────────────────────┐
  │  STARTUP  (runs once before the loop)                           │
  │                                                                 │
  │  0) CLARIFY                                                     │
  │     Set focus → clarifying questions → elaborate initial stories│
  │     Skipped in --gate proceed / --gate skip mode                │
  └──────────────────────────────┬──────────────────────────────────┘
                                 │
  ┌──────────────────────────────▼──────────────────────────────────┐
  │  STORY PREPARATION  (per iteration — builds the backlog)        │
  │                                                                 │
  │  R) RESEARCH                                                    │
  │     Gemini web pre-fetch → Claude agent → story candidates      │
  │                            │                                    │
  │  T) TEST SYNTHESIS                                              │
  │     Scan test-reports/ failures → regression story candidates   │
  │                            │                                    │
  │  S) STORY VALIDATE  ← new                                       │
  │     Constitution · goal alignment · quality · dedup checks      │
  │     Rejects out-of-scope or vague stories before merge          │
  │                            │                                    │
  │  M) MERGE                                                       │
  │     Patch prd.json with validated stories                       │
  │     Overflow → _research_overflow.json (next iteration)         │
  └──────────────────────────────┬──────────────────────────────────┘
                                 │
  ┌──────────────────────────────▼──────────────────────────────────┐
  │  IMPLEMENTATION  (per iteration — turns stories into code)      │
  │                                                                 │
  │  I) IMPLEMENT                                                   │
  │   ├─ Decompose  — split oversized stories into sub-stories      │
  │   ├─ Execute    — Ralph workers (sequential or parallel)         │
  │   ├─ Retry      — failure → escalate model → skip at attempt 3  │
  │   └─ Commit/Revert — merge on pass · drop branch on fail        │
  │                            │                                    │
  │  V) VALIDATE                                                    │
  │     Run project test suite (full or incremental)                │
  │                            │                                    │
  │  C) CHECK DONE                                                  │
  │     Always loops back to R to discover more stories             │
  │     Loop exits only when the time limit set in Phase 0 is hit  │
  └─────────────────────────────────────────────────────────────────┘
```

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for full phase reference and the modular file structure.

## CLI Options

```
bash spiral.sh [max_iters] [options]

Options:
  --gate proceed|skip|quit   Auto-answer gate prompts (default: interactive)
  --ralph-iters N            Max inner implementation iterations (default: 120)
  --ralph-workers N          Parallel worktree workers (default: 1)
  --skip-research            Skip Phase R (web research)
  --capacity-limit N         Skip Phase R when pending > N (default: 50)
  --model haiku|sonnet|opus  Claude model override (default: auto-route by complexity)
  --monitor                  Open terminal per worker (default: on)
  --no-monitor               Disable per-worker terminals
  --config PATH              Path to spiral.config.sh (default: $REPO_ROOT/spiral.config.sh)
  --help                     Show help
```

### Common Patterns

```bash
# Fully autonomous (research + implement)
bash spiral.sh 20 --gate proceed

# Research-only (discover stories, skip implementation)
bash spiral.sh 1 --gate skip

# Implementation-only (skip web research)
bash spiral.sh 5 --gate proceed --skip-research

# Parallel with 3 workers
bash spiral.sh 5 --gate proceed --ralph-workers 3

# Custom config file
bash spiral.sh 10 --gate proceed --config /path/to/my-config.sh
```

## Exit Codes

CI pipelines and the `SPIRAL_ON_COMPLETE` hook can branch on `$?` using these values:

| Code | Constant | Meaning |
|------|----------|---------|
| 0 | *(success)* | All stories passed / operation completed OK |
| 2 | `ERR_BAD_USAGE` | Wrong CLI arguments or unknown flag |
| 3 | `ERR_CONFIG` | Missing or invalid `spiral.config.sh` value |
| 4 | `ERR_MISSING_DEP` | Required tool not found (`jq`, `ralph.sh`, …) |
| 5 | `ERR_PRD_NOT_FOUND` | `prd.json` file not found |
| 6 | `ERR_PRD_CORRUPT` | `prd.json` corrupt and unrecoverable |
| 7 | `ERR_SCHEMA_VERSION` | `prd.json` schemaVersion too new for SPIRAL |
| 8 | `ERR_COST_CEILING` | Spend cap (`SPIRAL_COST_CEILING`) reached |
| 9 | `ERR_ZERO_PROGRESS` | Zero-progress stall — all pending blocked |
| 10 | `ERR_REPLAY_FAILED` | `--replay` mode: story implementation failed |
| 11 | `ERR_STORY_NOT_FOUND` | Story ID passed to `--replay` not in `prd.json` |
| 12 | `ERR_ROLLBACK_FAILED` | `--rollback` mode: git revert or guard failed |
| 13 | `ERR_MAX_ITERS` | Max spiral iterations reached; stories remain |
| 14 | `ERR_API_DOWN` | Claude API unreachable at startup probe |
| 130 | *(signal)* | Interrupted by SIGINT (Ctrl-C) — shell standard |

## Configuration Reference

Place `spiral.config.sh` in your project root. All variables have defaults — only set what you need to override.

| Variable | Purpose | Default |
|----------|---------|---------|
| `SPIRAL_PYTHON` | Python interpreter | `python3` |
| `SPIRAL_RALPH` | Path to ralph.sh | `$SPIRAL_HOME/ralph/ralph.sh` (bundled) |
| `SPIRAL_RESEARCH_PROMPT` | Research prompt template | bundled generic |
| `SPIRAL_GEMINI_PROMPT` | Gemini pre-research prompt | _(skip Gemini)_ |
| `SPIRAL_GEMINI_ANNOTATE_PROMPT` | Gemini filesTouch prompt | _(skip annotation)_ |
| `SPIRAL_FIRECRAWL_ENABLED` | Use Firecrawl MCP for Phase R scraping | `0` (disabled) |
| `SPIRAL_VALIDATE_CMD` | Test suite command | `$SPIRAL_PYTHON tests/run_tests.py --report-dir test-reports` |
| `SPIRAL_REPORTS_DIR` | Test reports directory | `test-reports` |
| `SPIRAL_STORY_PREFIX` | Story ID prefix | `US` |
| `SPIRAL_PATCH_DIRS` | Dirs for git diff patches (parallel) | _(all files)_ |
| `SPIRAL_DEPLOY_CMD` | Post-merge deploy command | _(skip)_ |
| `SPIRAL_TERMINAL` | Terminal emulator for `--monitor` | _(auto-detect)_ |
| `SPIRAL_STREAM_FMT` | Node.js stream formatter | `$SPIRAL_HOME/ralph/stream-formatter.mjs` (bundled) |
| `SPIRAL_MODEL_ROUTING` | Claude model selection strategy | `auto` (by story complexity) |
| `SPIRAL_RESEARCH_MODEL` | Claude model for Phase R | `sonnet` |
| `SPIRAL_GITNEXUS_REPO` | GitNexus repo name for semantic file hints | _(skip)_ |

See [`templates/spiral.config.example.sh`](templates/spiral.config.example.sh) for full documentation with examples.

## prd.json Format

SPIRAL expects a `prd.json` in the project root:

```json
{
  "productName": "My App",
  "branchName": "main",
  "overview": "What we are building",
  "goals": ["Goal 1", "Goal 2"],
  "userStories": [
    {
      "id": "US-001",
      "title": "Implement user login",
      "priority": "high",
      "description": "Users should be able to log in with email and password",
      "acceptanceCriteria": ["Login form validates email format", "..."],
      "technicalNotes": ["Use bcrypt for password hashing"],
      "dependencies": [],
      "estimatedComplexity": "medium",
      "passes": false
    }
  ]
}
```

### Key Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (`{SPIRAL_STORY_PREFIX}-NNN`) |
| `title` | string | Short descriptive name |
| `priority` | string | `critical` \| `high` \| `medium` \| `low` |
| `passes` | boolean | `true` when implemented and verified |
| `dependencies` | string[] | Story IDs that must complete first |
| `filesTouch` | string[] | Optional hint for parallel worker partitioning |
| `acceptanceCriteria` | string[] | Verifiable conditions for "done" |
| `technicalNotes` | string[] | Implementation hints |

Use `templates/prd.example.json` as a starter.

## Bundled Components

### Ralph (Implementation Engine)

Located at `ralph/`. Ralph is the inner loop that implements one story at a time:

1. Reads `prd.json` — finds next `passes: false` story (sorted by priority)
2. Checks dependency chain (skips blocked stories)
3. Spawns a fresh Claude/Codex/Qwen instance with the project prompt
4. AI implements the story, runs quality checks, marks `passes: true`
5. Ralph verifies quality gates (TypeScript, lint — configurable)
6. On success: commits. On failure: retries (max 3, then skips)

Run Ralph standalone: `bash ralph/ralph.sh [max_iters] [--tool auto] [--prd prd.json]`

### Skills

Located at `ralph/skills/`. Two Claude Code skills are bundled:

| Skill | Trigger | What It Does |
|-------|---------|--------------|
| `/spiral-init` | "init spiral", "setup spiral" | Setup wizard: scans codebase, asks questions, generates config files |
| `/ralph` | "run ralph", "implement prd" | Runs the Ralph autonomous loop (auto-redirects to `/spiral-init` if no `prd.json`) |
| `/prd` | "create a prd", "plan this feature" | Generates a structured PRD with clarifying questions |

To install skills into your Claude Code environment, symlink or copy:

```bash
# Symlink (recommended)
ln -s ~/.ai/Skills/spiral/ralph/skills/ralph.md ~/.claude/skills/ralph/SKILL.md
ln -s ~/.ai/Skills/spiral/ralph/skills/prd.md ~/.claude/skills/prd/SKILL.md

# Or copy
mkdir -p ~/.claude/skills/ralph ~/.claude/skills/prd
cp ~/.ai/Skills/spiral/ralph/skills/ralph.md ~/.claude/skills/ralph/SKILL.md
cp ~/.ai/Skills/spiral/ralph/skills/prd.md ~/.claude/skills/prd/SKILL.md
```

## Crash Recovery

If SPIRAL is interrupted mid-iteration, re-running resumes from the last completed phase via `.spiral/_checkpoint.json`. No work is lost.

```bash
# Just re-run — it picks up where it left off
bash ~/.ai/Skills/spiral/spiral.sh 20 --gate proceed
```

## Runtime Scratch Directory

SPIRAL writes all temporary files to `.spiral/` in the project root:

```
.spiral/
├── _checkpoint.json           # Crash recovery state
├── _last_run.log              # Full console output
├── _research_output.json      # Phase R output
├── _test_stories_output.json  # Phase T output
├── _research_overflow.json    # Unused candidates for next iteration
└── workers/                   # Parallel worker prd files + logs
```

Add `.spiral/` to your `.gitignore`.

## Repo Structure

```
spiral/
├── spiral.sh                        # Main entry point (7-phase loop)
├── setup.sh                         # Fully automatic bootstrap
├── ralph/                           # Implementation engine (bundled)
│   ├── ralph.sh                     # Inner loop: one story at a time
│   ├── CLAUDE.md                    # Default per-iteration prompt
│   ├── stream-formatter.mjs         # Colorized output formatter
│   ├── jq.exe                       # Windows jq binary (bundled)
│   └── skills/                      # Claude Code skills
│       ├── spiral-init.md           # /spiral-init setup wizard
│       ├── ralph.md                 # /ralph skill
│       └── prd.md                   # /prd skill
├── lib/
│   ├── phases/                      # One shell module per phase
│   │   ├── phase_0_clarify.sh       # Phase 0: startup clarification (NEW)
│   │   ├── phase_r_research.sh      # Phase R: web research
│   │   ├── phase_t_test_synth.sh    # Phase T: test failure synthesis
│   │   ├── phase_s_story_validate.sh# Phase S: story validation (NEW)
│   │   ├── phase_m_merge.sh         # Phase M: merge into prd.json
│   │   ├── phase_i_implement.sh     # Phase I: implementation orchestrator
│   │   ├── phase_v_validate.sh      # Phase V: code validation
│   │   └── phase_c_check_done.sh    # Phase C: completion check
│   ├── impl/                        # Phase I sub-stage modules
│   │   ├── decompose.sh             # Split oversized stories
│   │   ├── retry.sh                 # Retry counter + model escalation
│   │   └── commit_revert.sh         # Merge on pass, drop branch on fail
│   ├── check_done.py                # Phase C: completion evaluator
│   ├── merge_stories.py             # Phase M: dedup + prd.json patcher
│   ├── decompose_story.py           # Phase I/decompose: story splitter
│   ├── route_stories.py             # Phase I: model routing per story
│   ├── check_dag.py                 # Phase I: dependency cycle detector
│   ├── synthesize_tests.py          # Phase T: test failure → stories
│   ├── merge_worker_results.py      # Parallel: merge worker outputs
│   ├── partition_prd.py             # Parallel: wave-based partitioning
│   ├── populate_hints.py            # Parallel: filesTouch from git history
│   └── run_parallel_ralph.sh        # Parallel: multi-worker orchestrator
├── docs/
│   └── ARCHITECTURE.md              # Full phase reference + module map
├── templates/
│   ├── spiral.config.example.sh     # Config template (all variables documented)
│   ├── research_prompt.example.md   # Generic research prompt
│   └── prd.example.json             # Starter PRD for testing
├── README.md
├── LICENSE
└── .gitignore
```

## Firecrawl MCP (Optional)

Firecrawl is an optional Phase R enhancement. It replaces `WebFetch` with a dedicated scraper that returns **clean LLM-optimized markdown**, handles JavaScript-rendered pages, and offloads heavy scraping from Claude — saving significant tokens on research iterations.

**Why it matters for research-heavy projects:**
- Government portals and compliance documentation sites are often HTML-heavy or JS-rendered
- `WebFetch` makes Claude parse raw HTML, wasting many tokens before getting to the actual content
- Firecrawl strips all that noise and delivers structured markdown — Claude synthesizes faster and more accurately

**Setup (5 minutes):**

1. Get a free API key at [firecrawl.dev](https://www.firecrawl.dev) — 500 free credits/month

2. Add to your Claude Code MCP config (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "firecrawl": {
      "command": "npx",
      "args": ["-y", "firecrawl-mcp"],
      "env": {
        "FIRECRAWL_API_KEY": "fc-your-api-key-here"
      }
    }
  }
}
```

3. Enable in your project's `spiral.config.sh`:

```bash
SPIRAL_FIRECRAWL_ENABLED=1
```

That's it. When enabled, Phase R uses `mcp__firecrawl__scrape` instead of `WebFetch`. When disabled (default), SPIRAL uses the built-in `WebFetch` — no Firecrawl account required.

**Available Firecrawl tools (used automatically when enabled):**

| Tool | What it does |
|------|-------------|
| `mcp__firecrawl__scrape` | Scrape a URL → clean markdown |
| `mcp__firecrawl__search` | Search with Firecrawl's index |
| `mcp__firecrawl__crawl` | Crawl an entire site section |

## GitNexus (Optional)

GitNexus is an optional parallel-mode enhancement for `populate_hints.py`. It uses a local **code knowledge graph** (KuzuDB) to fill `filesTouch` hints for stories that have no git commit history — typically new story areas added after the baseline was established.

**Why it matters for long-running projects:**
- `populate_hints.py` builds its keyword→file mapping from completed story commits. Stories added in later SPIRAL iterations (e.g., US-200+ on a project that started at US-001) have no commits yet, so keyword matching returns 0 files.
- Without hints, `partition_prd.py` assigns those stories to parallel workers by load balancing alone — which means stories that actually share imports may end up in different workers, producing `.rej` merge conflicts.
- GitNexus understands semantic relationships in the current codebase, not just commit history. It fills the gap for zero-history stories.

**Performance:**
- Runs once per SPIRAL iteration, pre-partition (before any Claude agent is spawned)
- ~1s per story with empty hints; ~1-2 min total for a typical batch
- Results are cached in `prd.json` (`filesTouch` persists, never re-queried)
- Zero overhead inside agent sessions — no hook, no Grep/Glob interception

**Setup:**

1. Install gitnexus: `npm i -g gitnexus`

2. Index your repo (one-time, re-run after large changes):

```bash
cd /path/to/your/repo
gitnexus analyze
```

3. Enable in your project's `spiral.config.sh`:

```bash
SPIRAL_GITNEXUS_REPO="your-repo-name"  # from: gitnexus list
```

When `SPIRAL_GITNEXUS_REPO` is empty (default), the feature is completely disabled — zero overhead, keyword matching only.

## Browser Testing (Optional)

Four complementary tools cover the full spectrum from in-agent visual verification to shell-driven Phase V E2E assertions — useful whenever stories involve web UI features, form behaviour, or end-to-end flows.

| Tool | Role | When used |
|------|------|-----------|
| **Chrome DevTools MCP** | Gives Claude direct browser control via MCP tools (`navigate`, `click`, `fill`, `screenshot`, `evaluate_script`, …) | Inside Ralph's agent sessions — Claude opens the running app, interacts with it, and visually verifies results before marking `passes: true` |
| **agent-browser skill** | High-level CLI (`agent-browser open/snapshot/click/fill/close`) invoked from Bash — wraps browser automation as simple shell commands | In Claude Code sessions running SPIRAL itself, for manual or scripted validation steps |
| **Pinchtab** | Persistent HTTP browser server — text-mode, token-efficient (~800 tokens vs ~10 k for a screenshot), parallel-safe with per-worker isolation | Phase V shell assertions: `pinchtab nav $URL && pinchtab text \| grep -q "expected"` after pytest passes |
| **Lightpanda** | Ultra-fast Zig-based headless browser — drop-in Chrome replacement, ~10× lower memory than Chromium | Low-overhead browser back-end for Pinchtab or any `--browser lightpanda` automation; ideal on CI or memory-constrained workers |

**Why they fit together:**
- **Chrome DevTools MCP** is the best choice inside a Ralph agent turn — Claude gets full MCP tool access, can screenshot, click, and evaluate JS without leaving the implementation loop.
- **agent-browser** handles shell-level automation in SPIRAL's own hooks and validation steps, no Playwright/Selenium install required.
- **Pinchtab** is the right tool for Phase V shell assertions — it's fast, scriptable, produces grep-able text output, and each parallel Spiral worker can request an isolated browser tab.
- **Lightpanda** pairs with Pinchtab (or any automation that accepts a `--browser` flag) as a lightweight back-end: boots in milliseconds, uses far less RAM than Chrome, and is fully headless by design.

### Setup

**1. Chrome DevTools MCP** (`npm i -g chrome-devtools-mcp` by Google LLC):

```bash
npm i -g chrome-devtools-mcp
```

Add to your Claude Code MCP config (`~/.claude/settings.json` or `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "chrome-devtools-mcp",
      "args": []
    }
  }
}
```

Or use npx (no global install needed):

```json
{
  "mcpServers": {
    "chrome-devtools": {
      "command": "npx",
      "args": ["-y", "chrome-devtools-mcp"]
    }
  }
}
```

**2. agent-browser skill** — install into Claude Code's skills directory:

```bash
# From the SPIRAL skills bundle or your own skills repo
ln -s /path/to/agent-browser ~/.claude/skills/agent-browser

# Quick-start commands (inside a Claude Code session or Bash)
agent-browser open http://localhost:8080
agent-browser snapshot -i           # Lists interactive elements with refs
agent-browser click @e1
agent-browser fill @e2 "value"
agent-browser screenshot
agent-browser close
```

**3. Pinchtab** — shell-driven Phase V browser assertions:

```bash
npm i -g pinchtab

# Start the server (keep running in background)
pinchtab serve --port 9867

# Then in spiral.config.sh:
# SPIRAL_PINCHTAB_URL="http://localhost:9867"
# SPIRAL_DEV_URL="http://localhost:3000"
```

Usage in Phase V shell assertions (or `SPIRAL_PINCHTAB_E2E_CMD`):

```bash
pinchtab nav http://localhost:3000
pinchtab text | grep -q "Welcome"   # pass/fail assertion
```

Pinchtab is parallel-safe: each Spiral worker gets an isolated browser tab. Set `SPIRAL_PINCHTAB_URL` in `spiral.config.sh` to activate — Phase V runs these steps automatically after pytest/vitest.

**4. Lightpanda** — fast headless browser back-end:

Download from [lightpanda.io](https://lightpanda.io) or:

```bash
# macOS / Linux
curl -fsSL https://install.lightpanda.io | sh

# Or download the binary from GitHub releases:
# https://github.com/lightpanda-io/browser/releases
```

Lightpanda exposes a Chrome DevTools Protocol (CDP) endpoint — any tool that works against Chrome headless also works against Lightpanda. To use it as Pinchtab's back-end:

```bash
# Start Lightpanda CDP server
lightpanda serve --host 127.0.0.1 --port 9222

# Then start Pinchtab pointed at it
pinchtab serve --cdp-url ws://127.0.0.1:9222 --port 9867
```

On memory-constrained CI runners or when running many parallel Spiral workers, Lightpanda's ~10× lower RAM footprint versus Chromium makes a meaningful difference.

None of these tools are required — SPIRAL works without them. They activate automatically when configured: Chrome DevTools MCP via `mcp__chrome-devtools__*` tools detected in the environment; Pinchtab via `SPIRAL_PINCHTAB_URL` in `spiral.config.sh`.

## Notifications (Optional)

**Peon Ping** is a Claude Code skill that plays an audio chime when Ralph finishes a story — useful for long Spiral runs where you want to step away and be alerted when something completes rather than watching the terminal.

Install into Claude Code's skills directory:

```bash
ln -s /path/to/peon-ping ~/.claude/skills/peon-ping
```

Once installed, Peon Ping activates automatically at the end of each Ralph iteration. Configure volume, voice packs, and notification categories in your Claude Code settings. See the [peon-ping skill docs](https://github.com/wenjyue84/peon-ping) for full options.

## License

MIT

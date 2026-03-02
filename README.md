# SPIRAL

**Self-iterating PRD Research & Implementation Autonomous Loop**

SPIRAL autonomously discovers requirements, generates user stories, and implements them. Given a `prd.json`, it loops through research, test synthesis, story merging, and implementation until all stories pass.

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

Each SPIRAL iteration runs 7 phases:

```
                    ┌──────────────────────────────────┐
                    │        SPIRAL Iteration N         │
                    └──────────────────────────────────┘
                                    │
                    ┌───────────────▼───────────────────┐
                    │  R) RESEARCH                       │
                    │  Gemini web search → Claude agent   │
                    │  → story candidates JSON            │
                    └───────────────┬───────────────────┘
                                    │
                    ┌───────────────▼───────────────────┐
                    │  T) TEST SYNTHESIS                  │
                    │  Scan test report failures           │
                    │  → regression story candidates       │
                    └───────────────┬───────────────────┘
                                    │
                    ┌───────────────▼───────────────────┐
                    │  M) MERGE                           │
                    │  Deduplicate + patch prd.json        │
                    │  (overflow → next iteration)         │
                    └───────────────┬───────────────────┘
                                    │
                    ┌───────────────▼───────────────────┐
                    │  G) GATE                            │
                    │  Human checkpoint (or --gate auto)   │
                    │  proceed / skip / quit               │
                    └───────────────┬───────────────────┘
                                    │
                    ┌───────────────▼───────────────────┐
                    │  I) IMPLEMENT                       │
                    │  Ralph loop (sequential or parallel) │
                    │  Fresh Claude per story              │
                    └───────────────┬───────────────────┘
                                    │
                    ┌───────────────▼───────────────────┐
                    │  V) VALIDATE                        │
                    │  Run project test suite              │
                    └───────────────┬───────────────────┘
                                    │
                    ┌───────────────▼───────────────────┐
                    │  C) CHECK DONE                      │
                    │  All stories pass? → EXIT            │
                    │  Otherwise → loop back to R          │
                    └──────────────────────────────────┘
```

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
| `/ralph` | "run ralph", "implement prd" | Runs the Ralph autonomous loop |
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
│       ├── ralph.md                 # /ralph skill
│       └── prd.md                   # /prd skill
├── lib/                             # Python + bash helpers
│   ├── check_done.py                # Phase C: completion check
│   ├── merge_stories.py             # Phase M: deduplicate + patch
│   ├── merge_worker_results.py      # Parallel: merge worker outputs
│   ├── partition_prd.py             # Parallel: wave-based partitioning
│   ├── populate_hints.py            # Parallel: filesTouch from git history
│   ├── run_parallel_ralph.sh        # Parallel: multi-worker orchestrator
│   └── synthesize_tests.py          # Phase T: test failure → stories
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

## License

MIT

---
name: spiral-init
description: >
  Setup wizard for SPIRAL in a new project. Scans the codebase,
  asks the user questions, and generates spiral.config.sh + prd.json.
  Use when the user says "init spiral", "setup spiral", "spiral init",
  "spiral setup", "configure spiral", or when /ralph detects no prd.json.
---

# SPIRAL Setup Wizard

You are running the SPIRAL setup wizard for a new project. Your job is to scan the codebase, ask the user a series of questions, and generate the configuration files needed to run SPIRAL.

## Step 1: Codebase Scan

Run these scans in parallel to detect the project's tech stack. Use dedicated tools (Glob, Grep, Read) — not bash grep/find.

### 1a. Detect Languages & Package Managers

Check for these files at the project root (use Glob):
- `package.json` → Node.js/JavaScript/TypeScript
- `Cargo.toml` → Rust
- `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile` → Python
- `go.mod` → Go
- `pom.xml`, `build.gradle` → Java/Kotlin
- `*.csproj`, `*.sln` → C#/.NET
- `Gemfile` → Ruby
- `composer.json` → PHP

If `package.json` exists, read it to detect:
- Framework (react, next, vue, svelte, express, fastify, hono, etc.)
- Test runner (vitest, jest, mocha, playwright, cypress)
- Build tool (vite, webpack, tsc, esbuild, turbo)
- Scripts (dev, test, build, lint, check)

If `pyproject.toml` exists, read it for framework/test info.
If `Cargo.toml` exists, read it for crate info.

### 1b. Detect Project Structure

Use Glob to check for:
- `src/` directory structure
- `tests/` or `__tests__/` or `test/` directories
- `CLAUDE.md` (existing project instructions)
- `.github/workflows/` (CI/CD)
- `docker-compose.yml` or `Dockerfile`
- `tsconfig.json` (TypeScript config)
- `.env` or `.env.example` (environment variables)
- `drizzle.config.*` or `prisma/schema.prisma` (database ORM)
- Existing `prd.json` or `spiral.config.sh` (already initialized)

#### Auto-detect story prefix from existing prd.json

If `prd.json` exists with stories, detect the dominant prefix:

```bash
# Extract all story ID prefixes from prd.json
DETECTED_PREFIX=$(python3 -c "
import json, re, sys
from collections import Counter
try:
    with open('prd.json') as f:
        stories = json.load(f).get('userStories', [])
    prefixes = [re.match(r'^([A-Z]+)-\d+$', s.get('id','')) for s in stories]
    prefixes = [m.group(1) for m in prefixes if m]
    if len(prefixes) >= 2:
        top = Counter(prefixes).most_common(1)[0]
        if top[1] >= 2:
            print(top[0])
except Exception:
    pass
" 2>/dev/null)
```

- If `DETECTED_PREFIX` is non-empty, use it as the default for Group 6
- If empty (no stories, no consistent prefix, or prd.json missing), default remains `US`

### 1c. Estimate Project Size

Use Glob with common source patterns to estimate:
- `**/*.{ts,tsx,js,jsx}` → JS/TS file count
- `**/*.py` → Python file count
- `**/*.rs` → Rust file count
- (whichever language was detected)

### 1d. Check Git Status

```bash
rtk git log --oneline -5
rtk git branch --list
```

## Step 2: Present Scan Results

Show the user a summary of what you found:

```
SPIRAL Setup Wizard
===================

Codebase scan complete:

  Language:    TypeScript
  Framework:   React + Express
  Test runner: Vitest
  Build tool:  Vite
  ORM:         Drizzle (PostgreSQL)
  Files:       ~142 source files
  CI/CD:       GitHub Actions
  Git:         12 commits on main

  Detected test command:  npm test
  Detected dev command:   npm run dev
```

Adjust the fields based on what was actually detected. Skip fields that don't apply.

## Step 3: Ask Questions

Ask the user these questions **one group at a time** (not all at once). Use the scan results to pre-fill sensible defaults.

### Group 1: Project Identity

> **What is the name of this project?**
> (detected: `{name from package.json or folder name}`)
>
> **Describe what this project does in 1-2 sentences:**

### Group 2: Goals & Scope

> **What are you trying to accomplish with SPIRAL?** Pick one or describe your own:
> 1. Build new features from scratch
> 2. Fix bugs and improve test coverage
> 3. Refactor/modernize existing code
> 4. Add missing tests for existing code
> 5. Something else (describe)
>
> **Any specific focus area for the first iteration?** (e.g., "authentication", "performance", "error handling")
> Leave blank for no focus.

### Group 3: Testing & Validation

> **What command runs your test suite?**
> (detected: `{test script from package.json}`)
>
> **Where are test reports written?** (default: `test-reports`)
>
> If no test runner was detected, inform the user:
> "No test runner detected. SPIRAL works best with a test suite. You can add one later or SPIRAL will skip the Test Synthesis phase."

#### Validate Command Dry-Run

After the user provides `SPIRAL_VALIDATE_CMD` (non-empty input), immediately perform a dry-run before writing it to config:

```bash
timeout 30 bash -c "$SPIRAL_VALIDATE_CMD"
DRY_RUN_EXIT=$?
```

Handle each outcome:

**Empty input:** Skip the dry-run entirely. Use the detected project default as-is.

**Exit 0 (success):**
```
[wizard] Validate command verified ✓ writing to config
```
Proceed immediately to the next question.

**Exit 127 (command not found):**
```
[wizard] Command not found: {cmd}
         → Hint: install with {suggest package manager command based on detected stack, e.g. "npm install -D vitest" or "pip install pytest"}

Command returned exit 127 → use anyway? (y/N)
```
Wait for user input:
- `y` — accept the command as-is and continue
- `N` or Enter (default) — re-prompt: "What command runs your test suite?"

**Non-zero exit or timeout (any other failure):**
```
Command returned exit {N} → use anyway? (y/N)
```
Wait for user input:
- `y` — accept the command as-is and continue
- `N` or Enter (default) — re-prompt: "What command runs your test suite?"

Keep re-prompting until the user either provides a command that exits 0, accepts a failing command with `y`, or enters blank (skip dry-run).

### Group 4: Model & Token Strategy

> **Implementation model routing** — which Claude model strategy for implementing stories? (default: `auto`)
>
> - `auto` — smart routing: haiku→sonnet→opus by story complexity. Cheapest model that can handle each story; escalates on retry. Best for mixed workloads.
> - `haiku` — always use haiku (fastest, cheapest, ~80% cost saving vs sonnet — use for well-scoped, low-ambiguity stories)
> - `sonnet` — always use sonnet (balanced cost/quality — solid default for most projects)
> - `opus` — always use opus (highest quality, most expensive — use when stories are complex or high-stakes)
>
> **Research model** — which model synthesizes Phase R research? (default: `sonnet`)
>
> - `sonnet` — recommended default: better synthesis depth, connects broader context
> - `haiku` — faster and cheaper, but may miss nuanced connections in complex codebases
>
> **Enable `--tool auto`** — route simple stories to Qwen/Codex first before using Claude? (default: `no`)
>
> - `yes` — 60-80% cost saving on trivial stories (CRUD, boilerplate, simple refactors). SPIRAL tries the cheapest tool first and falls back to Claude on failure.
> - `no` — use Claude for all stories. More reliable, less configuration.

### Group 5: Research Phase Configuration

> **Use Gemini for web pre-research?** (free, saves Claude tokens by pre-fetching search results)
>
> Gemini CLI performs web searches and summarizes results before Claude's research phase,
> saving significant Claude tokens on context gathering.
>
> - `yes` — enable Gemini pre-research (recommended if Gemini CLI is installed)
> - `no` — skip Gemini, Claude handles all research directly
>
> (Check if `gemini` CLI is available via `command -v gemini`. If not found, warn:
> "Gemini CLI not detected — install it first or select 'no'." Default: `yes` if available, `no` otherwise)
>
> **Focus prompt for Gemini/Claude research?**
>
> An optional prompt that guides what the research phase looks for — e.g.,
> "focus on authentication patterns" or "prioritize performance optimization techniques".
> Leave blank for general research.
>
> (If provided, writes to `SPIRAL_GEMINI_PROMPT` in spiral.config.sh)
>
> **Use Firecrawl MCP for URL scraping?** (cleaner markdown, handles JS-rendered pages)
>
> Firecrawl converts web pages to clean markdown — much better than raw HTML scraping,
> especially for JS-rendered pages (SPAs, docs sites). Useful when research phase fetches URLs.
>
> - `yes` — enable Firecrawl MCP. Writes `SPIRAL_FIRECRAWL_ENABLED=1` to config.
>   Show setup instructions: "Run `npx firecrawl` or see https://docs.firecrawl.dev/mcp for MCP server setup."
> - `no` — skip Firecrawl, use default URL fetching
>
> (Default: `no`)
>
> **Skip research when pending stories exceed N?** (avoids flooding prd.json)
>
> When too many stories are already pending, the research phase can be skipped to avoid
> generating even more work. This keeps the backlog manageable.
>
> (Default: `50`. Set to `0` for unlimited.)

### Group 6: SPIRAL Preferences

> **Story ID prefix** — short identifier for user stories
> (default: `{DETECTED_PREFIX if non-empty, otherwise 'US'}` — auto-detected from existing story IDs)
> Examples: `US` (user story), `BUG` (bug fixes), `FT` (features)
>
> If `DETECTED_PREFIX` was found, pre-fill the prompt with it:
> `Story ID prefix [detected: {DETECTED_PREFIX}]:`
> Otherwise show:
> `Story ID prefix [default: US]:`
> The user may accept the default by pressing Enter or type a new prefix.

### Group 7: Optional Features (quick yes/no)

> **Enable project constitution** for governance/quality standards? (y/n, default: y)
>
> A constitution defines the non-negotiable rules that every SPIRAL iteration must follow —
> coding standards, architecture boundaries, quality bars. SPIRAL agents read it before
> implementing any story.

If the user says **yes** to the constitution (default), proceed to **Step 3b: Generate Constitution**.
If the user says **no**, skip to Step 4.

(Note: Groups renumbered — Research Phase Configuration added as Group 5, pushing Preferences to Group 6 and Optional Features to Group 7.)

### Group 8: Browser Testing (Optional)

Detect whether Chrome DevTools MCP and the agent-browser skill are available:

```bash
# Check Chrome DevTools MCP
npm list -g chrome-devtools-mcp 2>/dev/null | grep -q chrome-devtools-mcp && echo "found" || echo "not found"

# Check agent-browser skill
ls ~/.claude/skills/agent-browser.md 2>/dev/null && echo "found" || echo "not found"
```

**If Chrome DevTools MCP is detected:**
> **Chrome DevTools MCP is installed** — Claude can take screenshots and interact with your running app during Phase V validation.
>
> Enable browser testing in SPIRAL? (y/n, default: y)
> This writes `SPIRAL_BROWSER_TESTING=1` to spiral.config.sh, enabling Phase V visual checks.

**If Chrome DevTools MCP is NOT detected:**
> **Chrome DevTools MCP not found** (optional). To enable visual validation during Phase V:
>
>     npm i -g chrome-devtools-mcp
>
> Skip for now? (y/n, default: y — you can enable it later in spiral.config.sh)

**If agent-browser skill is detected:**
> **agent-browser skill is installed** — Claude can use the browser agent for automated UI testing during Phase V.
> Included when `SPIRAL_BROWSER_TESTING=1` is set.

**If agent-browser skill is NOT detected:**
> **agent-browser skill not found** (optional). Install it to enable autonomous browser interaction.
> Skip for now — this is informational only.

**Dev server URL for visual screenshots:**

> **Dev server URL for visual screenshots?** (e.g. `http://localhost:3000`)
>
> When set, Phase V will take a screenshot of your running app after each validation pass.
> Screenshots are saved to `.spiral/screenshots/` and shown in the metrics dashboard.
> Leave blank to disable.

If the user provides a URL, write `SPIRAL_DEV_URL="{url}"` to spiral.config.sh.

If the user opts in to browser testing (either tool detected + confirmed, or user requests it manually), write `SPIRAL_BROWSER_TESTING=1` to spiral.config.sh.

Do **not** block setup if tools are missing — this section is informational. The MCP config itself (claude settings.json) requires manual setup outside the wizard; show the snippet:

```json
// Add to ~/.claude/settings.json under "mcpServers":
"chrome-devtools": {
  "command": "chrome-devtools-mcp"
}
```

### Group 9: Advanced Options (Optional)

> **Advanced lifecycle tuning** — these settings are powerful but have sensible defaults. Skip any you're unsure about.
>
> **Max retries per failing story?** (default: `3`)
>
> After N consecutive failures, SPIRAL skips the story and marks it for decomposition
> into smaller sub-stories. Lower values iterate faster (fail-fast); higher values give
> the agent more chances to solve tricky stories.
>
> **GitNexus repo name for semantic file hints?** (default: empty — disabled)
>
> If GitNexus is installed, providing a repo name enables semantic file-level hints
> that improve parallel worker partitioning for new stories. SPIRAL will query GitNexus
> for file relevance when assigning work to workers.
>
> (Check if `gitnexus` CLI is available via `command -v gitnexus`. If not found, warn:
> "GitNexus CLI not detected — install it first or leave blank to disable." Default: empty)
>
> **Post-merge deploy command?** (default: empty — disabled)
>
> A shell command that runs after each successful story merge, e.g. `npm run build` or
> `make deploy-staging`. This turns SPIRAL into a CI-style loop: implement → validate → deploy → repeat.
> Leave blank to skip post-merge deployment.

### Step 3b: Generate Constitution

Based on the codebase scan results, **draft a constitution** and present it for the user to review. The constitution should be derived from what was actually detected — not generic boilerplate.

**How to derive the constitution from the scan:**

1. **From detected language/framework** → coding conventions
   - TypeScript detected + `tsconfig.json` strict mode → "All code must pass `tsc --noEmit` with zero errors"
   - React detected → "Components use functional style with hooks, no class components"
   - Python detected → "Follow PEP 8, use type hints on all public functions"

2. **From detected test runner** → quality bars
   - Vitest/Jest detected → "Every new feature must include unit tests"
   - Playwright/Cypress detected → "Critical user flows must have E2E coverage"
   - No test runner → "Tests are optional but acceptance criteria must be verifiable manually"

3. **From detected linting/formatting** → style rules
   - ESLint config detected → "All code must pass `npm run lint` with zero warnings"
   - Prettier detected → "Code must be formatted with Prettier before commit"
   - Biome detected → "Code must pass `biome check` before commit"

4. **From project structure** → architecture boundaries
   - `src/components/` detected → "UI components live in `src/components/`, one component per file"
   - `src/server/` + `src/client/` → "Server and client code are strictly separated"
   - Drizzle/Prisma detected → "Database schema changes require a migration file"

5. **From existing CLAUDE.md** → inherit existing rules
   - If the project already has a `CLAUDE.md`, extract any rules/conventions from it and include them

6. **From user's stated goals** → scope guardrails
   - "Build new features" → "New features must not break existing tests"
   - "Fix bugs" → "Bug fixes must include a regression test"
   - "Refactor" → "Refactoring must not change external behavior"

**Present the draft to the user:**

```
Project Constitution (draft)
=============================

These are the non-negotiable rules every SPIRAL iteration must follow.
Review and edit before confirming.

## Code Quality
- All code must pass `{detected lint command}` with zero errors
- All code must pass `{detected type check}` with zero errors
- {formatting rule from detected tool}

## Testing
- {testing rules based on detected test runner}
- New features must include tests for acceptance criteria
- Bug fixes must include a regression test

## Architecture
- {architecture rules derived from project structure}
- {ORM/database rules if applicable}

## Scope
- Each story must be completable in one Ralph iteration
- Changes must be focused — no drive-by refactoring
- {goal-specific guardrails}

---
Want to edit any of these? Or confirm to save.
```

**Let the user freely edit** — they can add, remove, or reword any rule. Only write the file after explicit confirmation.

## Step 4: Generate Initial Stories

Based on the user's answers in Group 2, generate 2-4 starter stories for `prd.json`. These should be:
- Concrete and actionable (not vague)
- Appropriate for the detected tech stack
- Small enough for one Ralph iteration each
- Using the user's chosen story prefix

Examples by goal:

**If "Build new features":** Ask what feature they want first, generate 2-3 stories for it.
**If "Fix bugs":** Ask about known issues, or generate stories like "Add error handling for X", "Fix Y edge case".
**If "Add tests":** Generate stories like "Add unit tests for {module}", "Add E2E test for {workflow}".
**If "Refactor":** Generate stories like "Extract {pattern} into reusable utility", "Migrate {old} to {new}".

Always ask the user to review and confirm the stories before writing.

## Step 5: Write Configuration Files

Once the user confirms, generate these files:

### 5a. `spiral.config.sh`

Write a clean config file with only the values the user specified (not all defaults). Include comments explaining each setting.

```bash
#!/bin/bash
# spiral.config.sh — SPIRAL configuration for {projectName}
# Generated by SPIRAL setup wizard

# Test command
SPIRAL_VALIDATE_CMD="{detected or user-specified test command}"

# Story ID prefix
SPIRAL_STORY_PREFIX="{user choice}"

# Model routing: auto routes haiku→sonnet→opus by story complexity
# Options: auto | haiku | sonnet | opus
SPIRAL_MODEL_ROUTING="{user choice, default: auto}"

# Research model: used in Phase R to synthesize context
# Options: sonnet | haiku  (sonnet recommended for better synthesis depth)
SPIRAL_RESEARCH_MODEL="{user choice, default: sonnet}"

# Tool auto: route trivial stories to Qwen/Codex first (60-80% cost saving)
# Set to 1 to enable, omit or set to 0 to disable
# SPIRAL_TOOL_AUTO=1

# --- Research Phase Configuration ---

# Gemini pre-research: free web search before Claude research phase
# Set to 1 to enable (saves Claude tokens by pre-fetching search results)
# SPIRAL_GEMINI_ENABLED=1

# Focus prompt for Gemini/Claude research (empty = general research)
# Guides what the research phase looks for, e.g. "authentication patterns"
# SPIRAL_GEMINI_PROMPT=""

# Firecrawl MCP: clean markdown scraping for JS-rendered pages
# Set to 1 to enable (requires Firecrawl MCP server setup)
# SPIRAL_FIRECRAWL_ENABLED=1

# Max pending stories before skipping research (avoids flooding prd.json)
# Set to 0 for unlimited
SPIRAL_MAX_PENDING={user choice, default: 50}

# --- Browser Testing (Phase V) ---

# Chrome DevTools MCP + agent-browser: visual screenshot validation during Phase V
# Set to 1 to enable (requires chrome-devtools-mcp installed: npm i -g chrome-devtools-mcp)
# SPIRAL_BROWSER_TESTING=1

# Dev server URL for visual screenshots (e.g. http://localhost:3000)
# When set, Phase V captures a screenshot after validation via Chrome DevTools MCP
# Screenshots saved to .spiral/screenshots/iter-N-TIMESTAMP.png
# SPIRAL_DEV_URL=""

# Focus theme (empty = all stories)
# SPIRAL_FOCUS=""

# --- Advanced Lifecycle Tuning ---

# Max retries per failing story before skip + decomposition
# Lower = faster iteration (fail-fast), higher = more persistent
SPIRAL_MAX_RETRIES={user choice, default: 3}

# GitNexus repo name for semantic file hints (improves worker partitioning)
# Leave empty to disable
# SPIRAL_GITNEXUS_REPO=""

# Post-merge deploy command (runs after each successful story merge)
# Enables CI-style loop: implement → validate → deploy → repeat
# SPIRAL_DEPLOY_CMD=""
```

Only include optional sections (Firecrawl, Spec-Kit, Gemini, etc.) if the user opted in.

If the user said **yes** to `--tool auto`, uncomment and set `SPIRAL_TOOL_AUTO=1`.

If the user said **yes** to Gemini pre-research, uncomment and set `SPIRAL_GEMINI_ENABLED=1`. If they provided a focus prompt, uncomment and set `SPIRAL_GEMINI_PROMPT="{user's prompt}"`.

If the user said **yes** to Firecrawl, uncomment and set `SPIRAL_FIRECRAWL_ENABLED=1`.

If the user opted in to browser testing (Group 8), uncomment and set `SPIRAL_BROWSER_TESTING=1`.

If the user enabled the constitution, add:
```bash
# Project constitution (non-negotiable quality standards)
SPIRAL_SPECKIT_CONSTITUTION=".specify/memory/constitution.md"
```

### 5b. Constitution (if enabled)

Create the directory and write the confirmed constitution:

```bash
# Create the directory structure
mkdir -p .specify/memory
```

Write the user-confirmed constitution to `.specify/memory/constitution.md`:

```markdown
# Project Constitution — {projectName}

> Generated by SPIRAL setup wizard. These rules are enforced on every iteration.
> Edit freely — SPIRAL reads this file before implementing any story.

{confirmed constitution content from Step 3b}
```

### 5c. `prd.json`

Write the PRD with the project info and confirmed starter stories:

```json
{
  "productName": "{projectName}",
  "branchName": "main",
  "overview": "{user's project description}",
  "goals": ["{goal 1}", "{goal 2}"],
  "userStories": [
    {
      "id": "{PREFIX}-001",
      "title": "...",
      "priority": "high",
      "description": "...",
      "acceptanceCriteria": ["..."],
      "technicalNotes": ["..."],
      "dependencies": [],
      "estimatedComplexity": "small",
      "passes": false
    }
  ]
}
```

### 5d. Update `.gitignore`

Check if `.gitignore` exists. If it does, check if `.spiral/` is already listed. If not, append:

```
# SPIRAL runtime files
.spiral/
```

If `.gitignore` doesn't exist, create one with `.spiral/` and common ignores for the detected language.

### 5e. Create `progress.txt` (starter)

```markdown
# Progress Log

## Codebase Patterns
- Language: {detected}
- Framework: {detected}
- Test runner: {detected}
- Key directories: {detected structure}

## Setup
- SPIRAL initialized on {today's date}
- Goal: {user's stated goal}
- Focus: {focus area or "none"}
```

## Step 6: Print Next Steps

After writing all files, show:

```
SPIRAL setup complete!

Files created:
  - spiral.config.sh                  (project configuration)
  - prd.json                          ({N} starter stories)
  - .specify/memory/constitution.md   (project constitution — if enabled)
  - progress.txt                      (learning accumulator)
  - .gitignore                        (updated with .spiral/)

Next steps:

  1. Review prd.json — edit stories or add more
  2. Review .specify/memory/constitution.md — add or refine rules
  3. Run SPIRAL:
     bash ~/.ai/Skills/spiral/spiral.sh 5 --gate proceed
  4. Or use Ralph directly for one story at a time:
     /ralph

Tip: Use /prd to generate more stories from a feature description.
```

If the constitution was not enabled, omit the constitution line from the file list and step 2.

## Important Rules

- **Never skip the scan** — always scan first, even if the user provides info upfront
- **Pre-fill defaults** from scan results — don't make the user repeat what you already know
- **Ask one group at a time** — don't overwhelm with all questions at once
- **Validate test command** — dry-run `SPIRAL_VALIDATE_CMD` via `timeout 30 bash -c "$cmd"` before writing to config; re-prompt on failure unless user explicitly accepts with `y`
- **Don't overwrite** — if `prd.json` or `spiral.config.sh` already exist, warn the user and ask before overwriting
- **Keep stories small** — starter stories should be achievable in one Ralph iteration
- **Use the detected tech stack** — generated stories should reference actual files/frameworks found in the scan

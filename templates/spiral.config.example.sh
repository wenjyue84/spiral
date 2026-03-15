#!/bin/bash
# spiral.config.sh — Project-specific SPIRAL configuration
#
# Place this file in your project root. SPIRAL sources it automatically.
# All variables have sensible defaults — only set what you need to override.

# ── Python interpreter ───────────────────────────────────────────────────────
# Path to Python 3.x binary. Used for all SPIRAL Python scripts.
# Default: python3
# SPIRAL_PYTHON="python3"
# SPIRAL_PYTHON="$PWD/.venv/bin/python"              # Linux/Mac venv
# SPIRAL_PYTHON="$PWD/.venv/Scripts/python.exe"       # Windows venv

# ── Ralph path ───────────────────────────────────────────────────────────────
# Path to ralph.sh implementation loop.
# Default: $SPIRAL_HOME/ralph/ralph.sh (bundled with spiral)
# SPIRAL_RALPH="$SPIRAL_HOME/ralph/ralph.sh"

# ── Research prompt ──────────────────────────────────────────────────────────
# Path to the research prompt template file. Use a project-specific prompt
# for domain-specific research (e.g., compliance, API docs).
# Placeholders: __SPIRAL_ITER__, __NEXT_ID_NUM__, __OUTPUT_PATH__,
#               __EXISTING_TITLES__, __PENDING_TITLES__, __STORY_PREFIX__
# Default: bundled generic template
# SPIRAL_RESEARCH_PROMPT="$PWD/scripts/spiral/research_prompt.md"

# ── Gemini web research (Phase R) ───────────────────────────────────────────
# If set and gemini CLI is available, this prompt runs Gemini 2.5 Pro with
# web search enabled BEFORE the Claude research agent. The output is
# prepended as context so Claude can skip URL browsing.
# Default: empty (skip Gemini pre-research)
# SPIRAL_GEMINI_PROMPT="Research the latest compliance requirements for 2025-2026..."

# ── Gemini filesTouch annotation (parallel mode) ────────────────────────────
# If set and gemini CLI is available, asks Gemini which files each story
# touches before partitioning. Use __STORY_TITLE__ placeholder.
# Default: empty (skip annotation)
# SPIRAL_GEMINI_ANNOTATE_PROMPT='Which Python files would implement this story? Return a JSON array only. Story: __STORY_TITLE__'

# ── Validation command (Phase V) ─────────────────────────────────────────────
# Command to run the project's test suite. SPIRAL evaluates this in the
# project root directory.
# Default: $SPIRAL_PYTHON tests/run_tests.py --report-dir test-reports
# SPIRAL_VALIDATE_CMD="npm test"
# SPIRAL_VALIDATE_CMD="pytest --tb=short"

# ── Phase A: AI Story Suggestions ────────────────────────────────────────────
# Phase A runs once per iteration before Phase R. It generates story candidates
# from two sub-sources, which both route through Phase S → M for validation
# and deduplication before entering prd.json:
#
#   Source 2 (ai-example): Phase 0-D numbered picks queued for next iteration +
#                           PRD gap analysis (empty epics, low-coverage goals).
#   Source 5 (test-story):  Auto-generated test implementation stories for each
#                           passing story (integration, e2e, security, performance,
#                           regression). Ralph writes the actual test code.
#
# Max AI-generated gap suggestions per iteration (gap analysis only, not queue).
# 0 = no gap analysis (queue picks from Phase 0-D still consumed).
# Default: 5
# SPIRAL_MAX_AI_SUGGEST=5

# Minimum story complexity to trigger Source 5 test story generation.
# Stories below this complexity get no auto-generated test stories.
# Choices: small, medium, large. Default: medium
# SPIRAL_TEST_STORY_MIN_COMPLEXITY=medium

# ── Phase V: Persistent Test Suites ───────────────────────────────────────────
# After each Phase I batch, passing stories are added to persistent test suites
# stored in .spiral/test-suites/. Suites accumulate across iterations and grow
# more complete over time. Results are saved per-iteration for trend analysis.
#
# Suite types run automatically in Phase V (if test entries exist):
#   smoke       — basic create/read/update/delete flows (every feature)
#   regression  — bug-fix and patch stories
#   security    — auth, tokens, permissions
#   performance — latency, cache, bulk operations
#
# Test entry "command" fields are populated by Ralph when implementing
# Source 5 (test-story) stories. Until Ralph writes the command, entries
# are tracked but skipped (marked "pending" in results).
#
# No additional config required — suites are auto-managed. To customize
# which suite types are populated, set this (comma-separated):
# SPIRAL_TEST_SUITE_TYPES="smoke,regression,security,performance"

# ── Per-phase timeouts (seconds) ──────────────────────────────────────────────
# Each LLM phase has a distinct configurable deadline. When exceeded, the call
# receives SIGTERM (then SIGKILL after 30s), the result is treated as a phase
# failure (increments retry count, does not hard-abort), and a phase_timeout
# event is logged to spiral_events.jsonl.
# Set any to 0 to disable (unlimited) for that phase.

# Phase R (research): wall-clock limit for Claude research agent.
# Default: 300
# SPIRAL_RESEARCH_TIMEOUT=300

# Phase I (implementation): wall-clock limit for ralph implementation agent.
# Default: 600
# SPIRAL_IMPL_TIMEOUT=600

# Phase V (validation): wall-clock limit for test suite execution.
# Slow integration test suites may need a higher value (e.g., 600 or 900).
# Default: 300
# SPIRAL_VALIDATE_TIMEOUT=300

# ── API Retry Jitter (prevents thundering herd) ───────────────────────────────
# When multiple parallel SPIRAL workers hit rate limits (429/529) simultaneously,
# retry delays are staggered with random jitter to avoid synchronized retries.
# Each worker's RANDOM seed is unique (based on PID), so delays vary per worker.
#
# SPIRAL_RETRY_JITTER_S — max random jitter in seconds added to exponential backoff
# Default: 5
# SPIRAL_RETRY_JITTER_S=5
#
# SPIRAL_RETRY_MAX_ATTEMPTS — max retry attempts before giving up
# Default: 3
# SPIRAL_RETRY_MAX_ATTEMPTS=3
#
# SPIRAL_RETRY_BASE_DELAY — initial backoff in seconds (scaled by attempt number)
# Default: 1
# SPIRAL_RETRY_BASE_DELAY=1

# ── Test reports directory ───────────────────────────────────────────────────
# Where test reports are written (relative to project root).
# Must contain timestamped subdirs with report.json inside.
# Default: test-reports
# SPIRAL_REPORTS_DIR="test-reports"

# ── Story ID prefix ─────────────────────────────────────────────────────────
# Prefix for story IDs in prd.json. Default: US
# E.g., US-001, US-002, ...
# SPIRAL_STORY_PREFIX="US"

# ── Patch directories (parallel mode) ───────────────────────────────────────
# Space-separated directories to include in git diff patches when merging
# parallel worker results. If empty, diffs everything (full repo).
# Default: empty (all files)
# SPIRAL_PATCH_DIRS="src/ tests/"

# ── Deploy command (parallel mode) ──────────────────────────────────────────
# Command to deploy merged code after parallel workers complete.
# Runs in the project root. If empty, no deploy step.
# Default: empty (skip deploy)
# SPIRAL_DEPLOY_CMD='docker cp ./myapp/. container:/app/ && docker exec container clear-cache'

# ── Terminal emulator (parallel --monitor mode) ─────────────────────────────
# Path to terminal emulator for opening per-worker log windows.
# Default: auto-detect (wt.exe on Windows, mintty on MSYS2)
# SPIRAL_TERMINAL="/c/Users/me/AppData/Local/Microsoft/WindowsApps/wt.exe"

# ── Stream formatter (optional) ─────────────────────────────────────────────
# Path to Node.js stream formatter for Claude output. Used in Phase R.
# Default: $SPIRAL_HOME/ralph/stream-formatter.mjs (bundled with spiral)
# SPIRAL_STREAM_FMT="$SPIRAL_HOME/ralph/stream-formatter.mjs"

# ── Firecrawl MCP (Phase R — web scraping) ──────────────────────────────────
# When enabled, Phase R uses Firecrawl MCP instead of WebFetch for scraping URLs.
# Firecrawl returns clean LLM-optimized markdown, handles JS-rendered pages better,
# and offloads heavy scraping from Claude — saving significant tokens on research.
#
# Setup (one-time):
#   1. Get a free API key: https://firecrawl.dev (500 credits/month free)
#   2. Add to ~/.claude/settings.json (or your Claude Code MCP config):
#      {
#        "mcpServers": {
#          "firecrawl": {
#            "command": "npx",
#            "args": ["-y", "firecrawl-mcp"],
#            "env": { "FIRECRAWL_API_KEY": "fc-your-api-key-here" }
#          }
#        }
#      }
#   3. Set SPIRAL_FIRECRAWL_ENABLED=1 below
#
# Default: 0 (disabled — WebFetch used instead)
# SPIRAL_FIRECRAWL_ENABLED=0

# ── Research cache TTL (Phase R — URL response caching) ──────────────────
# Caches fetched URL responses in .spiral/research_cache/ to eliminate
# redundant HTTP requests across iterations. Cache key = md5(url).
# Each entry stores {url, fetched_ts, content} as JSON.
# Expired entries are automatically pruned at the start of Phase R.
# 0 = disabled (no caching). Default: 24 (hours)
# SPIRAL_RESEARCH_CACHE_TTL_HOURS=24

# ── Max research stories per iteration ────────────────────────────────────
# Caps how many NEW research candidates Phase R can inject per iteration.
# Applied BEFORE deduplication in Phase M merge. Prevents a single research
# pass from overwhelming the backlog even when SPIRAL_MAX_PENDING is set.
# 0 = unlimited (no cap). Recommended: 5-10 for controlled growth.
# Default: 0 (unlimited)
# SPIRAL_MAX_RESEARCH_STORIES=10

# ── Story count health threshold ────────────────────────────────────────────
# Warn when total story count in prd.json exceeds this value.
# Large PRDs degrade AI context quality and slow jq operations.
# When exceeded, spiral.sh prints an actionable message to run --archive-done.
# Set SPIRAL_MAX_STORIES_ABORT=1 to fail hard (instead of warn) when exceeded.
# Default: 100 (warn only)
# SPIRAL_MAX_STORIES=100
# SPIRAL_MAX_STORIES_ABORT=0

# ── Max pending stories ────────────────────────────────────────────────────
# Hard cap on total incomplete (pending) stories in prd.json.
# Phase M will stop adding new stories once pending count reaches this limit.
# Prevents the backlog from growing uncontrollably.
# 0 = unlimited (no cap). Recommended: 5-15 for focused projects.
# Default: 0 (unlimited)
# SPIRAL_MAX_PENDING=9

# ── Focus theme (iteration scoping) ─────────────────────────────────────────
# Scopes the entire SPIRAL iteration to a specific theme.
# Phase R only discovers focus-matching stories.
# Phase M hard-filters research stories; soft-prioritizes test stories.
# Phase I injects focus context for the implementation agent.
# CLI --focus flag overrides this setting.
# Examples: "performance", "security hardening", "accessibility", "error handling"
# Default: empty (no focus — all stories considered)
# SPIRAL_FOCUS="performance"

# ── Manual story exclusion ─────────────────────────────────────────────────
# Comma-separated story IDs to permanently skip without penalty (no retry
# increment). Use for stories that are blocked externally or descoped mid-run.
# These stories are excluded from Phase I selection, appear in --status output
# with a [MANUAL SKIP] indicator, and are treated as non-blocking by check_done.
# Default: empty (no manual exclusions)
# Example: SPIRAL_SKIP_STORY_IDS="US-042,US-099"
# SPIRAL_SKIP_STORY_IDS=""

# ── Model routing (Claude model selection) ──────────────────────────────────
# Controls which Claude model Ralph uses for implementation.
#   "auto"   — auto-classify per story: haiku (trivial), sonnet (default), opus (complex)
#   "haiku"  — always use haiku (fastest, cheapest)
#   "sonnet" — always use sonnet (balanced)
#   "opus"   — always use opus (most capable)
# Retry escalation always applies: failed attempts escalate one tier (haiku→sonnet→opus).
# CLI --model flag overrides this setting.
# Default: auto
# SPIRAL_MODEL_ROUTING="auto"

# ── Story time budget (per-story wall-clock limit) ──────────────────────────
# Maximum wall-clock seconds per story attempt in Ralph.
# Stories exceeding this budget are discarded and retried.
# Makes results more comparable across stories (inspired by autoresearch).
# 0 = disabled (default). Recommended: 300 (5 min) for fast iteration.
# SPIRAL_STORY_TIME_BUDGET=300

# ── Per-story token cost limits ─────────────────────────────────────────────
# SPIRAL_STORY_COST_WARN_USD: print a warning when a single story's cumulative
# LLM cost exceeds this amount. Execution continues.
# Default: $0.50
# SPIRAL_STORY_COST_WARN_USD=0.50

# SPIRAL_STORY_COST_HARD_USD: abandon the story (mark _failureReason:
# story_cost_ceiling) when cumulative cost exceeds this amount. The story is
# retried on the next iteration up to MAX_RETRIES times.
# Default: $2.00
# SPIRAL_STORY_COST_HARD_USD=2.00

# Model pricing constants ($/1M tokens) — override when using non-sonnet models.
# These are Anthropic 2025 Claude Sonnet defaults. Adjust for Haiku or Opus.
# SPIRAL_MODEL_INPUT_PRICE_PER_M=3.00    # claude-sonnet: $3.00 / 1M input
# SPIRAL_MODEL_OUTPUT_PRICE_PER_M=15.00  # claude-sonnet: $15.00 / 1M output

# ── Model fallback chain ──────────────────────────────────────────────────
# Colon-separated list of model identifiers to try when the primary model's
# circuit breaker is OPEN. Each model maintains its own circuit breaker state.
# If all models in the chain are OPEN, the story is deferred with
# _failureReason: all_models_unavailable.
# Only applies when EFFECTIVE_TOOL is "claude".
# Example: SPIRAL_MODEL_FALLBACK_CHAIN="sonnet:haiku:opus"
# Default: empty (no fallback — original circuit breaker behavior)
# SPIRAL_MODEL_FALLBACK_CHAIN=""

# ── Research model (Phase R) ────────────────────────────────────────────────
# Which Claude model to use for Phase R (web research agent).
# Research benefits from good reasoning — sonnet is recommended.
# CLI --model flag overrides this setting.
# Default: sonnet
# SPIRAL_RESEARCH_MODEL="sonnet"

# ── GitNexus knowledge graph (hints + partition quality) ──────────────────
# When set, populate_hints.py uses the GitNexus knowledge graph to find
# relevant files for stories that keyword matching fails on (no git history
# for new story areas). Runs once per SPIRAL iteration, before workers launch.
#
# Must match a repo name from: gitnexus list
# Requires: gitnexus CLI installed (npm i -g gitnexus) + prior `gitnexus analyze`
# Cost: ~1s per story with empty hints, ~1-2 min total; results cached in prd.json
# Default: empty (skip gitnexus — use keyword matching only)
# SPIRAL_GITNEXUS_REPO="my-repo"

# ── Spec-Kit Integration (optional) ──────────────────────────────────────
# When set, SPIRAL reads spec-kit's constitution and specs to enrich:
#   - Phase R: Research agent respects constitutional constraints
#   - Phase I: Ralph agents read constitution as quality governance
#
# Setup (one-time per target project):
#   1. Install: npm install -g @spec-kit/cli  (or create .specify/ manually)
#   2. In your project: specify   (follow the wizard)
#   3. Write your constitution: /speckit.constitution (in Claude Code)
#   4. Set variables below
#
# NOTE: @spec-kit/cli v0.3.1 has a packaging bug (workspace:* deps).
#       You can manually create the directory structure instead:
#         mkdir -p .specify/memory && touch .specify/memory/constitution.md
#
# Path to spec-kit constitution (relative to project root).
# Default: empty (spec-kit not used)
# SPIRAL_SPECKIT_CONSTITUTION=".specify/memory/constitution.md"
#
# Path to specs directory (relative to project root).
# Default: empty (stories use prd.json only)
# SPIRAL_SPECKIT_SPECS_DIR="specs"

# ── Memory management (OOM prevention) ───────────────────────────────────────
# V8 heap cap per process (MB). Controls --max-old-space-size for all spawned
# Claude CLI instances. Total process RSS ≈ 1.3-1.5x this value (non-heap
# overhead from Zones, Buffers, JIT code, stacks).
#
# Memory budget formula for parallel workers:
#   max_workers = floor((TotalRAM - OS - MainSession - Python) * 0.8 / per_worker_RSS)
#   per_worker_RSS ≈ SPIRAL_MEMORY_LIMIT * 1.5
#
# Recommendations by system RAM:
#   8 GB  → 512  (1 worker max)
#   16 GB → 1024 (2-3 workers)
#   32 GB → 2048 (4-5 workers)
#
# Default: 1024
# SPIRAL_MEMORY_LIMIT=1024

# Per-worker V8 heap cap (MB). Workers run full Claude CLI sessions and often
# need more memory than the lightweight orchestrator. Set this higher than
# SPIRAL_MEMORY_LIMIT to give workers a larger heap without over-allocating
# for the orchestrator or research phases.
#
# run_parallel_ralph.sh overrides SPIRAL_MEMORY_LIMIT with this value before
# spawning each worker; ralph.sh then picks it up via NODE_OPTIONS.
#
# Default: ${SPIRAL_MEMORY_LIMIT:-1024}
# Example: 2048 (2 GB per worker on a 16 GB+ machine)
# SPIRAL_WORKER_MEMORY_LIMIT=2048

# ── cgroups v2 per-worker isolation (Linux only, US-259) ────────────────────
# Kernel-enforced hard memory and CPU limits for each Ralph worker subprocess.
# Automatically skipped with a warning on macOS, Windows, or kernels without
# cgroups v2 unified hierarchy.
#
# SPIRAL_WORKER_MEM_LIMIT_MB — memory.max per worker (bytes = value × 1048576).
# Default: 2048 (2 GB). Set to 0 to disable the memory limit.
# SPIRAL_WORKER_MEM_LIMIT_MB=2048
#
# SPIRAL_WORKER_CPU_QUOTA — cpu.max quota as a percentage of one CPU (1–100).
# 80 means the worker may use at most 80% of a single CPU core.
# Default: 80.
# SPIRAL_WORKER_CPU_QUOTA=80

# Memory watchdog: background PowerShell monitor that kills Node.js processes
# exceeding the RSS threshold. Requires PowerShell on Windows.
# 1 = enabled (default), 0 = disabled.
# SPIRAL_MEMORY_WATCHDOG=1

# Watchdog kill threshold (MB RSS). When a Node.js process exceeds this,
# the watchdog terminates it. Should be > SPIRAL_MEMORY_LIMIT to allow for
# non-heap allocations (Zones, JIT, Buffers, stacks).
# Default: 1536 (~50% above 1024 V8 cap, or ~25% above 1024+overhead).
# SPIRAL_MEMORY_THRESHOLD=1536

# ── Adaptive memory management ("Low Power Mode") ──────────────────────────
# Graduated memory pressure system that throttles SPIRAL instead of killing.
# The watchdog writes a pressure level (0-4) to a signal file. All scripts
# self-regulate by reading it at natural decision points.
#
# Level 0 (normal):    >40% free  -> full speed
# Level 1 (elevated):  25-40%     -> brief delays
# Level 2 (high):      15-25%     -> reduce workers, cap model at sonnet, skip Phase R
# Level 3 (critical):  8-15%      -> 1 worker, haiku, skip R+T, pause workers
# Level 4 (emergency): <8%        -> kill largest process
#
# 1 = enabled (default), 0 = disabled (kill-only watchdog behavior)
# SPIRAL_LOW_POWER_MODE=1

# Comma-separated free RAM % boundaries for pressure levels 1-4 (descending).
# Format: normal,elevated,high,critical (% free RAM thresholds)
# Default: "40,25,15,8"
# SPIRAL_PRESSURE_THRESHOLDS="40,25,15,8"

# Watchdog poll interval in seconds. Lower = more responsive, higher = less CPU.
# Default: 15
# SPIRAL_MEMORY_POLL_INTERVAL=15

# Which degradation strategies to apply under pressure.
# Comma-separated: workers,model,phases,cooldown
# Default: "workers,model,phases,cooldown" (all strategies)
# SPIRAL_DEGRADATION_STRATEGIES="workers,model,phases,cooldown"

# Number of consecutive polls at a lower level before reporting the drop.
# Prevents oscillation when memory hovers near a threshold boundary.
# Default: 2
# SPIRAL_PRESSURE_HYSTERESIS=2

# ── Pinchtab E2E browser assertions (Phase V) ────────────────────────────
# When set, Phase V runs pinchtab shell-driven E2E steps after pytest passes.
#
# Pinchtab is a persistent HTTP browser server. Unlike Chrome DevTools MCP
# (which lives inside a Claude agent turn), pinchtab is called from shell —
# exactly like pytest or npm test.
#
# Decision guide:
#   Chrome DevTools MCP — inline visual check DURING Phase I (ralph agent)
#   pinchtab            — shell-driven E2E assertions AFTER pytest in Phase V
#
# Advantages over Chrome DevTools MCP for Phase V:
#   - Token-efficient: `pinchtab text` ~800 tokens vs ~10,000 for screenshot
#   - Persistent session: login once per Spiral run, reuse across iterations
#   - Parallel-safe: each worker can request an isolated browser instance
#   - Shell-assertable: pipe `pinchtab text` to grep for pass/fail logic
#
# Setup (one-time):
#   1. Install pinchtab: npm install -g pinchtab (or your installer)
#   2. Start the server: pinchtab serve --port 9867
#   3. Set SPIRAL_PINCHTAB_URL below
#   4. (Optional) Set SPIRAL_PINCHTAB_E2E_CMD to override the default steps
#
# Default E2E steps when SPIRAL_PINCHTAB_URL is set and SPIRAL_DEV_URL is set:
#   1. pinchtab nav $SPIRAL_DEV_URL
#   2. pinchtab text | grep -q "expected content" → pass/fail
#
# Override with a custom script for login flows or multi-step assertions:
#   SPIRAL_PINCHTAB_E2E_CMD="bash $PWD/scripts/pinchtab-e2e.sh"
#
# Default: empty (disabled)
# SPIRAL_PINCHTAB_URL="http://localhost:9867"
#
# Custom E2E command (optional — runs instead of the default nav+text steps)
# SPIRAL_PINCHTAB_E2E_CMD=""

# ── Lighthouse audit (Phase V — visual quality) ──────────────────────────
# When enabled, runs a Lighthouse audit after the test suite in Phase V.
# Checks performance, accessibility, and best-practices scores.
# Requires: npx (Node.js) and a running dev server at SPIRAL_LIGHTHOUSE_URL.
# Default: 0 (disabled)
# SPIRAL_LIGHTHOUSE=1

# URL to audit. Should point to the running dev server or preview build.
# Default: http://localhost:5173
# SPIRAL_LIGHTHOUSE_URL="http://localhost:5173"

# Minimum score (0-100) for any Lighthouse category before a warning is printed.
# Does not fail the build — informational only.
# Default: 50
# SPIRAL_LIGHTHOUSE_THRESHOLD=50

# ── Phase hooks (pre/post phase callbacks) ──────────────────────────────────
# User-defined executable scripts called before and after each SPIRAL phase
# (R, M, G, I, V). Use for custom actions like seeding a database before
# Phase V, or posting a Slack notification after Phase I.
#
# Hook contract:
#   - The hook receives these env vars: SPIRAL_CURRENT_PHASE (I/R/M/V/G),
#     SPIRAL_CURRENT_STORY_ID (empty for pre-R/M/G/V hooks), SPIRAL_RUN_ID,
#     SPIRAL_ITERATION.
#   - A non-zero exit code from a PRE hook aborts the current story attempt
#     (SPIRAL skips to the next iteration and records the failure).
#   - A non-zero exit code from a POST hook is logged as a warning; execution
#     continues.
#   - Hooks are executed with `timeout SPIRAL_HOOK_TIMEOUT` to prevent stalls.
#
# Example pre-hook (seed DB before Phase V):
#   #!/bin/bash
#   [ "$SPIRAL_CURRENT_PHASE" = "V" ] && psql -c "TRUNCATE test_data" || true
#
# Example post-hook (Slack notification after Phase I):
#   #!/bin/bash
#   [ "$SPIRAL_CURRENT_PHASE" = "I" ] && \
#     curl -s -X POST "$SLACK_WEBHOOK" -d "{\"text\":\"Story $SPIRAL_CURRENT_STORY_ID done\"}"
#
# Default: empty (disabled)
# SPIRAL_PRE_PHASE_HOOK="$PWD/scripts/spiral-pre-hook.sh"
# SPIRAL_POST_PHASE_HOOK="$PWD/scripts/spiral-post-hook.sh"
#
# Timeout in seconds for each hook invocation. Default: 30
# SPIRAL_HOOK_TIMEOUT=30

# ── Outbound webhook (phase-level notifications) ──────────────────────────
# Post a JSON payload to this HTTPS URL at the start and end of each SPIRAL
# phase (R, T, M, G, I, V, C).  Empty = disabled.
# SPIRAL_NOTIFY_WEBHOOK="https://example.com/hooks/spiral"
#
# Maximum seconds to wait for the webhook HTTP response. Default: 5
# SPIRAL_NOTIFY_WEBHOOK_TIMEOUT=5
#
# Optional extra HTTP header appended to every request (e.g. auth token).
# SPIRAL_NOTIFY_WEBHOOK_HEADERS="Authorization: Bearer TOKEN"
#
# HMAC-SHA256 signing secret (US-207).  When set, every POST includes an
# X-Spiral-Signature-256: sha256=<hex> header so receivers can verify payload
# authenticity (follows GitHub webhook signing convention).
# Leave unset to omit the header (backward-compatible).
# spiral-doctor warns when SPIRAL_NOTIFY_WEBHOOK is set but this is not.
# SPIRAL_NOTIFY_WEBHOOK_SECRET="your-signing-secret"

# ── _last_run.log rotation ────────────────────────────────────────────────
# Rotate .spiral/_last_run.log when it exceeds this size in megabytes.
# When exceeded, the current log is renamed to _last_run.log.1, previous .1
# becomes .2, and so on. Files beyond SPIRAL_LOG_KEEP_ROTATIONS are deleted.
# A rotation notice is written as the first line of the new log.
# 0 = disabled (never rotate). Default: 50
# SPIRAL_LOG_MAX_MB=50
#
# Number of rotated log files to keep alongside the active log.
# Rotations are named _last_run.log.1 (newest) through _last_run.log.N.
# Default: 3
# SPIRAL_LOG_KEEP_ROTATIONS=3

# ── progress.txt rotation ─────────────────────────────────────────────────
# Maximum number of lines in progress.txt before it is archived and reset.
# When exceeded, progress.txt is renamed to progress-YYYYMMDD-HHMMSS.txt and
# a fresh empty progress.txt is created. This prevents the file from growing
# unboundedly across many SPIRAL iterations.
# 0 = disabled (never rotate). Default: 2000
# SPIRAL_PROGRESS_MAX_LINES=2000

# ── Circuit breaker for LLM API calls ────────────────────────────────────────
# SPIRAL wraps every LLM call with a three-state circuit breaker
# (CLOSED → OPEN → HALF_OPEN → CLOSED) to protect against API instability.
#
# How it works:
#   1. After SPIRAL_CB_FAILURE_THRESHOLD consecutive transient errors
#      (HTTP 429 / 502 / 503 / 504 / 529), the breaker trips to OPEN and
#      blocks further calls for SPIRAL_CB_COOLDOWN_SECS seconds.
#   2. After the cooldown, the breaker enters HALF_OPEN and allows a single
#      probe call.  A successful probe resets to CLOSED (normal); a failed
#      probe restarts the cooldown and the breaker stays OPEN.
#
# State is persisted per-model-endpoint in .spiral/circuit_breaker.json
# (or .spiral/circuit_breaker_ENDPOINT.json for named endpoints).
# Only transient errors count: 429, 500, 502, 503, 504, 529.
# Permanent errors (400, 401, 403) are ignored.
#
# Consecutive failures before tripping circuit breaker. Default: 5
# SPIRAL_CB_FAILURE_THRESHOLD=5

# Cooldown period in seconds when the circuit is OPEN. Default: 60
# SPIRAL_CB_COOLDOWN_SECS=60

# ── AI commit identity (optional) ────────────────────────────────────────────
# When set, Ralph uses `git -c user.name=... -c user.email=... commit` to tag
# AI-generated commits with a distinct identity — without touching the global
# git config.  A `Generated-By: SPIRAL` trailer is also appended to the commit
# message, making it easy to filter AI commits with `git log --grep`.
#
# Enables audit workflows and `git blame` tooling to surface AI-generated lines.
# When unset, commits inherit the machine's default git identity (no change).
#
# Examples:
# SPIRAL_GIT_AUTHOR="SPIRAL Agent"
# SPIRAL_GIT_EMAIL="spiral@noreply.local"

# ── Per-story feature branching (US-157) ─────────────────────────────────────
# When SPIRAL_BRANCH_PREFIX is set, Ralph creates a dedicated git branch for
# each story before Phase I implementation, enabling clean PR-per-story workflows.
# Branch name convention: <SPIRAL_BRANCH_PREFIX>/<STORY_ID> (e.g. spiral/US-042)
#
# After story passes Phase V:
#   - SPIRAL_CREATE_PRS=false (default): branch merged to SPIRAL_BASE_BRANCH with
#     --no-ff, then deleted (unless SPIRAL_KEEP_STORY_BRANCHES=true)
#   - SPIRAL_CREATE_PRS=true: branch pushed to remote; left open for PR creation
#
# Branch creation is idempotent — `git checkout -B` resets the branch to the
# current HEAD if it already exists, supporting story replays safely.
#
# Default: empty (no feature branching — all work on current branch)
# SPIRAL_BRANCH_PREFIX="spiral"
#
# Base branch to merge story branches back into (default: branch at startup).
# SPIRAL_BASE_BRANCH="main"
#
# Keep story branches after successful merge (default: false — delete after merge).
# SPIRAL_KEEP_STORY_BRANCHES=false

# ── Dirty working tree guard (US-177) ────────────────────────────────────────
# If the working tree has uncommitted changes when Phase I is about to run,
# SPIRAL_AUTO_STASH=true automatically stashes them, runs Phase I, then pops
# the stash afterwards.  If false (default), Phase I is skipped with an
# actionable message telling the user to commit or stash their changes first.
#
# SPIRAL_AUTO_STASH=false   # default: abort Phase I if tree is dirty
# SPIRAL_AUTO_STASH=true    # auto-stash dirty changes around Phase I

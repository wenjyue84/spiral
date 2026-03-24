#!/bin/bash
# spiral.config.sh — Spiral running on itself
# Focus: token/quality balance, wizard education, Chrome DevTools integration

# ── Python interpreter ───────────────────────────────────────────────────────
# Use venv Python directly — "uv run python" fails when quoted in spiral.sh ($SPIRAL_PYTHON is quoted)
SPIRAL_PYTHON="/c/Users/Jyue/Documents/1-projects/Software Projects/Spiral/.venv/Scripts/python.exe"

# ── Test / validation command ────────────────────────────────────────────────
SPIRAL_VALIDATE_CMD="uv run pytest tests/ -v --tb=short -n 6"

# ── Phase V timeout (seconds) ─────────────────────────────────────────────
# Default 300s is too short for 2900+ tests. Increased to 600s.
SPIRAL_VALIDATE_TIMEOUT=600

# ── Baseline test count (for test ratchet in ralph) ──────────────────────────
# DISABLED: pytest --collect-only was consuming the entire Ralph budget (1800s)
# inside the Claude CLI session, causing every story to time out during baseline
# counting. Hardcoded to last known passing count (~2900) as instant fallback.
# Re-enable once baseline counting is moved outside the Claude CLI session.
export SPIRAL_TEST_BASELINE_CMD='echo 2900'

# ── Model routing: auto routes haiku→sonnet→opus by story complexity ─────────
# Options: auto | haiku | sonnet | opus
# auto = cheapest model that can handle the story; escalates on retry
SPIRAL_MODEL_ROUTING="auto"

# Context-window safety margin: upgrade model if prompt exceeds this fraction of the limit (US-295)
# Default 0.85 = upgrade when prompt > 85% of the 200k context window (~170k tokens)
SPIRAL_CONTEXT_WINDOW_MARGIN="${SPIRAL_CONTEXT_WINDOW_MARGIN:-0.85}"

# ── Adaptive thinking effort (US-373) ─────────────────────────────────────────
# Controls --effort flag for 4.6 models (opus/sonnet). Choices: low/medium/high/max.
# Older models (haiku-4-5, sonnet-4-5) ignore this and use default budget_tokens.
SPIRAL_THINKING_EFFORT="${SPIRAL_THINKING_EFFORT:-high}"

# ── Thinking budget cap (US-398) ─────────────────────────────────────────────
# Maximum thinking tokens per story. Maps to --effort level in Claude CLI:
#   0          = disable thinking entirely (no --effort flag)
#   1024-4999  = low
#   5000-9999  = medium
#   10000-49999 = high (default)
#   50000+     = max
# Minimum 1024 when >0 (Anthropic API floor). spiral-doctor validates this.
# Any value ≥50000 maps to --effort max (unlimited thinking). The number is
# NOT passed as a token cap — it only selects the effort level.
SPIRAL_THINKING_BUDGET_TOKENS="${SPIRAL_THINKING_BUDGET_TOKENS:-200000}"

# ── Programmatic tool calling (US-339) ──────────────────────────────────────
# Enable code_execution_20250825 tool for orchestrated multi-tool calls in sandboxed
# code. Requires Claude Sonnet 4.6+. When enabled, allows code to call bash_execute,
# file_read, file_write in a single inference pass, reducing pass count by ~37%.
# Options: true (enable when model supports), false (disabled), auto (auto-detect)
# When enabled on unsupported models (haiku), falls back gracefully.
SPIRAL_PROGRAMMATIC_TOOLS="${SPIRAL_PROGRAMMATIC_TOOLS:-auto}"

# ── Interleaved thinking (US-392) ───────────────────────────────────────────────
# Enable interleaved-thinking-2025-05-14 beta for iterative reasoning throughout
# the implementation workflow. Supported on claude-opus-4-6 and claude-sonnet-4-6.
# When enabled, Claude reasons between tool calls rather than only before the first one.
# Options: true (enable), false (disabled, default)
# This doubles token consumption but enables more sophisticated multi-step planning.
SPIRAL_INTERLEAVED_THINKING="${SPIRAL_INTERLEAVED_THINKING:-true}"

# Enable episodic memory injection into Ralph worker context. When true, queries
# .spiral/episodic_memory.db for top-3 similar past implementations by story title
# and injects them as few-shot examples in the user prompt. Requires episodic_memory.db
# to exist (populated by US-433 after successful story commits).
# Options: true (enable), false (disabled, default)
SPIRAL_EPISODIC_MEMORY="${SPIRAL_EPISODIC_MEMORY:-false}"

# ── Phase X: Repo map / symbol map context injection ───────────────────────
# When true, Phase X parses filesTouch entries and generates per-story symbol
# maps (exports, imports, test neighbors, callers, boundaries). Injected into
# Ralph's user prompt at zero LLM cost.
SPIRAL_REPO_MAP="${SPIRAL_REPO_MAP:-true}"
SPIRAL_REPO_MAP_MAX_LINES="${SPIRAL_REPO_MAP_MAX_LINES:-150}"

# ── Phase-specific model defaults ────────────────────────────────────────────
# Each non-implementation phase can use a cheaper model (haiku is ~15x cheaper
# than sonnet). Phase I continues to use SPIRAL_MODEL_ROUTING for escalation.
SPIRAL_RESEARCH_MODEL="haiku" # Phase R: research synthesis model
# Model for Phase A LLM story generation. Defaults to haiku (cheapest).
# SPIRAL_AI_SUGGEST_MODEL="claude-haiku-4-5-20251001"
SPIRAL_VALIDATION_MODEL="haiku" # Phase S: story validation (future — currently Python-only)
SPIRAL_MERGE_MODEL="haiku"      # Phase M: merge decisions (future — currently Python-only)
# Bulk override format: SPIRAL_PHASE_MODEL_OVERRIDE=R:haiku,S:haiku,M:haiku
# SPIRAL_PHASE_MODEL_OVERRIDE=""

# ── CodeQL deep semantic analysis ──────────────────────────────────────────────
# Second security lens alongside Semgrep. Semgrep catches patterns quickly;
# CodeQL finds deeper data-flow and variant-style vulnerabilities.
# Runs in Phase V after tests pass (the "serious judge").
# Requires: codeql CLI (install: gh extension install github/gh-codeql)
# SPIRAL_CODEQL_ENABLED="false"              # true to enable
# SPIRAL_CODEQL_MODE="validate"              # validate | gate | nightly
# SPIRAL_CODEQL_LANGUAGES="python"           # space-separated: python javascript
# SPIRAL_CODEQL_QUERY_SUITE="security-and-quality"  # or security-extended
# SPIRAL_CODEQL_BLOCKING="false"             # true = block on HIGH/CRITICAL
# SPIRAL_CODEQL_KEEP_DB="false"              # true = keep DB for debugging

# ── Dead Feature Detector (US-1006) ──────────────────────────────────────────
# Phase V scan to find newly added functions/classes that are never imported or
# called from the codebase. Prevents "code exists but doesn't work" implementations.
# Default false = soft warning (logged but does not block)
# Set to true to hard block: Phase V fails if any dead features detected
SPIRAL_STRICT_DEAD_FEATURE="${SPIRAL_STRICT_DEAD_FEATURE:-false}"

# ── Phase Timing Regression Detector (US-1008) ───────────────────────────────
# Records execution time baseline (P50/P90) for each SPIRAL phase from the last 10
# iterations. After each iteration, checks if any phase exceeded 2x its P90 baseline.
# Default false = soft warning (logged but does not block)
# Set to true to hard block: Phase C fails if regression detected
SPIRAL_STRICT_PERF_CHECK="${SPIRAL_STRICT_PERF_CHECK:-false}"
# Regression threshold multiplier (default 2.0 = 2x P90 baseline)
SPIRAL_PERF_REGRESSION_MULTIPLIER="${SPIRAL_PERF_REGRESSION_MULTIPLIER:-2.0}"

# ── Story enrichment pass (US-443) ────────────────────────────────────────────
# After Phase S validation, optionally refine medium/sparse stories: rewrite
# vague ACs, add exact file paths + test commands, split stories touching 3+
# files. Costs one extra Claude call per eligible story but prevents 2-3 retry
# cycles in Phase I. Set to true to opt in.
SPIRAL_STORY_ENRICHMENT="${SPIRAL_STORY_ENRICHMENT:-true}"
# Model for enrichment pass. sonnet is default; set to opus for maximum quality.
SPIRAL_STORY_ENRICHMENT_MODEL="${SPIRAL_STORY_ENRICHMENT_MODEL:-sonnet}"
# Max stories to enrich per iteration (0=unlimited). Default: 10.
SPIRAL_STORY_ENRICHMENT_MAX="${SPIRAL_STORY_ENRICHMENT_MAX:-10}"

# ── Context injection mode (US-280) ──────────────────────────────────────────
# diff = inject git diff of filesTouch paths (empty for new files)
# full = inject complete file contents of filesTouch targets
SPIRAL_CONTEXT_MODE="full"

# ── Research focus prompt ────────────────────────────────────────────────────
# Guides Gemini + Claude in Phase R toward relevant context
SPIRAL_GEMINI_PROMPT="Focus on: (1) preventing stories from getting stuck — DLQ patterns, smarter auto-decomposition triggers, circuit breaker improvements, stuck-detection heuristics; (2) token efficiency without quality loss — prompt compression, response caching, batch API usage, selective model routing by story complexity; (3) execution speed — parallel phase pipelines, incremental test selection, worker heartbeat optimizations; (4) test coverage gaps — missing edge cases in lib/*.py and spiral.sh, property-based testing opportunities, regression test patterns for known failure modes. Provide actionable implementation context with concrete code examples."

# ── Story prefix ─────────────────────────────────────────────────────────────
SPIRAL_STORY_PREFIX="US"

# ── Parallel worker settings ─────────────────────────────────────────────────
# 3 workers (32GB RAM). Uses hot-file registry + sequential merge + file
# inference to minimize inter-worker merge conflicts.
SPIRAL_RALPH_WORKERS="${SPIRAL_RALPH_WORKERS:-3}"

# ── Conflict minimization (Strategies 1-3) ───────────────────────────────────
# Strategy 1: Hot File Registry — track historically conflict-prone files.
# Files with conflict weight >= threshold are hard co-located to same worker.
SPIRAL_HOT_FILE_THRESHOLD="${SPIRAL_HOT_FILE_THRESHOLD:-2}"
# Halve hot-file weight every N iterations (decay prevents stale constraints)
SPIRAL_HOT_FILE_DECAY_ITERS="${SPIRAL_HOT_FILE_DECAY_ITERS:-5}"

# Strategy 2: Auto-populate filesTouch via static analysis before partitioning.
# Parses story text for file/module refs, resolves against Phase X repo map.
SPIRAL_INFER_FILES_TO_TOUCH="${SPIRAL_INFER_FILES_TO_TOUCH:-true}"

# Strategy 3: Sequential merge with rebase (merge worker 1 → rebase worker 2 →
# merge worker 2 → etc). Resolves inter-worker conflicts inline instead of
# discarding entire workers. Workers merged in order of passed story count.
SPIRAL_SEQUENTIAL_MERGE="${SPIRAL_SEQUENTIAL_MERGE:-true}"

# Per-worker memory budget (MB) for pre-spawn gate. Gate requires
# (remaining_workers * this + 512) MB free before launching each worker.
# Default 1536 = V8 heap (1024) + typical non-heap overhead (512).
# Set lower (1024) on machines with limited free RAM.
export SPIRAL_MEMORY_GATE_MB=1024

# Hard timeout (minutes) for memory gate. 0 = wait forever (old behavior).
# Default 2 = wait up to 2 min, then launch anyway (watchdog handles runtime).
export SPIRAL_MEMORY_WAIT_MAX_MINS=2

# ── Dispatch mode: control worker scheduling strategy (US-361) ──────────────────
# Options: dag (new default) | parallel (legacy all-parallel)
# dag = tier-aware dispatch: tier 0 stories run in parallel, tier N+1 waits for tier N
# parallel = legacy mode: all workers run simultaneously regardless of dependencies
SPIRAL_DISPATCH_MODE="${SPIRAL_DISPATCH_MODE:-dag}"

# ── Dynamic memory pool (per-story reservation) ──────────────────────────────
# When true, workers dynamically reserve memory from a shared pool based on
# story complexity (model tier) instead of using a static 2048MB budget.
# false = legacy static _PER_WORKER_MB=2048 behavior (zero change).
SPIRAL_MEMORY_POOL="${SPIRAL_MEMORY_POOL:-true}"
# RAM excluded from pool for OS + orchestrator overhead (MB)
SPIRAL_POOL_RESERVE_MB="${SPIRAL_POOL_RESERVE_MB:-1024}"
# Per-tier reservation sizes (MB)
SPIRAL_POOL_TIER_SMALL="${SPIRAL_POOL_TIER_SMALL:-768}"    # haiku, score 0-1
SPIRAL_POOL_TIER_MEDIUM="${SPIRAL_POOL_TIER_MEDIUM:-1536}" # sonnet, score 2-4
SPIRAL_POOL_TIER_LARGE="${SPIRAL_POOL_TIER_LARGE:-2560}"   # opus, score 5+, retries >= 2
# V8 heap as percentage of reservation (remainder = non-heap overhead)
SPIRAL_POOL_V8_HEAP_FRACTION="${SPIRAL_POOL_V8_HEAP_FRACTION:-65}"
# Interval (seconds) for reclaiming reservations from dead worker PIDs
SPIRAL_POOL_RECLAIM_INTERVAL="${SPIRAL_POOL_RECLAIM_INTERVAL:-30}"

# ── Capacity limit: skip Phase R when pending stories exceed this ─────────────
# Prevents flooding prd.json during aggressive non-stop runs.
# Tightened to 15: at ~3-5 completions/iter, Phase R only runs when backlog is
# nearly clear, keeping the pending gap under control.
SPIRAL_MAX_PENDING=15

# ── Dead weight threshold: auto-archive stories stuck N+ iterations ────────────
# When a non-passed story survives more than this many iterations without progress,
# it's automatically marked _archived:true to prevent backlog bloat (US-779).
# Phase I skips archived stories but they remain in prd.json for audit.
# Default: 5 iterations. Set to 0 to disable dead weight detection.
SPIRAL_DEAD_WEIGHT_THRESHOLD=5

# ── Total story count assertion ceiling ───────────────────────────────────────
# Spiral has 264 total stories (243 done + 21 pending + room for research).
# Override the default of 200 to prevent abort on assert.
SPIRAL_MAX_TOTAL_STORIES=450

# ── Auto-stash dirty working tree before Phase I (US-177) ────────────────────
# Stashes uncommitted changes before ralph runs, pops them after.
# Required when running SPIRAL on itself (prd.json, config, etc. are always dirty).
SPIRAL_AUTO_STASH=true

# ── Stale git lock-file cleanup (US-225) ─────────────────────────────────────
# Lock files in worktrees older than this many minutes are removed (if no live
# git process is found). 0 = disable automatic cleanup.
SPIRAL_LOCK_TIMEOUT_MINUTES=5

# ── Batch size: cap stories visible to ralph per iteration ────────────────
# Only the N highest-priority pending stories are included in the PRD slice
# passed to ralph. 0 = disabled (all pending stories visible, current behavior).
SPIRAL_STORY_BATCH_SIZE=10

# ── Research story cap: max new stories Phase R may add per iteration ─────────
# Prevents Phase R from flooding prd.json each cycle. Matches the implementation
# rate (~3-5 completions/iter) so pending count stays roughly flat.
SPIRAL_MAX_RESEARCH_STORIES=5

# ── AI suggestion cap: max Phase A stories generated per iteration ────────────
# Phase A runs after Phase R and adds AI-generated story candidates.
# Set to 0 to stop generating new stories and focus on clearing the backlog.
SPIRAL_MAX_AI_SUGGEST=5

# ── AI suggestion quality threshold: filter low-quality stories (US-790) ─────────
# Stories scoring below this threshold are discarded before Phase S validation.
# Score (0-100) based on: production value (35%), constitution alignment (25%),
# acceptance criteria quality (25%), scope clarity (15%).
# Tier 1 (user-facing): ~90, Tier 2 (reliability): ~75, Tier 3 (power user): ~60, Tier 4 (infra): ~20.
# Default 40 filters out infrastructure-only and poorly-scoped stories.
SPIRAL_AI_SUGGEST_MIN_SCORE=40

# ── Dead weight detection: auto-archive stories stuck 5+ iterations ─────────────
# Tracks _pending_iterations counter per story. Stories exceeding this threshold
# are marked _archived: true with _archiveReason to prevent backlog bloat.
# Archived stories remain in prd.json for audit but are excluded from Phase I dispatch.
SPIRAL_DEAD_WEIGHT_THRESHOLD=5

# ── Phase S: Message Batches API validation (US-390) ──────────────────────
# Set to 1 to submit Phase S validation requests to the Anthropic Message
# Batches API (50% cost reduction vs sequential, async up to 10k stories).
# Requires ANTHROPIC_API_KEY. Single-story runs fall back to synchronous path.
# Batch summary is written to .spiral/_phase_s_batch.json.
SPIRAL_BATCH_VALIDATE="${SPIRAL_BATCH_VALIDATE:-1}"

# ── Auto-generate paired test stories for new feature stories ─────────────
# When set to 1, Phase R automatically generates a paired UT- test story for
# each new feature story discovered. Ensures test coverage keeps pace with
# feature discovery. 0 = disabled (default).
SPIRAL_SYNTHESIZE_TESTS_FOR_NEW="${SPIRAL_SYNTHESIZE_TESTS_FOR_NEW:-1}"

# ── Phase S: Majority-voting consensus for story validation (US-342) ─────────
# Number of independent LLM validation calls per story. Results are aggregated
# with majority voting (>50% accept → accept, ties default to reject).
# Research (arxiv:2502.19130) shows 13.2% error reduction with N=3.
# Set to 1 for single-call behavior (no voting overhead, same as current).
# Default 3 balances quality (better decisions) with cost (3x API calls per story).
# Note: Vote results are recorded in results.tsv as votes_accept/votes_reject fields.
SPIRAL_VALIDATION_VOTES="${SPIRAL_VALIDATION_VOTES:-3}"

# ── Semantic dedup threshold (US-371) ───────────────────────────────────────
# TF-IDF cosine similarity threshold for near-duplicate story detection in Phase S.
# Stories from 'research' or 'ai-example' sources with similarity >= threshold to
# an existing prd.json story are rejected as semantic duplicates.
# 0.85 is conservative to avoid false positives on related-but-distinct stories.
# Set to 0 to disable semantic dedup entirely.
SPIRAL_SEMANTIC_DEDUP_THRESHOLD="${SPIRAL_SEMANTIC_DEDUP_THRESHOLD:-0.85}"

# ── End-game dedup threshold (anti-plateau strategy) ────────────────────────
# When done/total > 0.90 (end-game mode), Phase S uses this lower threshold so
# stories covering distinct sub-systems of already-implemented features can
# still enter the pipeline. Quality scoring still applies — only dedup is relaxed.
# 0.70 allows different-module coverage while blocking near-verbatim duplicates.
SPIRAL_ENDGAME_DEDUP_THRESHOLD="${SPIRAL_ENDGAME_DEDUP_THRESHOLD:-0.70}"

# ── Worker env allowlist (US-359) ──────────────────────────────────────────
# Comma-separated list of env var names/prefixes passed to worker subprocesses.
# Suffix * for prefix match (e.g. SPIRAL_* matches SPIRAL_WORKER_ID, SPIRAL_PYTHON).
# Anything not listed is unset before ralph.sh runs inside the worker.
SPIRAL_WORKER_ENV_ALLOWLIST="${SPIRAL_WORKER_ENV_ALLOWLIST:-ANTHROPIC_API_KEY,PATH,HOME,TMPDIR,TERM,SHELL,USER,LANG,TZ,SPIRAL_*,NODE_*,CLAUDE_*,RALPH_*,HEARTBEAT_DIR,TRACEPARENT,TRACESTATE,JQ,PYTHON,PWD,SHLVL}"

# ── Cascading-failure fan-out cap (US-322) ──────────────────────────────────
# Max consecutive story failures within a single Phase I before aborting.
# Prevents runaway failure propagation when a shared dependency is broken.
# 0 = disabled (never abort on consecutive failures).
SPIRAL_CASCADE_FAN_OUT_LIMIT="${SPIRAL_CASCADE_FAN_OUT_LIMIT:-5}"

# ── Consecutive zero-progress abort (US-400) ────────────────────────────────
# Stop the loop after N consecutive iterations where no story passes.
# Prints a diagnostic listing stuck story IDs, retry counts, and last failure
# reasons, then exits with ERR_ZERO_PROGRESS (exit code 9).
# 0 = disabled (unlimited retries; recovery strategies still apply).
# Default 3 matches the existing graduated recovery (decompose → halve batch → halt).
SPIRAL_CONSECUTIVE_FAIL_ABORT=0 # disabled — allow retries on difficult sub-stories

# ── Skip disk space preflight check (slow on Windows NTFS) ──────────────────
export SPIRAL_SKIP_DISK_CHECK=1

# ── Implementation timeout per story ─────────────────────────────────────
export SPIRAL_IMPL_TIMEOUT=1800
export SPIRAL_WORKER_TIMEOUT=1800

# ── Per-complexity timeouts (defaults: small=300, medium=600, large=1200) ──
# Doubled to give Ralph enough runway for complex stories (integration tests, CLI tools)
export SPIRAL_STORY_TIMEOUT_SMALL=1200
export SPIRAL_STORY_TIMEOUT_MEDIUM=1800
export SPIRAL_STORY_TIMEOUT_LARGE=2400

# ── Cost ceiling: abort when cumulative API spend exceeds budget ──────────────
# Set to a USD amount (e.g., 50.0) to cap spending. Empty = disabled.
# SPIRAL_COST_CEILING=""

# ── Per-story cost limits ────────────────────────────────────────────────────
# Disabled — user wants no per-story cost ceiling (stories were being abandoned
# prematurely). ralph.sh defaults to 9999.00 when unset, effectively disabling.
# export SPIRAL_STORY_COST_HARD_USD=10.00
# export SPIRAL_STORY_COST_WARN_USD=5.00
# Force-clear stale env vars from previous sessions that may override the above
unset SPIRAL_STORY_COST_HARD_USD
unset SPIRAL_STORY_COST_WARN_USD

# ── Diminishing returns detection (US-783) ───────────────────────────────────
# Phase C checks cost-per-new-pass. If it exceeds this multiplier 3 consecutive
# times, SPIRAL exits cleanly with diagnostic (avoids budget waste).
# Default 2.0 = exit when cost per story doubles 3 consecutive iterations.
SPIRAL_DIMINISHING_RETURNS_MULTIPLIER="${SPIRAL_DIMINISHING_RETURNS_MULTIPLIER:-2.0}"

# ── Specialist prompt file (optional) ────────────────────────────────────────
# Path to a static prompt file used as fallback when Gemini is unavailable.
# Leave empty unless you have a domain-specific specialist prompt.
SPIRAL_RESEARCH_SPECIALIST_PROMPT=""

# ── Dev server URL for visual screenshots (Phase V) ───────────────────────
# When set, Phase V will attempt Chrome DevTools screenshot after validation.
# Screenshots saved to $SCRATCH_DIR/screenshots/iter-N-TIMESTAMP.png
# Leave empty to disable.
# SPIRAL_DEV_URL=""

# ── Pinchtab URL for Phase V shell-driven E2E assertions ─────────────────
# When set, Phase V runs pinchtab E2E steps (nav + text assertion) AFTER
# pytest passes. Pinchtab is a persistent HTTP browser server — text mode
# costs ~800 tokens vs ~10,000 for a screenshot.
# Start pinchtab manually: pinchtab serve (default: http://localhost:9867)
# Leave empty to disable.
# SPIRAL_PINCHTAB_URL="http://localhost:9867"

# ── Incremental Phase V validation (US-131) ───────────────────────────────
# When true, Phase V runs only the tests that cover files touched by the
# current story (derived from prd.json filesTouch field), instead of the full
# SPIRAL_VALIDATE_CMD suite. Falls back to full suite when no matching tests
# are found, or when all stories are complete (final gate always runs full suite).
# For pytest: test file derived as <SPIRAL_TEST_PREFIX><basename>.py
# For vitest: appends --related <filesTouch entries> to SPIRAL_VALIDATE_CMD
SPIRAL_INCREMENTAL_VALIDATE=true
# SPIRAL_TEST_PREFIX="tests/test_"

# ── Self-consistency hallucination check (US-228) ──────────────────────────
# When true, skips consistency checks on story acceptance criteria (fast path).
# Default false = consistency checks enabled (run prompts twice, flag divergent fields).
# SPIRAL_SKIP_CONSISTENCY_CHECK=false

# ── Manual story exclusion ─────────────────────────────────────────────────
# Comma-separated story IDs to permanently skip without penalty (no retry
# increment). Use for stories that are blocked externally or descoped mid-run.
# US-318 to US-335: Tier 4 stories (OTel spans, DeepEval, RAGAS, HMAC, etc.)
# requiring external dependencies not available in this environment.
SPIRAL_SKIP_STORY_IDS="US-318,US-319,US-320,US-321,US-322,US-323,US-324,US-325,US-326,US-327,US-328,US-329,US-330,US-331,US-332,US-333,US-334,US-335,US-447,US-461,US-466,US-467,US-471,US-481,US-656"
# US-656 skipped: federated-rebase rewrites story IDs — destructive and untestable in isolation
# US-481 skipped: 5+ timeout failures — HTTP API story too complex for haiku in 600s
# US-471 skipped: timed out 10+ times at 600s — Claude explores without implementing
# US-466 skipped: timed out 17+ times across all models — Claude spends entire 600s
# exploring codebase without implementing. Needs manual decomposition.
# US-447 skipped: claude CLI hits "Argument list too long" (Windows E2BIG) every attempt
# — Node.js can't start because PATH+env exceeds OS limit. Requeue after shortening PATH.
# US-461 skipped: baseline test counting consumes entire budget before implementation starts
# SPIRAL_SKIP_STORY_IDS=""

# ── Dashboard auto-refresh interval (seconds) ─────────────────────────────
# The HTML dashboard includes a <meta http-equiv='refresh'> tag so the browser
# reloads automatically during active runs. Set to 0 to disable (static mode).
SPIRAL_DASHBOARD_REFRESH_SECS=30

# ── Large PRD streaming threshold (US-123) ────────────────────────────────
# When prd.json exceeds this size (in KB), ralph.sh switches to jq --stream
# to avoid loading the entire document into memory. Default 512 KB covers
# ~1000-story PRDs comfortably. Set to 0 to always use streaming (useful for
# testing). Requires jq 1.6+ for --stream support.
SPIRAL_PRD_STREAM_THRESHOLD_KB=2048 # streaming jq path has a bug; keep on in-memory path until prd.json > 2MB

# ── Research output cache TTL (US-170) ───────────────────────────────────
# When set to a positive integer, Phase R is skipped entirely if
# _research_output.json already exists and is younger than this many hours.
# Also controls URL-level cache expiry in lib/research_cache.py.
# 0 = disabled (Phase R always runs). Default: 0.
# Example: SPIRAL_RESEARCH_CACHE_TTL_HOURS=6  # reuse research for up to 6h
SPIRAL_RESEARCH_CACHE_TTL_HOURS=4

# ── Query-level semantic cache TTL (US-773) ──────────────────────────────
# Number of iterations to retain cached research query results (based on iteration number).
# Queries >0.90 semantically similar to a cached result return cached response instead of
# making a new API call. Default 5 = retain results from last 5 iterations.
SPIRAL_RESEARCH_CACHE_TTL="${SPIRAL_RESEARCH_CACHE_TTL:-5}"

# ── Query dedup similarity threshold (US-773) ─────────────────────────────
# TF-IDF cosine similarity threshold for research query dedup. Queries with similarity
# >= threshold return cached result instead of calling Gemini. Default 0.90 (90% match).
SPIRAL_RESEARCH_DEDUP_THRESHOLD="${SPIRAL_RESEARCH_DEDUP_THRESHOLD:-0.90}"

# ── Research query cache enable/disable toggle (US-1027) ─────────────────
# When set to 0, disables all semantic caching in Phase R. Used for benchmarking
# baseline latency without cache. Default 1 = cache enabled (normal operation).
SPIRAL_RESEARCH_CACHE_ENABLED="${SPIRAL_RESEARCH_CACHE_ENABLED:-1}"

# ── Cosine-similarity research cache threshold (US-403) ───────────────────
# When a Phase R query misses the exact-match cache, sentence embeddings
# (MiniLM) are compared. Hits above this threshold return the cached result.
# Set to 1.0 to disable similarity lookup (exact match only).
# SPIRAL_CACHE_SIM_THRESHOLD=0.92

# ── Hierarchical summarization of Phase R output (US-254) ─────────────────
# When Phase R research output exceeds this token threshold, a summarization
# pass compresses story descriptions while preserving acceptance criteria,
# technical notes, and source URLs.  0 = disabled (no summarization).
# SPIRAL_RESEARCH_SUMMARY_THRESHOLD=4000
#
# Set to 1 to bypass summarization and pass full research to downstream phases.
# SPIRAL_USE_FULL_RESEARCH=0

# ── git-cliff binary path (Phase G changelog generation) ──────────────────
# Path to git-cliff executable. Defaults to "git-cliff" (found via PATH).
# Override to use a specific binary location.
SPIRAL_GIT_CLIFF_BIN="${SPIRAL_GIT_CLIFF_BIN:-git-cliff}"

# ── Spec-Kit constitution file ────────────────────────────────────────────
# Path (relative to repo root) to a constitution.md file that defines what
# this project IS, what it must never sacrifice, and what stories are out of
# scope. When set, Phase R reads it before generating stories and Ralph reads
# it before implementing each story. Acts as the "architect's veto".
SPIRAL_SPECKIT_CONSTITUTION=".specify/memory/constitution.md"

# ── Work stealing: idle worker prevention (Phase 3 safety) ─────────────────
# When true, finished workers claim uncompleted stories from a shared queue
# instead of sitting idle. Default: false (opt-in).
SPIRAL_WORK_STEALING="${SPIRAL_WORK_STEALING:-false}"

# ── LLM-as-Judge quality evaluation (US-248) ─────────────────────────────
# Score threshold (1-5) below which a quality warning is emitted.
# Warnings are non-blocking — they log to stderr but do not stop the run.
# Set to 0 to disable warnings. Default: 3.
# SPIRAL_QUALITY_THRESHOLD=3
#
# Set to 1 to disable the quality judge entirely (skips all LLM judge calls).
# SPIRAL_QUALITY_JUDGE_DISABLE=0

# ── Post-completion hook ───────────────────────────────────────────────────
# Shell command to run when ALL stories pass (check_done exits 0).
# Not run on iteration-limit exits, SIGINT, or errors.
# Example: SPIRAL_ON_COMPLETE='curl -s -X POST "$SLACK_WEBHOOK_URL" -d "{\"text\":\"Spiral done!\"}"'
# SPIRAL_ON_COMPLETE=""

# ── Strategy 1: Anti-pattern prompt injection ─────────────────────────────
# When true, each story failure appends the failure reason to _antiPatterns[]
# in prd.json. On the next retry, these are injected as a numbered "FORBIDDEN
# APPROACHES" list so the agent tries a fundamentally different implementation.
SPIRAL_ANTI_PATTERN_INJECT="${SPIRAL_ANTI_PATTERN_INJECT:-true}"

# ── Strategy 2: Early aggressive decomposition ────────────────────────────
# When true, a story that fails on its FIRST attempt is immediately decomposed
# if its complexity is >= SPIRAL_DECOMPOSE_FIRST_FAIL_COMPLEXITY (or its title
# word count > 12). This avoids wasting sonnet/opus calls on stories that
# should have been split from the start.
SPIRAL_DECOMPOSE_ON_FIRST_FAIL="${SPIRAL_DECOMPOSE_ON_FIRST_FAIL:-true}"
# Complexity threshold (small | medium | large) for first-fail decomposition.
SPIRAL_DECOMPOSE_FIRST_FAIL_COMPLEXITY="${SPIRAL_DECOMPOSE_FIRST_FAIL_COMPLEXITY:-medium}"

# ── OpenTelemetry privacy scrubbing (US-348) ────────────────────────────────
# Enable privacy-scrubbing span processor to redact sensitive data before
# telemetry export. See lib/privacy_scrubber.py for pattern definitions.
#
# SPIRAL_OTEL_EMIT_MESSAGES: Enable/disable gen_ai.input.messages and
#   gen_ai.output.messages attributes (default: false — opt-in for privacy).
#   Sensitive data in these fields will be redacted before export.
SPIRAL_OTEL_EMIT_MESSAGES="${SPIRAL_OTEL_EMIT_MESSAGES:-false}"
#
# SPIRAL_OTEL_SCRUB_PATTERNS: Comma-separated list of pattern names to enable.
#   Available patterns: anthropic_api_key, github_token, openai_api_key,
#   aws_secret, email, credential_path
#   Default: all patterns enabled (see lib/privacy_scrubber.py)
# SPIRAL_OTEL_SCRUB_PATTERNS="anthropic_api_key,github_token,openai_api_key,aws_secret,email,credential_path"
#
# SPIRAL_OTEL_SCRUB_FIELDS: Comma-separated list of attribute names to fully
#   redact (entire field removed, not pattern-matched).
#   Default: gen_ai.input.messages,gen_ai.output.messages
# SPIRAL_OTEL_SCRUB_FIELDS="gen_ai.input.messages,gen_ai.output.messages"
export SPIRAL_MAX_DIFF_LINES=400

# ── Phase V: AC Verification (US-1005) ───────────────────────────────────────
# When true, Phase V runs AC verification after pytest passes.
# Executes extracted assertions from .spiral/ac_checks/{story_id}.json and
# reports per-AC pass/fail results. Story fails only if zero assertions pass.
SPIRAL_AC_VERIFY=true

# ── Phase V: Dead Feature Detection (US-1006) ─────────────────────────────────
# When true, Phase V detects newly added Python functions/classes that are never
# called or imported (dead code). Default is soft warning (logs but does not block).
# Set to true to enable hard block: story fails if dead features found.
SPIRAL_STRICT_DEAD_FEATURE=false

# ── Reachability Verifier (US-1007) ────────────────────────────────────────
# Verify new Python modules for Phase stories are wired into spiral.sh/main.py.
# Default is soft warning (logs but does not block). Set to true to hard-block.
SPIRAL_STRICT_REACHABILITY=false

# ── Dashboard port allocation ────────────────────────────────────────────────
# Two servers run side-by-side. NEVER swap these ports.
#   Port 5299: Vite React dashboard (spiral-ui/) — full 11-tab UI
#   Port 5300: Python SSE server (spiral_live_server.py) — worker streaming + API
# spiral_live_server.py has a hard guard that refuses to start on SPIRAL_VITE_PORT.
# SPIRAL_VITE_PORT="5299"           # Vite dev server (spiral-ui/)
# SPIRAL_DASHBOARD_PORT="5300"      # Python SSE server (spiral_live_server.py)

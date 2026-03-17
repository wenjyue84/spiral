#!/bin/bash
# spiral.config.sh — Spiral running on itself
# Focus: token/quality balance, wizard education, Chrome DevTools integration

# ── Python interpreter ───────────────────────────────────────────────────────
# Use venv Python directly — "uv run python" fails when quoted in spiral.sh ($SPIRAL_PYTHON is quoted)
SPIRAL_PYTHON="/c/Users/Jyue/Documents/1-projects/Software Projects/Spiral/.venv/Scripts/python.exe"

# ── Test / validation command ────────────────────────────────────────────────
SPIRAL_VALIDATE_CMD="uv run pytest tests/ -v --tb=short"

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
SPIRAL_THINKING_BUDGET_TOKENS="${SPIRAL_THINKING_BUDGET_TOKENS:-10000}"

# ── Programmatic tool calling (US-339) ──────────────────────────────────────
# Enable code_execution_20250825 tool for orchestrated multi-tool calls in sandboxed
# code. Requires Claude Sonnet 4.6+. When enabled, allows code to call bash_execute,
# file_read, file_write in a single inference pass, reducing pass count by ~37%.
# Options: true (enable when model supports), false (disabled), auto (auto-detect)
# When enabled on unsupported models (haiku), falls back gracefully.
SPIRAL_PROGRAMMATIC_TOOLS="${SPIRAL_PROGRAMMATIC_TOOLS:-auto}"

# ── Phase-specific model defaults ────────────────────────────────────────────
# Each non-implementation phase can use a cheaper model (haiku is ~15x cheaper
# than sonnet). Phase I continues to use SPIRAL_MODEL_ROUTING for escalation.
SPIRAL_RESEARCH_MODEL="haiku"       # Phase R: research synthesis
SPIRAL_VALIDATION_MODEL="haiku"     # Phase S: story validation (future — currently Python-only)
SPIRAL_MERGE_MODEL="haiku"          # Phase M: merge decisions (future — currently Python-only)
# Bulk override format: SPIRAL_PHASE_MODEL_OVERRIDE=R:haiku,S:haiku,M:haiku
# SPIRAL_PHASE_MODEL_OVERRIDE=""

# ── Research focus prompt ────────────────────────────────────────────────────
# Guides Gemini + Claude in Phase R toward relevant context
SPIRAL_GEMINI_PROMPT="Focus on: achieving a delicate balance between token saving and quality of output code. Research token-efficient AI patterns, model routing strategies, dynamic complexity assessment, cost vs quality tradeoffs in LLM-powered coding agents, and best practices for setup wizards that educate users about configuration options. Provide actionable implementation context."

# ── Story prefix ─────────────────────────────────────────────────────────────
SPIRAL_STORY_PREFIX="US"

# ── Parallel worker settings ─────────────────────────────────────────────────
# Dynamic worker count (1-3) will be auto-selected once US-009 is implemented.
# Until then, leave unset and pass --ralph-workers on the command line.

# ── Dispatch mode: control worker scheduling strategy (US-361) ──────────────────
# Options: dag (new default) | parallel (legacy all-parallel)
# dag = tier-aware dispatch: tier 0 stories run in parallel, tier N+1 waits for tier N
# parallel = legacy mode: all workers run simultaneously regardless of dependencies
SPIRAL_DISPATCH_MODE="${SPIRAL_DISPATCH_MODE:-dag}"

# ── Capacity limit: skip Phase R when pending stories exceed this ─────────────
# Prevents flooding prd.json during aggressive non-stop runs
SPIRAL_MAX_PENDING=50

# ── Total story count assertion ceiling ───────────────────────────────────────
# Spiral has 264 total stories (243 done + 21 pending + room for research).
# Override the default of 200 to prevent abort on assert.
SPIRAL_MAX_TOTAL_STORIES=300

# ── Stale git lock-file cleanup (US-225) ─────────────────────────────────────
# Lock files in worktrees older than this many minutes are removed (if no live
# git process is found). 0 = disable automatic cleanup.
SPIRAL_LOCK_TIMEOUT_MINUTES=5

# ── Batch size: cap stories visible to ralph per iteration ────────────────
# Only the N highest-priority pending stories are included in the PRD slice
# passed to ralph. 0 = disabled (all pending stories visible, current behavior).
SPIRAL_STORY_BATCH_SIZE=20

# ── Phase S: Message Batches API validation (US-390) ──────────────────────
# Set to 1 to submit Phase S validation requests to the Anthropic Message
# Batches API (50% cost reduction vs sequential, async up to 10k stories).
# Requires ANTHROPIC_API_KEY. Single-story runs fall back to synchronous path.
# Batch summary is written to .spiral/_phase_s_batch.json.
SPIRAL_BATCH_VALIDATE="${SPIRAL_BATCH_VALIDATE:-0}"

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
SPIRAL_CONSECUTIVE_FAIL_ABORT="${SPIRAL_CONSECUTIVE_FAIL_ABORT:-3}"

# ── Cost ceiling: abort when cumulative API spend exceeds budget ──────────────
# Set to a USD amount (e.g., 50.0) to cap spending. Empty = disabled.
# SPIRAL_COST_CEILING=""

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
# SPIRAL_INCREMENTAL_VALIDATE=false
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
SPIRAL_SKIP_STORY_IDS="US-318,US-319,US-320,US-321,US-322,US-323,US-324,US-325,US-326,US-327,US-328,US-329,US-330,US-331,US-332,US-333,US-334,US-335"
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
SPIRAL_PRD_STREAM_THRESHOLD_KB=2048  # streaming jq path has a bug; keep on in-memory path until prd.json > 2MB

# ── Research output cache TTL (US-170) ───────────────────────────────────
# When set to a positive integer, Phase R is skipped entirely if
# _research_output.json already exists and is younger than this many hours.
# Also controls URL-level cache expiry in lib/research_cache.py.
# 0 = disabled (Phase R always runs). Default: 0.
# Example: SPIRAL_RESEARCH_CACHE_TTL_HOURS=6  # reuse research for up to 6h
# SPIRAL_RESEARCH_CACHE_TTL_HOURS=0

# ── Hierarchical summarization of Phase R output (US-254) ─────────────────
# When Phase R research output exceeds this token threshold, a summarization
# pass compresses story descriptions while preserving acceptance criteria,
# technical notes, and source URLs.  0 = disabled (no summarization).
# SPIRAL_RESEARCH_SUMMARY_THRESHOLD=4000
#
# Set to 1 to bypass summarization and pass full research to downstream phases.
# SPIRAL_USE_FULL_RESEARCH=0

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
SPIRAL_DECOMPOSE_ON_FIRST_FAIL="${SPIRAL_DECOMPOSE_ON_FIRST_FAIL:-false}"
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

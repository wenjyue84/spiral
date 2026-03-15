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

# Research phase uses sonnet by default (better synthesis than haiku)
SPIRAL_RESEARCH_MODEL="sonnet"

# ── Research focus prompt ────────────────────────────────────────────────────
# Guides Gemini + Claude in Phase R toward relevant context
SPIRAL_GEMINI_PROMPT="Focus on: achieving a delicate balance between token saving and quality of output code. Research token-efficient AI patterns, model routing strategies, dynamic complexity assessment, cost vs quality tradeoffs in LLM-powered coding agents, and best practices for setup wizards that educate users about configuration options. Provide actionable implementation context."

# ── Story prefix ─────────────────────────────────────────────────────────────
SPIRAL_STORY_PREFIX="US"

# ── Parallel worker settings ─────────────────────────────────────────────────
# Dynamic worker count (1-3) will be auto-selected once US-009 is implemented.
# Until then, leave unset and pass --ralph-workers on the command line.

# ── Capacity limit: skip Phase R when pending stories exceed this ─────────────
# Prevents flooding prd.json during aggressive non-stop runs
SPIRAL_MAX_PENDING=30

# ── Stale git lock-file cleanup (US-225) ─────────────────────────────────────
# Lock files in worktrees older than this many minutes are removed (if no live
# git process is found). 0 = disable automatic cleanup.
SPIRAL_LOCK_TIMEOUT_MINUTES=5

# ── Batch size: cap stories visible to ralph per iteration ────────────────
# Only the N highest-priority pending stories are included in the PRD slice
# passed to ralph. 0 = disabled (all pending stories visible, current behavior).
SPIRAL_STORY_BATCH_SIZE=20

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

# ── Manual story exclusion ─────────────────────────────────────────────────
# Comma-separated story IDs to permanently skip without penalty (no retry
# increment). Use for stories that are blocked externally or descoped mid-run.
# Example: SPIRAL_SKIP_STORY_IDS="US-042,US-099"
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
# SPIRAL_PRD_STREAM_THRESHOLD_KB=512

# ── Research output cache TTL (US-170) ───────────────────────────────────
# When set to a positive integer, Phase R is skipped entirely if
# _research_output.json already exists and is younger than this many hours.
# Also controls URL-level cache expiry in lib/research_cache.py.
# 0 = disabled (Phase R always runs). Default: 0.
# Example: SPIRAL_RESEARCH_CACHE_TTL_HOURS=6  # reuse research for up to 6h
# SPIRAL_RESEARCH_CACHE_TTL_HOURS=0

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

# ── Post-completion hook ───────────────────────────────────────────────────
# Shell command to run when ALL stories pass (check_done exits 0).
# Not run on iteration-limit exits, SIGINT, or errors.
# Example: SPIRAL_ON_COMPLETE='curl -s -X POST "$SLACK_WEBHOOK_URL" -d "{\"text\":\"Spiral done!\"}"'
# SPIRAL_ON_COMPLETE=""

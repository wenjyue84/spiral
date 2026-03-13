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

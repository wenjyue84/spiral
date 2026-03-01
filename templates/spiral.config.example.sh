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
# Default: $HOME/.ai/Skills/ralph/ralph.sh
# SPIRAL_RALPH="$HOME/.ai/Skills/ralph/ralph.sh"

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
# Default: $HOME/.ai/Skills/ralph/stream-formatter.mjs
# SPIRAL_STREAM_FMT="$HOME/.ai/Skills/ralph/stream-formatter.mjs"

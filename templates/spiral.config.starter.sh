#!/bin/bash
# spiral.config.sh — Starter config
# Edit the 3 REQUIRED vars below, then copy to your project root as spiral.config.sh.
# Everything else has safe defaults. For the full reference, see templates/spiral.config.example.sh.

# ── REQUIRED ─────────────────────────────────────────────────────────────────

# Full path to Python 3.13+ interpreter (used for story management scripts).
# On most systems "python3" works. On Windows with multiple versions, use the full path.
SPIRAL_PYTHON="python3"

# Test command that validates your project. Must exit 0 when all tests pass.
# Examples:
#   uv run pytest tests/ -v          (Python / pytest)
#   npm test                          (Node.js / Jest / Vitest)
#   cargo test                        (Rust)
#   bash tests/run.sh                 (custom script)
SPIRAL_VALIDATE_CMD="uv run pytest tests/ -v"

# Your project's story ID prefix (e.g. "US" → US-001, US-002; "FEAT" → FEAT-001)
SPIRAL_STORY_PREFIX="US"

# ── RECOMMENDED ──────────────────────────────────────────────────────────────

# Cap stories added per research phase (prevents prd.json from flooding).
SPIRAL_MAX_PENDING=50

# Stories shown to ralph per iteration (lower = more focused runs, less context used).
SPIRAL_STORY_BATCH_SIZE=10

# Stop if API spend exceeds this (USD). Uncomment to enable.
# SPIRAL_COST_CEILING="5.00"

# ── OPTIONAL ─────────────────────────────────────────────────────────────────

# Parallel ralph workers (1 = sequential, safer; 3+ = faster, uses more RAM).
# SPIRAL_RALPH_WORKERS=1

# Model routing: "auto" escalates haiku→sonnet→opus on retry.
# SPIRAL_MODEL_ROUTING="auto"

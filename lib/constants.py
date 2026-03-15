"""Shared constants for SPIRAL -- no imports from other lib modules."""
from __future__ import annotations

# Story priority ranking (lower = higher priority)
PRIORITY_RANK: dict[str, int] = {"critical": 0, "high": 1, "medium": 2, "low": 3}

# Anthropic 2025 pricing per million tokens (input / output)
PRICING: dict[str, dict[str, float]] = {
    "haiku": {"input": 0.80, "output": 4.00},
    "sonnet": {"input": 3.00, "output": 15.00},
    "opus": {"input": 15.00, "output": 75.00},
}

# Estimated cost per wall-clock hour by model tier
COST_PER_HOUR: dict[str, float] = {"haiku": 0.04, "sonnet": 0.24, "opus": 2.40}

# Cost projection defaults
DEFAULT_TOKENS_PER_STORY: int = 8000
TOKENS_PER_SEC_OUTPUT: int = 20
INPUT_OUTPUT_RATIO: float = 3.0
MIN_HISTORY_ROWS: int = 5

# Merge / story management
DEFAULT_MAX_NEW_STORIES: int = 50
OVERLAP_THRESHOLD: float = 0.6
EPIC_THRESHOLD: float = 0.45

# PRD locking
PRD_LOCK_TIMEOUT_S: float = 30.0
PRD_LOCK_POLL_INTERVAL_S: float = 0.1

# Calibration
CALIBRATION_ROLLING_WINDOW: int = 20

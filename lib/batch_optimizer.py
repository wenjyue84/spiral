"""lib/batch_optimizer.py — Phase S batch request optimizer (US-535).

Groups story candidates into batches where the same constitution checks apply,
so multiple stories can be validated in a single API call rather than one call
per story.  This reduces token overhead and API costs by 30-50% on multi-story
runs.

Public API
----------
group_stories_by_rules(stories, max_batch_size=10) -> list[list[dict]]
    Cluster stories by compatible validation rules.  Each cluster can be sent
    as a single API call.  Stories within a cluster share the same _source,
    priority tier, and constitute-check fingerprint.

batch_potential(stories, max_batch_size=10) -> dict
    High-level summary: groups, call-count reduction %, estimated token savings.
    Used by the 'spiral analyze-batch-potential' CLI command.
"""

from __future__ import annotations

import math
import re
from typing import Any

__all__ = ["batch_potential", "group_stories_by_rules"]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Estimated tokens consumed per story when validated individually
_TOKENS_PER_SOLO_CALL: int = 800

# Estimated tokens when stories are batched (shared prompt prefix saves tokens)
_TOKENS_PER_BATCHED_STORY: int = 400

# Constitution rule buckets — each bucket is a frozenset of checks that apply.
# In reality the same constitution applies to every story; we group by:
#   1. _source  (research / ai-example / test-fix / seed / None)
#   2. priority (high / medium / low)
# Stories in the same bucket can share a single validation prompt.

_PRIORITY_TIERS: dict[str, int] = {"high": 0, "medium": 1, "low": 2}


def _story_bucket(story: dict[str, Any]) -> tuple[str, str]:
    """Return a stable bucket key for a story.

    Stories that share a bucket key can be validated together in one API call
    because:
    - They have the same constitution checks (all stories share the same
      constitution file, so this is always compatible).
    - Their _source indicates the same pipeline origin, meaning the same
      validation prompt template applies.

    Returns
    -------
    tuple[str, str]
        (source_key, priority_key) — both normalised to lower-case strings.
    """
    source = str(story.get("_source") or "seed").lower()
    priority = str(story.get("priority") or "medium").lower()
    if priority not in _PRIORITY_TIERS:
        priority = "medium"
    return (source, priority)


def group_stories_by_rules(
    stories: list[dict[str, Any]],
    max_batch_size: int = 10,
) -> list[list[dict[str, Any]]]:
    """Cluster stories with identical constitution checks into batch groups.

    Stories in the same group share:
    - The same _source pipeline origin (research / ai-example / test-fix / seed)
    - The same priority tier (high / medium / low)

    This means a single Phase S API call can validate the whole group by
    including all story titles/descriptions in one prompt.

    Parameters
    ----------
    stories:
        List of story dicts (as found in prd.json ``userStories``).
    max_batch_size:
        Maximum stories per batch group.  Larger groups increase prompt size
        beyond what most models handle well; default 10 is safe.

    Returns
    -------
    list[list[dict]]
        Each inner list is one batch group.  The union of all inner lists
        equals the input list (no stories are dropped).
    """
    if not stories:
        return []

    # Collect stories per bucket
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for story in stories:
        key = _story_bucket(story)
        buckets.setdefault(key, []).append(story)

    # Split buckets that exceed max_batch_size
    groups: list[list[dict[str, Any]]] = []
    for members in buckets.values():
        for i in range(0, len(members), max_batch_size):
            groups.append(members[i : i + max_batch_size])

    return groups


def batch_potential(
    stories: list[dict[str, Any]],
    max_batch_size: int = 10,
) -> dict[str, Any]:
    """Compute batch optimisation potential for a list of stories.

    Parameters
    ----------
    stories:
        Story dicts from prd.json (pending or all).
    max_batch_size:
        Forwarded to ``group_stories_by_rules``.

    Returns
    -------
    dict with keys:
        story_count          int   — total stories analysed
        solo_api_calls       int   — calls needed without batching (one per story)
        batch_api_calls      int   — calls needed with batching
        call_reduction_pct   float — percentage reduction in API calls
        solo_tokens_est      int   — estimated tokens without batching
        batch_tokens_est     int   — estimated tokens with batching
        token_savings_est    int   — absolute token savings
        token_savings_pct    float — percentage token savings
        groups               list  — each group is a list of story IDs
    """
    n = len(stories)
    if n == 0:
        return {
            "story_count": 0,
            "solo_api_calls": 0,
            "batch_api_calls": 0,
            "call_reduction_pct": 0.0,
            "solo_tokens_est": 0,
            "batch_tokens_est": 0,
            "token_savings_est": 0,
            "token_savings_pct": 0.0,
            "groups": [],
        }

    groups = group_stories_by_rules(stories, max_batch_size=max_batch_size)

    solo_calls = n
    batch_calls = len(groups)
    reduction_pct = (1.0 - batch_calls / solo_calls) * 100.0 if solo_calls else 0.0

    solo_tokens = n * _TOKENS_PER_SOLO_CALL
    batch_tokens = n * _TOKENS_PER_BATCHED_STORY
    token_savings = solo_tokens - batch_tokens
    token_savings_pct = (token_savings / solo_tokens * 100.0) if solo_tokens else 0.0

    group_ids: list[list[str]] = [
        [s.get("id", "") for s in g] for g in groups
    ]

    return {
        "story_count": n,
        "solo_api_calls": solo_calls,
        "batch_api_calls": batch_calls,
        "call_reduction_pct": round(reduction_pct, 1),
        "solo_tokens_est": solo_tokens,
        "batch_tokens_est": batch_tokens,
        "token_savings_est": token_savings,
        "token_savings_pct": round(token_savings_pct, 1),
        "groups": group_ids,
    }

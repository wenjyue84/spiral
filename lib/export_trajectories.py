"""lib/export_trajectories.py — Export SPIRAL results as JSONL for LLM fine-tuning / RL training.

Emits one JSON line per story attempt in OpenAI SFT / trl shape:
  {messages: [{role, content}, ...], reward: float, meta: {story_id, model, tokens, duration}}

Usage:
  uv run python -m lib.export_trajectories --out trajectories.jsonl
  uv run python -m lib.export_trajectories --out out.jsonl --tsv results.tsv --logs-dir .spiral
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Any

# Reward values
REWARD_PASS = 1.0
REWARD_FAIL = -1.0

# Map results.tsv status to reward
_STATUS_REWARD: dict[str, float] = {
    "keep": REWARD_PASS,
    "pass": REWARD_PASS,
    "passed": REWARD_PASS,
    "reject": REWARD_FAIL,
    "fail": REWARD_FAIL,
    "failed": REWARD_FAIL,
    "skip": REWARD_FAIL,
}


def load_results_tsv(tsv_path: str) -> list[dict[str, str]]:
    """Read results.tsv; return list of row dicts. Skips header."""
    if not os.path.isfile(tsv_path):
        return []
    with open(tsv_path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        return [row for row in reader if row.get("story_id")]


def _status_to_reward(status: str) -> float:
    """Convert results.tsv status string to reward float in [-1, 1]."""
    return _STATUS_REWARD.get(status.lower().strip(), REWARD_FAIL)


def _safe_int(val: str, default: int = 0) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _safe_float(val: str, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def build_trajectory(row: dict[str, str]) -> dict[str, Any]:
    """Build a single trajectory dict from one results.tsv row.

    Messages are synthetic but structurally valid for SFT/RL use:
    - system: role description
    - user: the story implementation request
    - assistant: the outcome summary
    """
    story_id = row.get("story_id", "")
    story_title = row.get("story_title", "")
    status = row.get("status", "")
    model = row.get("model", "")
    duration = _safe_float(row.get("duration_sec", "0"))
    cache_read = _safe_int(row.get("cache_read_tokens", "0"))
    cache_create = _safe_int(row.get("cache_creation_tokens", "0"))
    total_tokens = cache_read + cache_create
    retry_num = _safe_int(row.get("retry_num", "0"))
    spiral_iter = row.get("spiral_iter", "")

    reward = _status_to_reward(status)

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are Ralph, an autonomous implementation agent in the SPIRAL loop. "
                "Your task is to implement the assigned user story from prd.json, "
                "run quality checks, and commit the result."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Implement story {story_id}: {story_title}. "
                f"This is attempt {retry_num + 1} (SPIRAL iteration {spiral_iter})."
            ),
        },
        {
            "role": "assistant",
            "content": (
                f"Story {story_id} implementation {'succeeded' if reward > 0 else 'failed'}. "
                f"Status: {status}. Model: {model}. Duration: {duration:.1f}s."
            ),
        },
    ]

    meta: dict[str, Any] = {
        "story_id": story_id,
        "model": model,
        "tokens": total_tokens,
        "duration": duration,
        "retry_num": retry_num,
        "spiral_iter": spiral_iter,
        "status": status,
        "timestamp": row.get("timestamp", ""),
    }

    return {"messages": messages, "reward": reward, "meta": meta}


def validate_trajectory(obj: dict[str, Any]) -> bool:
    """Return True if trajectory passes schema check."""
    if not isinstance(obj.get("messages"), list) or not obj["messages"]:
        return False
    for msg in obj["messages"]:
        if not isinstance(msg.get("role"), str) or not isinstance(msg.get("content"), str):
            return False
    reward = obj.get("reward")
    if not isinstance(reward, (int, float)):
        return False
    if not (-1.0 <= float(reward) <= 1.0):
        return False
    return True


def export_trajectories(
    tsv_path: str,
    out_path: str,
) -> int:
    """Export trajectories to JSONL. Returns number of records written."""
    rows = load_results_tsv(tsv_path)
    written = 0
    with open(out_path, "w", encoding="utf-8") as fh:
        for row in rows:
            traj = build_trajectory(row)
            if validate_trajectory(traj):
                fh.write(json.dumps(traj) + "\n")
                written += 1
    return written


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Export SPIRAL results.tsv to JSONL for LLM fine-tuning / RL training."
    )
    parser.add_argument(
        "--out",
        default="trajectories.jsonl",
        help="Output JSONL file path (default: trajectories.jsonl)",
    )
    parser.add_argument(
        "--tsv",
        default="results.tsv",
        help="Path to results.tsv (default: results.tsv)",
    )
    args = parser.parse_args(argv)

    n = export_trajectories(tsv_path=args.tsv, out_path=args.out)
    print(f"Exported {n} trajectories → {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()

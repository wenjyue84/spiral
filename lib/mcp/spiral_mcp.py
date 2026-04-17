#!/usr/bin/env python3
"""
SPIRAL MCP Server — exposes read/write tools for Claude Code integration.

Run:
  python -m lib.mcp.spiral_mcp

Tools:
  spiral_status()               — current iteration + phase from _checkpoint.json
  spiral_stories(filter)        — stories from prd.json, optional filter
  spiral_recent_failures(n)     — last n failure rows from results.tsv
  spiral_iteration(n)           — iteration-scoped rows from results.tsv
  spiral_add_story(body,source) — validate + append story to prd.json
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import fastmcp

# ── Resolve repo root (two levels up from lib/mcp/) ────────────────────────
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
# Do NOT add lib/ to sys.path — it would shadow the real 'mcp' SDK package

CHECKPOINT = _ROOT / ".spiral" / "_checkpoint.json"
RESULTS_TSV = _ROOT / "results.tsv"
PRD_JSON = _ROOT / "prd.json"

mcp = fastmcp.FastMCP("spiral")


# ── Helpers ─────────────────────────────────────────────────────────────────


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception:
        return None


def _read_tsv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh, delimiter="\t"))
    except Exception:
        return []


# ── Tools ───────────────────────────────────────────────────────────────────


@mcp.tool()
def spiral_status() -> dict[str, Any]:
    """Return current SPIRAL iteration, phase, and run metadata from _checkpoint.json."""
    data = _read_json(CHECKPOINT)
    if data is None:
        return {"error": "checkpoint not found", "path": str(CHECKPOINT)}
    return data


@mcp.tool()
def spiral_stories(filter: str = "") -> list[dict[str, Any]]:
    """
    Return stories from prd.json.

    filter: optional substring matched against story id, title, or status.
            Pass empty string to return all stories.
    """
    prd = _read_json(PRD_JSON)
    if prd is None:
        return [{"error": "prd.json not found"}]
    stories: list[dict[str, Any]] = prd.get("userStories", [])
    if filter:
        fl = filter.lower()
        stories = [
            s
            for s in stories
            if fl in s.get("id", "").lower()
            or fl in s.get("title", "").lower()
            or fl in str(s.get("passes", "")).lower()
            or fl in s.get("_source", "").lower()
        ]
    return stories


@mcp.tool()
def spiral_recent_failures(n: int = 10) -> list[dict[str, str]]:
    """
    Return the last n rows from results.tsv where status is not 'pass'.

    n: max number of failure rows to return (default 10).
    """
    rows = _read_tsv_rows(RESULTS_TSV)
    failures = [r for r in rows if r.get("status", "").lower() not in ("pass", "")]
    return failures[-n:] if n > 0 else failures


@mcp.tool()
def spiral_iteration(n: int) -> list[dict[str, str]]:
    """
    Return all results.tsv rows for a given spiral iteration number n.

    n: iteration number (spiral_iter column).
    """
    rows = _read_tsv_rows(RESULTS_TSV)
    return [r for r in rows if r.get("spiral_iter", "") == str(n)]


@mcp.tool()
def spiral_add_story(body: dict[str, Any], source: str = "seed") -> dict[str, Any]:
    """
    Validate and append a new story to prd.json.

    body:   story dict with at minimum 'id', 'title', 'priority', 'description', 'acceptanceCriteria'.
    source: _source tag — e.g. 'seed', 'ai-example', 'research' (default 'seed').

    Returns {"ok": true, "id": "<story_id>"} on success or {"error": "<message>"} on failure.
    """
    # Lazy-load prd_schema directly from file (avoids sys.path manipulation)
    import importlib.util
    import types

    prd_schema_path = _ROOT / "lib" / "prd" / "prd_schema.py"
    spec = importlib.util.spec_from_file_location("prd_schema", prd_schema_path)
    if spec is None or spec.loader is None:
        return {"error": "could not load prd_schema"}
    mod: types.ModuleType = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    validate_prd = mod.validate_prd

    # Ensure required story fields have defaults
    story: dict[str, Any] = {
        "passes": False,
        "estimatedComplexity": "medium",
        **body,
        "_source": source,
    }
    if "id" not in story:
        story["id"] = f"US-{uuid.uuid4().hex[:4].upper()}"

    prd = _read_json(PRD_JSON)
    if prd is None:
        return {"error": "prd.json not found or unreadable"}

    # Check for duplicate ID
    existing_ids = {s.get("id") for s in prd.get("userStories", [])}
    if story["id"] in existing_ids:
        return {"error": f"story id {story['id']} already exists"}

    # Validate full PRD with new story
    candidate = dict(prd)
    candidate["userStories"] = list(prd.get("userStories", [])) + [story]
    errors = validate_prd(candidate)
    if errors:
        return {"error": "; ".join(errors[:3])}

    # Atomic write via temp file
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=PRD_JSON.parent,
        suffix=".tmp",
        delete=False,
    ) as tmp:
        json.dump(candidate, tmp, indent=2, ensure_ascii=False)
        tmp_path = tmp.name

    os.replace(tmp_path, str(PRD_JSON))
    return {"ok": True, "id": story["id"]}


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()

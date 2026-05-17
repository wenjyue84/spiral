#!/usr/bin/env python3
"""Parse spiral_events.jsonl, results.tsv, and worker logs into unified trace format."""

import json
import os
from datetime import datetime
from typing import Any


def read_spiral_events(spiral_events_path: str) -> list[dict[str, Any]]:
    """Read spiral_events.jsonl and extract phase/timing events."""
    events: list[dict[str, Any]] = []
    if not os.path.exists(spiral_events_path):
        return events
    try:
        with open(spiral_events_path, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    events.append(data)
                except json.JSONDecodeError:
                    continue
    except Exception:
        pass
    return events


def read_results_tsv(results_path: str) -> list[dict[str, Any]]:
    """Parse results.tsv into list of dicts with proper typing."""
    rows: list[dict[str, Any]] = []
    if not os.path.exists(results_path):
        return rows
    try:
        with open(results_path, encoding="utf-8") as f:
            header: list[str] = []
            for i, line in enumerate(f):
                if i == 0:
                    header = line.strip().split("\t")
                else:
                    parts = line.strip().split("\t")
                    row: dict[str, Any] = {}
                    for j, col in enumerate(header):
                        val = parts[j] if j < len(parts) else ""
                        try:
                            if col in ("spiral_iter", "ralph_iter", "retry_num"):
                                row[col] = int(val) if val else 0
                            elif col in ("duration_sec", "wall_seconds", "user_cpu_s", "sys_cpu_s", "peak_rss_kb"):
                                row[col] = float(val) if val else 0.0
                            else:
                                row[col] = val
                        except (ValueError, IndexError):
                            row[col] = val
                    rows.append(row)
    except Exception:
        pass
    return rows


def read_worker_logs(log_dir: str) -> list[dict[str, Any]]:
    """Parse .spiral/worker-N.log files for worker timing events."""
    entries: list[dict[str, Any]] = []
    if not os.path.isdir(log_dir):
        return entries
    try:
        for fname in os.listdir(log_dir):
            if not fname.startswith("worker-") or not fname.endswith(".log"):
                continue
            worker_id = fname.replace("worker-", "").replace(".log", "")
            fpath = os.path.join(log_dir, fname)
            try:
                with open(fpath, encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if "start_unix_ms" in line or "duration_ms" in line:
                            try:
                                entry = json.loads(line)
                                entry["worker_id"] = worker_id
                                entries.append(entry)
                            except json.JSONDecodeError:
                                pass
            except Exception:
                pass
    except Exception:
        pass
    return entries


def unify_trace_data(
    spiral_events: list[dict[str, Any]],
    results_tsv: list[dict[str, Any]],
    worker_logs: list[dict[str, Any]],
    from_iteration: int | None = None,
    to_iteration: int | None = None,
    filter_phase: str | None = None,
) -> list[dict[str, Any]]:
    """Merge spiral_events, results.tsv, and worker logs into unified trace entries."""
    unified: list[dict[str, Any]] = []

    # Add entries from results.tsv
    for row in results_tsv:
        it = row.get("spiral_iter", 0)
        if from_iteration and it < from_iteration:
            continue
        if to_iteration and it > to_iteration:
            continue

        try:
            ts_raw = row.get("timestamp", "")
            start_unix_ms = (
                int(datetime.fromisoformat(ts_raw.replace("Z", "+00:00")).timestamp() * 1000) if ts_raw else 0
            )
        except (ValueError, AttributeError):
            start_unix_ms = 0

        entry = {
            "iteration": it,
            "phase": None,
            "worker_id": None,
            "start_unix_ms": start_unix_ms,
            "duration_ms": int((row.get("duration_sec", 0) or 0) * 1000),
            "status": row.get("status", "unknown"),
            "model": row.get("model", ""),
            "tokens_in": 0,
            "tokens_out": 0,
            "api_latency_ms": 0,
            "escalation_count": row.get("retry_num", 0),
            "error_category": None,
            "story_id": row.get("story_id", ""),
        }
        if not filter_phase:
            unified.append(entry)

    # Add entries from worker logs (ensure they have iteration field)
    for wlog in worker_logs:
        phase = wlog.get("phase")
        if filter_phase and phase != filter_phase:
            continue
        wlog_iter = wlog.get("iteration", 0)
        # Apply iteration filters to worker logs
        if from_iteration and wlog_iter < from_iteration:
            continue
        if to_iteration and wlog_iter > to_iteration:
            continue
        # Ensure worker log entries have all required fields
        entry = {
            "iteration": wlog_iter,
            "phase": phase,
            "worker_id": wlog.get("worker_id"),
            "start_unix_ms": wlog.get("start_unix_ms", 0),
            "duration_ms": wlog.get("duration_ms", 0),
            "status": wlog.get("status", "unknown"),
            "model": wlog.get("model", ""),
            "tokens_in": wlog.get("tokens_in", 0),
            "tokens_out": wlog.get("tokens_out", 0),
            "api_latency_ms": wlog.get("api_latency_ms", 0),
            "escalation_count": wlog.get("escalation_count", 0),
            "error_category": wlog.get("error_category"),
        }
        unified.append(entry)

    unified.sort(key=lambda x: x.get("start_unix_ms", 0))
    return unified

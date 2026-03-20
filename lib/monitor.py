"""monitor.py — Unified monitoring snapshot for SPIRAL progress checks.

Gathers PRD status, delta comparison, run health, UI health, and diagnostics
in one shot. Returns a JSON-serializable dict for the ``main.py monitor``
subcommand.

# TODO: _load_prd, _classify_stories, _load_retry_counts, _load_checkpoint
# are duplicated from main.py.  Extract to a shared ``lib/loaders.py`` once
# the codebase is ready for that refactor.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ── Data loaders (duplicated from main.py — see module docstring) ────────────


def _load_prd(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("userStories", [])
    except (json.JSONDecodeError, OSError):
        return []


def _load_retry_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return {k: int(v) for k, v in raw.items()}
    except (json.JSONDecodeError, ValueError, OSError):
        return {}


def _classify_stories(
    stories: list[dict[str, Any]],
    retry_counts: dict[str, int],
) -> dict[str, list[dict[str, Any]]]:
    """Split stories into passed / in_progress / skipped / dlq / pending."""
    buckets: dict[str, list[dict[str, Any]]] = {
        "passed": [],
        "in_progress": [],
        "skipped": [],
        "dlq": [],
        "pending": [],
    }
    for s in stories:
        sid = s.get("id", "")
        if s.get("passes"):
            buckets["passed"].append(s)
        elif s.get("_dlq"):
            buckets["dlq"].append(s)
        elif s.get("_skipped"):
            buckets["skipped"].append(s)
        elif retry_counts.get(sid, 0) > 0:
            buckets["in_progress"].append(s)
        else:
            buckets["pending"].append(s)
    return buckets


def _load_checkpoint(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# ── State persistence ────────────────────────────────────────────────────────


def _load_state(state_path: Path) -> dict[str, Any]:
    """Read .spiral/_monitor_state.json (previous pass count + timestamp)."""
    if not state_path.exists():
        return {}
    try:
        with open(state_path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state_path: Path, passes: int, ts: str) -> None:
    """Write current snapshot for next comparison."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"passed_count": passes, "timestamp": ts}
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ── Check functions ──────────────────────────────────────────────────────────


def _check_stories(project_root: Path) -> dict[str, Any]:
    """Load prd.json + retry-counts.json, classify stories, return counts."""
    prd_path = project_root / "prd.json"
    retry_path = project_root / "retry-counts.json"
    checkpoint_path = project_root / ".spiral" / "_checkpoint.json"

    stories = _load_prd(prd_path)
    retry_counts = _load_retry_counts(retry_path)
    checkpoint = _load_checkpoint(checkpoint_path)
    buckets = _classify_stories(stories, retry_counts)

    total = len(stories)
    passed = len(buckets["passed"])
    return {
        "run_id": checkpoint.get("run_id", ""),
        "iteration": checkpoint.get("iter", 0),
        "total": total,
        "passed": passed,
        "pending": len(buckets["pending"]),
        "in_progress": len(buckets["in_progress"]),
        "skipped": len(buckets["skipped"]),
        "failed": len(buckets["dlq"]),
        "pass_pct": round(passed / total * 100, 1) if total > 0 else 0.0,
    }


def _check_delta(current_passes: int, state_path: Path) -> dict[str, Any]:
    """Compare current vs saved, compute new_passed, set stalled flag."""
    state = _load_state(state_path)
    previous = state.get("passed_count", 0)
    last_check = state.get("timestamp", "")
    new_passed = current_passes - previous
    return {
        "previous": previous,
        "current": current_passes,
        "new_passed": max(new_passed, 0),
        "stalled": new_passed <= 0 and previous > 0,
        "last_check": last_check,
    }


def _check_run_health(scratch_dir: Path) -> dict[str, Any]:
    """Stat _last_run.log mtime, flag if >300s old."""
    log_path = scratch_dir / "_last_run.log"
    if not log_path.exists():
        return {
            "running": False,
            "log_age_secs": -1,
            "log_path": str(log_path),
        }
    try:
        mtime = log_path.stat().st_mtime
        age = time.time() - mtime
        return {
            "running": age < 300,
            "log_age_secs": round(age),
            "log_path": str(log_path),
        }
    except OSError:
        return {
            "running": False,
            "log_age_secs": -1,
            "log_path": str(log_path),
        }


def _check_ui(port: int) -> dict[str, Any]:
    """HTTP GET localhost:{port}, return reachable + status_code + latency."""
    url = f"http://localhost:{port}/"
    try:
        start = time.monotonic()
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            elapsed = time.monotonic() - start
            return {
                "reachable": True,
                "status_code": resp.status,
                "response_ms": round(elapsed * 1000),
            }
    except urllib.error.HTTPError as e:
        elapsed = time.monotonic() - start
        return {
            "reachable": True,
            "status_code": e.code,
            "response_ms": round(elapsed * 1000),
        }
    except (urllib.error.URLError, OSError, TimeoutError):
        return {
            "reachable": False,
            "status_code": 0,
            "response_ms": 0,
        }


def _diagnose(project_root: Path, scratch_dir: Path) -> list[dict[str, Any]]:
    """Run all diagnostic checks, return diagnostics array."""
    diags: list[dict[str, Any]] = []

    # 1. Stale lock files
    lock_files = [
        project_root / "prd.json.lock",
        project_root / ".git" / "index.lock",
    ]
    for lf in lock_files:
        if lf.exists():
            # Try to read PID from lock file
            pid_info = ""
            try:
                content = lf.read_text(encoding="utf-8", errors="ignore").strip()
                if content.isdigit():
                    pid = int(content)
                    # Check if PID is alive
                    try:
                        os.kill(pid, 0)
                        pid_info = f" (PID {pid} is alive)"
                    except OSError:
                        pid_info = f" (PID {pid} is dead)"
                else:
                    pid_info = ""
            except OSError:
                pass
            diags.append({
                "severity": "warning",
                "check": "stale_locks",
                "message": f"Lock file found: {lf.name}{pid_info}",
                "remediation": f"Delete {lf}" if "dead" in pid_info or not pid_info else f"Wait for PID to finish",
            })

    # 2. Recent crash logs
    crash_dir = scratch_dir / "crashes"
    if crash_dir.is_dir():
        crashes = sorted(crash_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        if crashes:
            latest = crashes[0]
            age_secs = time.time() - latest.stat().st_mtime
            if age_secs < 3600:  # Crashed in last hour
                diags.append({
                    "severity": "error",
                    "check": "recent_crash",
                    "message": f"Crash log found: {latest.name} ({round(age_secs)}s ago)",
                    "remediation": f"Read {latest} for error details",
                })

    # 3. Corrupt story titles (title == id)
    prd_path = project_root / "prd.json"
    stories = _load_prd(prd_path)
    corrupt_count = sum(1 for s in stories if s.get("title") == s.get("id") and not s.get("passes"))
    if corrupt_count > 0:
        diags.append({
            "severity": "warning",
            "check": "corrupt_titles",
            "message": f"{corrupt_count} pending stories have title == id",
            "remediation": "Manually fix story titles in prd.json",
        })

    # 4. Uncommitted config changes
    config_path = project_root / "spiral.config.sh"
    if config_path.exists():
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "spiral.config.sh"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "spiral.config.sh" in result.stdout:
                diags.append({
                    "severity": "info",
                    "check": "uncommitted_config",
                    "message": "spiral.config.sh has uncommitted changes",
                    "remediation": "Commit config or auto-stash will keep reverting it",
                })
        except (subprocess.TimeoutExpired, OSError):
            pass

    return diags


def _needs_attention(
    delta: dict[str, Any],
    run_health: dict[str, Any],
    ui_health: dict[str, Any],
    diagnostics: list[dict[str, Any]],
) -> bool:
    """True if: stalled, not running, UI down, or any error-severity diagnostic."""
    if delta.get("stalled"):
        return True
    if not run_health.get("running"):
        return True
    if not ui_health.get("reachable"):
        return True
    if any(d.get("severity") == "error" for d in diagnostics):
        return True
    return False


# ── Public entry point ───────────────────────────────────────────────────────


def run_monitor(*, project_root: Path, ui_port: int = 5299) -> dict[str, Any]:
    """Gather all monitoring data in one shot. Never raises."""
    scratch_dir = project_root / ".spiral"
    state_path = scratch_dir / "_monitor_state.json"
    now = datetime.now(timezone.utc).isoformat()

    try:
        status = _check_stories(project_root)
    except Exception:
        status = {
            "run_id": "", "iteration": 0, "total": 0, "passed": 0,
            "pending": 0, "in_progress": 0, "skipped": 0, "failed": 0,
            "pass_pct": 0.0,
        }

    try:
        delta = _check_delta(status["passed"], state_path)
    except Exception:
        delta = {
            "previous": 0, "current": status.get("passed", 0),
            "new_passed": 0, "stalled": False, "last_check": "",
        }

    try:
        run_health = _check_run_health(scratch_dir)
    except Exception:
        run_health = {"running": False, "log_age_secs": -1, "log_path": ""}

    try:
        ui_health = _check_ui(ui_port)
    except Exception:
        ui_health = {"reachable": False, "status_code": 0, "response_ms": 0}

    try:
        diagnostics = _diagnose(project_root, scratch_dir)
    except Exception:
        diagnostics = []

    needs_attn = _needs_attention(delta, run_health, ui_health, diagnostics)

    # Save state for next comparison
    try:
        _save_state(state_path, status["passed"], now)
    except Exception:
        pass

    return {
        "schema": "monitor-v1",
        "timestamp": now,
        "needs_attention": needs_attn,
        "status": status,
        "delta": delta,
        "run_health": run_health,
        "ui_health": ui_health,
        "diagnostics": diagnostics,
    }

"""worker_oom_guard.py -- OOM guard for Ralph worker subprocesses.

Monitors subprocess memory usage against SPIRAL_MAX_WORKER_MEMORY.
Kills the subprocess and logs OOM_GUARD_TRIGGERED to results.tsv when
memory exceeds the configured limit.
"""

import csv
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil


def parse_memory_limit(limit_str: str) -> int:
    """Parse memory limit string to bytes. Accepts 512MB, 256M, 1GB, 1G, raw int."""
    s = limit_str.strip().upper()
    for suffix, mult in (
        ("GB", 1 << 30),
        ("MB", 1 << 20),
        ("KB", 1 << 10),
        ("G", 1 << 30),
        ("M", 1 << 20),
        ("K", 1 << 10),
    ):
        if s.endswith(suffix):
            return int(s[: -len(suffix)]) * mult
    return int(s)


def get_process_memory_bytes(pid: int) -> int:
    """Return RSS memory of process in bytes. Returns 0 if process not found."""
    try:
        return int(psutil.Process(pid).memory_info().rss)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return 0


def log_oom_event(tsv_path: str, story_id: str) -> None:
    """Append an OOM_GUARD_TRIGGERED row to the given TSV file."""
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "story_id": story_id,
        "memory_event": "OOM_GUARD_TRIGGERED",
    }
    path = Path(tsv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(row.keys()),
            delimiter="	",
            extrasaction="ignore",
        )
        if write_header:
            writer.writeheader()
        writer.writerow(row)


class OomGuard:
    """Monitor a subprocess and kill it if memory exceeds limit."""

    def __init__(self, limit_bytes: int, tsv_path: str) -> None:
        self.limit_bytes = limit_bytes
        self.tsv_path = tsv_path

    def check_and_enforce(
        self, proc: "subprocess.Popen[bytes]", story_id: str
    ) -> bool:
        """Check memory; kill proc if over limit, log event. Returns True if killed."""
        used = get_process_memory_bytes(proc.pid)
        if used > self.limit_bytes:
            try:
                proc.kill()
            except OSError:
                pass
            log_oom_event(self.tsv_path, story_id)
            return True
        return False

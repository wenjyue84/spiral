"""Integration tests for worker OOM guard (US-1079).

Verifies that OomGuard detects memory-hungry subprocesses, kills them,
logs OOM_GUARD_TRIGGERED to results.tsv, and that the caller continues
to process subsequent work after the OOM event.
"""

import csv
import subprocess
import sys
import time
from pathlib import Path

from lib.worker_oom_guard import OomGuard, log_oom_event, parse_memory_limit

# -- parse_memory_limit --------------------------------------------------------


def test_parse_mb() -> None:
    assert parse_memory_limit("512MB") == 512 * (1 << 20)


def test_parse_m_suffix() -> None:
    assert parse_memory_limit("256M") == 256 * (1 << 20)


def test_parse_gb() -> None:
    assert parse_memory_limit("1GB") == 1 << 30


def test_parse_g_suffix() -> None:
    assert parse_memory_limit("2G") == 2 * (1 << 30)


def test_parse_plain_bytes() -> None:
    assert parse_memory_limit("1024") == 1024


# -- log_oom_event -------------------------------------------------------------


def test_log_creates_tsv(tmp_path: Path) -> None:
    tsv = str(tmp_path / "results.tsv")
    log_oom_event(tsv, "US-1079")
    assert Path(tsv).exists()


def test_log_writes_oom_columns(tmp_path: Path) -> None:
    tsv = str(tmp_path / "results.tsv")
    log_oom_event(tsv, "US-1079")
    with open(tsv) as f:
        rows = list(csv.DictReader(f, delimiter="	"))
    assert len(rows) == 1
    assert rows[0]["story_id"] == "US-1079"
    assert rows[0]["memory_event"] == "OOM_GUARD_TRIGGERED"


def test_log_appends_multiple_events(tmp_path: Path) -> None:
    tsv = str(tmp_path / "results.tsv")
    log_oom_event(tsv, "US-1079")
    log_oom_event(tsv, "US-1080")
    with open(tsv) as f:
        rows = list(csv.DictReader(f, delimiter="	"))
    assert len(rows) == 2
    assert rows[1]["story_id"] == "US-1080"


def test_log_creates_parent_dirs(tmp_path: Path) -> None:
    tsv = str(tmp_path / "sub" / "dir" / "results.tsv")
    log_oom_event(tsv, "US-1079")
    assert Path(tsv).exists()


# -- OomGuard integration ------------------------------------------------------


def _spawn_mem_proc(mb: int) -> "subprocess.Popen[bytes]":
    """Start a subprocess that allocates mb MB and sleeps."""
    code = f"import time; x = bytearray({mb} * 1024 * 1024); time.sleep(30)"
    return subprocess.Popen([sys.executable, "-c", code])


def test_oom_guard_kills_over_limit_and_logs(tmp_path: Path) -> None:
    """AC1 + AC2: guard kills subprocess exceeding threshold and logs to TSV."""
    tsv = str(tmp_path / "results.tsv")
    guard = OomGuard(limit_bytes=1024 * 1024, tsv_path=tsv)

    proc = _spawn_mem_proc(mb=10)
    killed = False
    try:
        for _ in range(30):
            time.sleep(0.2)
            if guard.check_and_enforce(proc, "US-1079"):
                killed = True
                break
        assert killed, "OomGuard should kill subprocess over memory limit"
        proc.wait(timeout=5)
        assert proc.returncode is not None
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    with open(tsv) as f:
        rows = list(csv.DictReader(f, delimiter="	"))
    assert any(r["memory_event"] == "OOM_GUARD_TRIGGERED" for r in rows), (
        "OOM_GUARD_TRIGGERED must be logged in memory_event column"
    )


def test_guard_does_not_kill_under_limit(tmp_path: Path) -> None:
    """Process under limit is not killed and nothing is logged."""
    tsv = str(tmp_path / "results.tsv")
    guard = OomGuard(limit_bytes=10 * (1 << 30), tsv_path=tsv)
    proc = _spawn_mem_proc(mb=10)
    try:
        time.sleep(0.4)
        killed = guard.check_and_enforce(proc, "US-1079")
        assert not killed
        assert not Path(tsv).exists(), "No event should be logged for under-limit process"
    finally:
        proc.kill()
        proc.wait()


def test_caller_continues_after_oom_event(tmp_path: Path) -> None:
    """AC3: caller can run a second task normally after OOM guard fires."""
    tsv = str(tmp_path / "results.tsv")
    guard = OomGuard(limit_bytes=1024 * 1024, tsv_path=tsv)

    proc1 = _spawn_mem_proc(mb=10)
    try:
        for _ in range(30):
            time.sleep(0.2)
            if guard.check_and_enforce(proc1, "US-1079"):
                break
    finally:
        if proc1.poll() is None:
            proc1.kill()
        proc1.wait()

    result = subprocess.run(
        [sys.executable, "-c", "print('alive')"],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert b"alive" in result.stdout

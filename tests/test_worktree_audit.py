"""Tests for `spiral worktree audit` command (US-231)."""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

# Allow importing main.py from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

MAIN_PY = str(Path(__file__).parent.parent / "main.py")


def run_audit(*extra_args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run `python main.py worktree audit` and return the CompletedProcess."""
    cmd = [sys.executable, MAIN_PY, "worktree", "audit", *extra_args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd or str(Path(MAIN_PY).parent),
    )


def _init_git_repo(tmp_path: Path) -> None:
    """Initialise a minimal git repo suitable for worktree tests."""
    subprocess.run(["git", "init", "-b", "main"], cwd=str(tmp_path), check=True,
                   capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"],
                   cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"],
                   cwd=str(tmp_path), check=True, capture_output=True)
    (tmp_path / "README.md").write_text("hello")
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), check=True,
                   capture_output=True)


# ── CLI smoke tests (run against real repo) ───────────────────────────────────

class TestWorktreeAuditCLI:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, MAIN_PY, "worktree", "audit", "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "audit" in result.stdout.lower()

    def test_json_flag_produces_valid_json(self):
        result = run_audit("--json")
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(f"--json output is not valid JSON: {exc}\nOutput: {result.stdout!r}")
        assert "anomalies" in data
        assert "total" in data
        assert "clean" in data

    def test_json_output_schema(self):
        result = run_audit("--json")
        data = json.loads(result.stdout)
        assert isinstance(data["anomalies"], list)
        assert isinstance(data["total"], int)
        assert isinstance(data["clean"], bool)
        assert data["total"] == len(data["anomalies"])

    def test_clean_exits_zero_unclean_exits_one(self):
        """Exit code must be consistent with `clean` field."""
        result = run_audit("--json")
        data = json.loads(result.stdout)
        if data["clean"]:
            assert result.returncode == 0
        else:
            assert result.returncode == 1

    def test_fix_flag_adds_fixed_skipped_to_json(self):
        result = run_audit("--json", "--fix")
        data = json.loads(result.stdout)
        assert "fixed" in data
        assert "skipped_unsafe" in data

    def test_human_readable_output_contains_keyword(self):
        result = run_audit()
        combined = result.stdout + result.stderr
        assert ("healthy" in combined.lower() or "anomaly" in combined.lower()), (
            f"Unexpected output: {combined!r}"
        )

    def test_anomaly_entries_have_required_fields(self):
        """Every anomaly entry must carry type, safe_to_fix, remediation, detail."""
        result = run_audit("--json")
        data = json.loads(result.stdout)
        for a in data["anomalies"]:
            assert "type" in a, f"Missing 'type' in {a}"
            assert "safe_to_fix" in a, f"Missing 'safe_to_fix' in {a}"
            assert "remediation" in a, f"Missing 'remediation' in {a}"
            assert "detail" in a, f"Missing 'detail' in {a}"


# ── Isolated anomaly detection tests ─────────────────────────────────────────

class TestWorktreeAuditIsolated:
    """Tests using a temporary, isolated git repo to avoid polluting the main repo."""

    def test_clean_repo_exits_zero(self, tmp_path):
        """A fresh repo with no .spiral-workers/ reports clean."""
        _init_git_repo(tmp_path)
        # Copy main.py into tmp_path so Path(__file__).parent resolves to tmp_path
        import shutil
        shutil.copy(MAIN_PY, tmp_path / "main.py")
        result = subprocess.run(
            [sys.executable, str(tmp_path / "main.py"), "worktree", "audit", "--json"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        data = json.loads(result.stdout)
        assert data["clean"] is True, f"Expected clean, got anomalies: {data['anomalies']}"
        assert result.returncode == 0

    def test_stale_lock_detected(self, tmp_path):
        """A lock file older than threshold is detected as stale_lock."""
        import shutil
        _init_git_repo(tmp_path)
        shutil.copy(MAIN_PY, tmp_path / "main.py")

        worker_dir = tmp_path / ".spiral-workers" / "worker-test"
        worker_dir.mkdir(parents=True)
        r = subprocess.run(
            ["git", "-C", str(tmp_path), "worktree", "add",
             str(worker_dir), "-b", "stale-lock-branch"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"Could not create test worktree: {r.stderr}")

        # Resolve the git dir for the worker worktree
        git_ptr = worker_dir / ".git"
        git_dir_line = git_ptr.read_text().strip()
        if git_dir_line.startswith("gitdir:"):
            git_dir = Path(git_dir_line[len("gitdir:"):].strip())
            if not git_dir.is_absolute():
                git_dir = worker_dir / git_dir
        else:
            git_dir = worker_dir / ".git"

        if not git_dir.is_dir():
            pytest.skip("Could not resolve worker git dir")

        lock_file = git_dir / "index.lock"
        lock_file.write_text("locked")
        old_time = time.time() - 600  # 10 minutes ago
        os.utime(str(lock_file), (old_time, old_time))

        result = subprocess.run(
            [sys.executable, str(tmp_path / "main.py"), "worktree", "audit", "--json"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        data = json.loads(result.stdout)
        types = [a["type"] for a in data["anomalies"]]
        assert "stale_lock" in types, f"Expected stale_lock, got: {types}"
        assert result.returncode == 1

    def test_detached_head_detected(self, tmp_path):
        """A detached HEAD worktree is detected as detached_head."""
        import shutil
        _init_git_repo(tmp_path)
        shutil.copy(MAIN_PY, tmp_path / "main.py")

        worker_dir = tmp_path / ".spiral-workers" / "worker-detached"
        worker_dir.mkdir(parents=True)
        r = subprocess.run(
            ["git", "-C", str(tmp_path), "worktree", "add", "--detach", str(worker_dir)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"Could not create detached worktree: {r.stderr}")

        result = subprocess.run(
            [sys.executable, str(tmp_path / "main.py"), "worktree", "audit", "--json"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        data = json.loads(result.stdout)
        types = [a["type"] for a in data["anomalies"]]
        assert "detached_head" in types, f"Expected detached_head, got: {types}"
        assert result.returncode == 1

    def test_fix_removes_stale_lock(self, tmp_path):
        """--fix removes a stale lock and reports it as fixed."""
        import shutil
        _init_git_repo(tmp_path)
        shutil.copy(MAIN_PY, tmp_path / "main.py")

        worker_dir = tmp_path / ".spiral-workers" / "worker-fix"
        worker_dir.mkdir(parents=True)
        r = subprocess.run(
            ["git", "-C", str(tmp_path), "worktree", "add",
             str(worker_dir), "-b", "fix-test-branch"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            pytest.skip(f"Could not create worker worktree: {r.stderr}")

        git_ptr = worker_dir / ".git"
        git_dir_line = git_ptr.read_text().strip()
        if git_dir_line.startswith("gitdir:"):
            git_dir = Path(git_dir_line[len("gitdir:"):].strip())
            if not git_dir.is_absolute():
                git_dir = worker_dir / git_dir
        else:
            git_dir = worker_dir / ".git"

        if not git_dir.is_dir():
            pytest.skip("Cannot resolve git dir")

        lock_file = git_dir / "index.lock"
        lock_file.write_text("locked")
        old_time = time.time() - 600
        os.utime(str(lock_file), (old_time, old_time))

        result = subprocess.run(
            [sys.executable, str(tmp_path / "main.py"),
             "worktree", "audit", "--json", "--fix"],
            capture_output=True, text=True, cwd=str(tmp_path),
        )
        data = json.loads(result.stdout)
        assert data.get("fixed", 0) >= 1, f"Expected fixed>=1, got: {data}"
        assert not lock_file.exists(), "Lock file should have been removed by --fix"

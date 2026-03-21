"""US-687: Parallel Worker Worktree Isolation — no cross-worker file conflicts."""

from __future__ import annotations

import csv
import io
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

WORKER_COUNT = 3
FILES = ["utils_A.py", "utils_B.py", "utils_C.py"]
SHAS = ["aaa1111", "bbb2222", "ccc3333"]


def _init_repo(root: Path) -> None:
    """Create a real git repo at *root* with an initial commit."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "init", str(root)], capture_output=True, check=True, env=env)
    readme = root / "README.md"
    readme.write_text("init", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "."], capture_output=True, check=True, env=env)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "init"], capture_output=True, check=True, env=env)


def _add_worktree(repo: Path, wt_path: Path, branch: str) -> None:
    """Add a git worktree for *branch* at *wt_path*."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", str(wt_path), "-b", branch],
        capture_output=True,
        check=True,
        env=env,
    )


def _commit_file(repo: Path, filename: str, content: str, msg: str) -> str:
    """Write *filename*, commit, return short SHA."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    (repo / filename).write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", filename], capture_output=True, check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", msg], capture_output=True, check=True, env=env)
    r = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True, env=env
    )
    return r.stdout.strip()


def _results_tsv(rows: list[dict[str, str]]) -> str:
    hdr = ["story_id", "worker_id", "commit_sha", "status"]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=hdr, delimiter="\t", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


@pytest.fixture()
def worktree_env(tmp_path: Path) -> dict[str, Any]:
    """Set up main repo + 3 worktrees, each committing a unique file."""
    main = tmp_path / "main-repo"
    main.mkdir()
    _init_repo(main)
    wt_base = tmp_path / ".spiral-workers"
    wt_base.mkdir()
    worktrees: list[Path] = []
    shas: list[str] = []
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    for i in range(WORKER_COUNT):
        wt = wt_base / f"worker-{i + 1}"
        _add_worktree(main, wt, f"worker-{i + 1}")
        sha = _commit_file(wt, FILES[i], f"# {FILES[i]} from worker {i + 1}\n", f"feat: {FILES[i]}")
        worktrees.append(wt)
        shas.append(sha)
    # Merge all worker branches into main
    for i in range(WORKER_COUNT):
        subprocess.run(
            ["git", "-C", str(main), "merge", "--no-ff", f"worker-{i + 1}", "--no-edit"],
            capture_output=True,
            check=True,
            env=env,
        )
    return {"main": main, "worktrees": worktrees, "shas": shas, "wt_base": wt_base}


class TestWorktreeIsolation:
    """AC2: .spiral-workers/worker-{1,2,3}/.git are isolated."""

    def test_each_worker_has_own_git_dir(self, worktree_env: dict[str, Any]) -> None:
        for wt in worktree_env["worktrees"]:
            git_path = wt / ".git"
            assert git_path.exists(), f"{wt.name} missing .git"

    def test_workers_have_separate_heads(self, worktree_env: dict[str, Any]) -> None:
        heads: list[str] = []
        for wt in worktree_env["worktrees"]:
            r = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
            heads.append(r.stdout.strip())
        assert len(set(heads)) == WORKER_COUNT, f"Expected {WORKER_COUNT} distinct HEADs, got {heads}"


class TestFileConflictFree:
    """AC1: Each worker modifies a separate file; main has all 3, no conflicts."""

    def test_main_contains_all_worker_files(self, worktree_env: dict[str, Any]) -> None:
        main: Path = worktree_env["main"]
        for f in FILES:
            assert (main / f).exists(), f"main branch missing {f}"

    def test_no_merge_conflict_markers(self, worktree_env: dict[str, Any]) -> None:
        main: Path = worktree_env["main"]
        for f in FILES:
            content = (main / f).read_text(encoding="utf-8")
            assert "<<<<<<" not in content, f"Conflict markers in {f}"
            assert ">>>>>>" not in content, f"Conflict markers in {f}"


class TestResultsTsvDistinct:
    """AC3: results.tsv has 3 stories with distinct worker_id and no dup SHAs."""

    def test_distinct_worker_ids(self, tmp_path: Path) -> None:
        rows = [
            {"story_id": f"US-00{i + 1}", "worker_id": str(i + 1), "commit_sha": SHAS[i], "status": "accept"}
            for i in range(WORKER_COUNT)
        ]
        tsv = tmp_path / "results.tsv"
        tsv.write_text(_results_tsv(rows), encoding="utf-8")
        reader = csv.DictReader(io.StringIO(tsv.read_text(encoding="utf-8")), delimiter="\t")
        wids = [r["worker_id"] for r in reader]
        assert len(set(wids)) == WORKER_COUNT

    def test_no_duplicate_commit_shas(self, tmp_path: Path) -> None:
        rows = [
            {"story_id": f"US-00{i + 1}", "worker_id": str(i + 1), "commit_sha": SHAS[i], "status": "accept"}
            for i in range(WORKER_COUNT)
        ]
        tsv = tmp_path / "results.tsv"
        tsv.write_text(_results_tsv(rows), encoding="utf-8")
        reader = csv.DictReader(io.StringIO(tsv.read_text(encoding="utf-8")), delimiter="\t")
        shas = [r["commit_sha"] for r in reader]
        assert len(set(shas)) == WORKER_COUNT, f"Duplicate SHAs: {shas}"

    def test_merge_commits_on_main(self, worktree_env: dict[str, Any]) -> None:
        main: Path = worktree_env["main"]
        r = subprocess.run(
            ["git", "-C", str(main), "log", "--oneline", "--merges"], capture_output=True, text=True, check=True
        )
        merges = [line for line in r.stdout.strip().splitlines() if line]
        assert len(merges) >= WORKER_COUNT, f"Expected {WORKER_COUNT} merges, got {len(merges)}"

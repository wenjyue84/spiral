"""tests/test_extract_story_commits.py — Tests for lib/prd/extract_story_commits.py (US-640)."""

import logging
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from prd.extract_story_commits import story_commits_from_git

KNOWN_IDS = {"US-001", "US-002", "US-003", "US-004", "US-005"}

# 8 commits: 5 stories (US-001..US-005) + 2 orphans (US-099, US-098)
# US-001 appears in 2 commits; US-003 appears in 2 commits (incl. multi-story)
SUBJECTS = [
    "feat: US-001 login page",
    "fix: US-001 login bug",
    "feat: US-002 dashboard",
    "feat: US-003 reports",
    "feat: US-003 US-004 shared utils",
    "feat: US-005 exports",
    "chore: US-099 orphan A",
    "chore: US-098 orphan B",
]


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Temp git repo with 8 story commits."""

    def g(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    g("init")
    g("config", "user.email", "t@t.com")
    g("config", "user.name", "T")
    (tmp_path / "f").write_text("init")
    g("add", ".")
    g("commit", "-m", "init")
    for subj in SUBJECTS:
        (tmp_path / "f").write_text(subj)
        g("add", ".")
        g("commit", "-m", subj)
    return tmp_path


def test_mapping_counts(git_repo: Path) -> None:
    r = story_commits_from_git(git_repo)
    assert len(r["US-001"]) == 2
    assert len(r["US-002"]) == 1
    assert len(r["US-003"]) == 2  # two commits mention US-003
    assert len(r["US-004"]) == 1
    assert len(r["US-005"]) == 1


def test_orphans_in_mapping(git_repo: Path) -> None:
    r = story_commits_from_git(git_repo)
    assert "US-099" in r
    assert "US-098" in r


def test_orphan_warnings(git_repo: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="prd.extract_story_commits"):
        story_commits_from_git(git_repo, known_ids=KNOWN_IDS)
    assert sum(1 for m in caplog.messages if "US-099" in m) == 1
    assert sum(1 for m in caplog.messages if "US-098" in m) == 1


def test_no_warnings_for_known_stories(git_repo: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="prd.extract_story_commits"):
        story_commits_from_git(git_repo, known_ids=KNOWN_IDS)
    for sid in KNOWN_IDS:
        assert not any(sid in m for m in caplog.messages)


def test_shas_are_hex40(git_repo: Path) -> None:
    r = story_commits_from_git(git_repo)
    for shas in r.values():
        for sha in shas:
            assert len(sha) == 40 and sha.isalnum()


def test_no_warnings_without_known_ids(git_repo: Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        story_commits_from_git(git_repo)
    assert not caplog.records

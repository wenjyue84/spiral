"""Tests for conftest.py fixtures — verify mock_api_repo and related fixtures are properly wired."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def test_mock_api_repo_fixture_importable(mock_api_repo: tuple[Any, Path]) -> None:
    """Verify mock_api_repo fixture is importable and yields (MockClaudeAPI, Path)."""
    mock_api, repo_path = mock_api_repo
    assert mock_api is not None, "mock_api_repo should yield a MockClaudeAPI instance"
    assert repo_path.exists(), "repo_path should be a valid directory"
    assert isinstance(repo_path, Path), "repo_path should be a Path instance"


def test_mock_api_repo_has_prd_json(mock_api_repo: tuple[Any, Path]) -> None:
    """Verify mock_api_repo fixture creates prd.json in the repo."""
    _mock_api, repo_path = mock_api_repo
    prd_path = repo_path / "prd.json"
    assert prd_path.exists(), "prd.json should exist in mock_api_repo"

    # Load and verify it's valid JSON
    with open(prd_path, encoding="utf-8") as f:
        prd = json.load(f)
    assert isinstance(prd, dict), "prd.json should be a dict"
    assert "userStories" in prd, "prd.json should have userStories"


def test_mock_api_repo_has_constitution(mock_api_repo: tuple[Any, Path]) -> None:
    """Verify mock_api_repo fixture creates constitution.md in the repo."""
    _mock_api, repo_path = mock_api_repo
    constitution_path = repo_path / "constitution.md"
    assert constitution_path.exists(), "constitution.md should exist in mock_api_repo"
    content = constitution_path.read_text(encoding="utf-8")
    assert "Constitution" in content or "Invariants" in content, "constitution.md should have meaningful content"


def test_mock_api_repo_is_git_repo(mock_api_repo: tuple[Any, Path]) -> None:
    """Verify mock_api_repo fixture initializes a git repository."""
    _mock_api, repo_path = mock_api_repo
    git_dir = repo_path / ".git"
    assert git_dir.exists(), ".git directory should exist"
    assert git_dir.is_dir(), ".git should be a directory"

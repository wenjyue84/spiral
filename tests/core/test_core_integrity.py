"""Seed tests for SPIRAL core infrastructure integrity.

These tests are HUMAN-MAINTAINED and protected from Ralph modification
by the PreToolUse hook (protect-spiral-files.sh). They serve as the
"trusted verification base" -- if these tests pass, the core system
is intact regardless of what Ralph has done to the project code.

This addresses the "Trusting Trust" problem: Ralph cannot weaken tests
that validate the system Ralph itself runs inside.
"""

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure lib/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestCoreFilesExist:
    """Verify that all essential orchestration files exist."""

    @pytest.mark.parametrize(
        "path",
        [
            "spiral.sh",
            "spiral.config.sh",
            "ralph/ralph.sh",
            "ralph/CLAUDE.md",
            "lib/impl/commit_revert.sh",
            "lib/command_allowlist.sh",
            "lib/spiral_assert.sh",
            "lib/prd/validate_stories.py",
            "lib/prd/check_dag.py",
            ".claude/hooks/protect-spiral-files.sh",
        ],
    )
    def test_core_file_exists(self, path: str) -> None:
        assert (REPO_ROOT / path).exists(), f"Core file missing: {path}"


class TestProtectHookIntegrity:
    """Verify the PreToolUse hook has the env-var gate and protected paths."""

    def test_hook_has_env_gate(self) -> None:
        hook = (REPO_ROOT / ".claude/hooks/protect-spiral-files.sh").read_text(encoding="utf-8")
        assert "SPIRAL_WORKER_ACTIVE" in hook, "Hook must check SPIRAL_WORKER_ACTIVE env var"

    def test_hook_protects_lib(self) -> None:
        hook = (REPO_ROOT / ".claude/hooks/protect-spiral-files.sh").read_text(encoding="utf-8")
        assert '"lib/"' in hook or "'lib/'" in hook, "Hook must protect lib/ directory"

    def test_hook_protects_ralph(self) -> None:
        hook = (REPO_ROOT / ".claude/hooks/protect-spiral-files.sh").read_text(encoding="utf-8")
        assert '"ralph/"' in hook or "'ralph/'" in hook, "Hook must protect ralph/ directory"

    def test_hook_protects_itself(self) -> None:
        hook = (REPO_ROOT / ".claude/hooks/protect-spiral-files.sh").read_text(encoding="utf-8")
        assert '".claude/hooks/"' in hook or "'.claude/hooks/'" in hook, "Hook must protect its own directory"


class TestRalphWorkerFlag:
    """Verify ralph.sh exports the worker flag before calling Claude."""

    def test_ralph_exports_worker_flag(self) -> None:
        ralph = (REPO_ROOT / "ralph/ralph.sh").read_text(encoding="utf-8")
        assert "SPIRAL_WORKER_ACTIVE" in ralph, "ralph.sh must export SPIRAL_WORKER_ACTIVE=1 before claude invocation"


class TestPrdSchemaValid:
    """Verify prd.json is valid JSON and has expected structure."""

    def test_prd_is_valid_json(self) -> None:
        prd_path = REPO_ROOT / "prd.json"
        if not prd_path.exists():
            pytest.skip("No prd.json in repo root")
        with open(prd_path, encoding="utf-8") as f:
            data = json.load(f)
        assert "userStories" in data, "prd.json must have userStories key"

    def test_all_stories_have_id(self) -> None:
        prd_path = REPO_ROOT / "prd.json"
        if not prd_path.exists():
            pytest.skip("No prd.json in repo root")
        with open(prd_path, encoding="utf-8") as f:
            data = json.load(f)
        for story in data.get("userStories", []):
            assert "id" in story, f"Story missing 'id': {story.get('title', '???')}"


class TestCommandAllowlist:
    """Verify the command allowlist blocks dangerous operations."""

    def test_allowlist_blocks_rm_rf(self) -> None:
        allowlist = (REPO_ROOT / "lib/command_allowlist.sh").read_text(encoding="utf-8")
        assert "rm -rf" in allowlist, "Command allowlist must explicitly deny 'rm -rf'"

    def test_allowlist_blocks_force_push(self) -> None:
        allowlist = (REPO_ROOT / "lib/command_allowlist.sh").read_text(encoding="utf-8")
        assert "git push --force" in allowlist, "Command allowlist must explicitly deny 'git push --force'"

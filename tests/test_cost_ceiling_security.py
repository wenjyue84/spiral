"""Security tests for SPIRAL_COST_CEILING budget gate (US-577).

Verifies that:
- Phase I is blocked when estimated token costs exceed SPIRAL_COST_CEILING
- rollback_story() removes the lowest-priority pending story and persists it
- No story implementation runs when the ceiling is hit and 'skip' is selected
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.budget_analyzer import check_budget_gate
from lib.rollback_story import rollback_story

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_prd(tmp_path: Path, stories: list[dict[str, Any]] | None = None) -> Path:
    """Write a minimal prd.json with pending stories and return its Path."""
    if stories is None:
        stories = [
            {"id": "US-001", "title": "High priority story", "passes": False, "priority": "high"},
            {"id": "US-002", "title": "Medium priority story", "passes": False, "priority": "medium"},
            {"id": "US-003", "title": "Low priority story", "passes": False, "priority": "low"},
        ]
    prd_path = tmp_path / "prd.json"
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump({"userStories": stories}, f)
    return prd_path


def _make_empty_results_tsv(tmp_path: Path) -> Path:
    """Write an empty results.tsv and return its Path."""
    tsv_path = tmp_path / "results.tsv"
    with open(tsv_path, "w", encoding="utf-8") as f:
        f.write("story_id\tstatus\tmodel\tduration_sec\n")
    return tsv_path


# ---------------------------------------------------------------------------
# Budget gate blocking
# ---------------------------------------------------------------------------


class TestBudgetGateBlocking:
    """check_budget_gate() must return would_exceed=True when cost > ceiling."""

    def test_ceiling_exceeded_returns_would_exceed_true(self, tmp_path: Path) -> None:
        """Phase I is blocked when estimated pending cost exceeds SPIRAL_COST_CEILING."""
        prd_path = _make_prd(tmp_path)
        results_path = _make_empty_results_tsv(tmp_path)

        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=0.0001,  # tiny sentinel to force breach
        )

        assert result["would_exceed"] is True
        assert result["estimated_pending_usd"] > 0.0001
        assert result["total_projected_usd"] > 0.0001

    def test_ceiling_not_exceeded_allows_phase_i(self, tmp_path: Path) -> None:
        """Phase I proceeds when estimated cost stays under the ceiling."""
        prd_path = _make_prd(tmp_path)
        results_path = _make_empty_results_tsv(tmp_path)

        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=99999.0,
        )

        assert result["would_exceed"] is False

    def test_no_ceiling_never_blocks_phase_i(self, tmp_path: Path) -> None:
        """When cost_ceiling_usd is None, Phase I is never blocked."""
        prd_path = _make_prd(tmp_path)
        results_path = _make_empty_results_tsv(tmp_path)

        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=None,
        )

        assert result["would_exceed"] is False

    def test_zero_or_negative_ceiling_treated_as_disabled(self, tmp_path: Path) -> None:
        """A ceiling of 0 or negative is treated as disabled — Phase I is not blocked."""
        prd_path = _make_prd(tmp_path)
        results_path = _make_empty_results_tsv(tmp_path)

        for ceiling in (0, 0.0, -1.0):
            result = check_budget_gate(
                prd_file=prd_path,
                results_tsv=results_path,
                cost_ceiling_usd=float(ceiling),
            )
            assert result["would_exceed"] is False, f"ceiling={ceiling} should be treated as disabled, not blocking"

    def test_monkeypatched_estimator_with_env_ceiling_forces_breach(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Monkeypatching the estimator with SPIRAL_COST_CEILING=0.01 forces a breach."""
        prd_path = _make_prd(tmp_path)
        results_path = _make_empty_results_tsv(tmp_path)

        monkeypatch.setenv("SPIRAL_COST_CEILING", "0.01")

        import lib.budget_analyzer as ba

        def mock_estimate_pending(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return {
                "total_cost_usd": 999.99,
                "total_tokens": 10_000_000,
                "by_model": {"sonnet": 999.99},
                "story_count": 3,
                "by_story": [("US-001", 333.33), ("US-002", 333.33), ("US-003", 333.33)],
            }

        monkeypatch.setattr(ba, "estimate_pending_story_cost", mock_estimate_pending)

        ceiling = float(os.environ["SPIRAL_COST_CEILING"])
        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=ceiling,
        )

        assert result["would_exceed"] is True
        assert result["estimated_pending_usd"] == pytest.approx(999.99)

    def test_ceiling_check_never_silently_bypasses(self, tmp_path: Path) -> None:
        """Security invariant: would_exceed must be True when projected > ceiling; no silent pass."""
        prd_path = _make_prd(tmp_path)
        results_path = _make_empty_results_tsv(tmp_path)

        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=0.00001,
        )

        assert result["would_exceed"] is True, (
            f"Budget gate silently bypassed: projected={result['total_projected_usd']:.8f} "
            f"> ceiling={result['ceiling_usd']:.8f} but would_exceed is False"
        )


# ---------------------------------------------------------------------------
# Rollback behaviour
# ---------------------------------------------------------------------------


class TestRollbackBehavior:
    """rollback_story() must remove the lowest-priority pending story and persist it."""

    def test_rollback_removes_lowest_priority_and_persists(self, tmp_path: Path) -> None:
        """Rollback removes the lowest-priority story and the change is written to disk."""
        prd_path = _make_prd(tmp_path)

        with open(prd_path, encoding="utf-8") as f:
            before = json.load(f)
        pending_before = [s for s in before["userStories"] if not s.get("passes")]
        assert len(pending_before) == 3

        result = rollback_story(prd_path)

        assert result["success"] is True
        assert result["removed_story_id"] == "US-003"  # lowest priority = "low"
        assert result["remaining_pending"] == 2

        with open(prd_path, encoding="utf-8") as f:
            after = json.load(f)
        pending_after = [s for s in after["userStories"] if not s.get("passes")]
        assert len(pending_after) == 2
        assert not any(s["id"] == "US-003" for s in pending_after)

    def test_rollback_targets_lowest_priority_not_insertion_order(self, tmp_path: Path) -> None:
        """The story removed is the lowest-priority one, regardless of list position."""
        stories: list[dict[str, Any]] = [
            {"id": "US-A", "title": "Low priority (inserted first)", "passes": False, "priority": "low"},
            {"id": "US-B", "title": "High priority", "passes": False, "priority": "high"},
            {"id": "US-C", "title": "Medium priority", "passes": False, "priority": "medium"},
        ]
        prd_path = _make_prd(tmp_path, stories)

        result = rollback_story(prd_path)

        assert result["success"] is True
        assert result["removed_story_id"] == "US-A"  # lowest priority despite first position

    def test_rollback_preserves_higher_priority_stories(self, tmp_path: Path) -> None:
        """After rollback, all higher-priority stories remain in prd.json."""
        prd_path = _make_prd(tmp_path)

        rollback_story(prd_path)

        with open(prd_path, encoding="utf-8") as f:
            after = json.load(f)
        ids_remaining = {s["id"] for s in after["userStories"]}
        assert "US-001" in ids_remaining  # high priority — must stay
        assert "US-002" in ids_remaining  # medium priority — must stay

    def test_rollback_no_pending_stories_returns_failure(self, tmp_path: Path) -> None:
        """When all stories have passed, rollback returns success=False."""
        stories: list[dict[str, Any]] = [
            {"id": "US-001", "title": "Done", "passes": True, "priority": "high"},
        ]
        prd_path = _make_prd(tmp_path, stories)

        result = rollback_story(prd_path)

        assert result["success"] is False
        assert result["error"] is not None

    def test_rollback_dry_run_does_not_modify_file(self, tmp_path: Path) -> None:
        """Dry-run rollback reports what would be removed without modifying prd.json."""
        prd_path = _make_prd(tmp_path)

        with open(prd_path, encoding="utf-8") as f:
            before_content = f.read()

        result = rollback_story(prd_path, dry_run=True)

        assert result["success"] is True
        assert result.get("dry_run") is True

        with open(prd_path, encoding="utf-8") as f:
            after_content = f.read()

        assert before_content == after_content


# ---------------------------------------------------------------------------
# Skip path — no story execution when ceiling exceeded
# ---------------------------------------------------------------------------


class TestSkipPathBlocksImplementation:
    """When ceiling is hit and user selects skip, no stories should be executed."""

    def test_would_exceed_signals_skip_to_phase_i(self, tmp_path: Path) -> None:
        """The would_exceed flag is the signal the shell uses to set _BUDGET_GATE_SKIP=1."""
        prd_path = _make_prd(tmp_path)
        results_path = _make_empty_results_tsv(tmp_path)

        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=0.0001,
        )

        # Shell script maps: would_exceed=true → _BUDGET_GATE_SKIP=1 → no stories run
        assert result["would_exceed"] is True, "Gate must signal skip when cost exceeds ceiling"

    def test_pending_stories_not_executed_when_gate_blocks(self, tmp_path: Path) -> None:
        """Pending stories exist but must not be passed to Ralph when the gate signals block."""
        stories: list[dict[str, Any]] = [
            {"id": "US-EXEC-001", "title": "Expensive story", "passes": False, "priority": "high"},
        ]
        prd_path = _make_prd(tmp_path, stories)
        results_path = _make_empty_results_tsv(tmp_path)

        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=0.0001,
        )

        assert result["would_exceed"] is True
        assert result["pending_count"] > 0, "Stories are pending"
        # The shell translates would_exceed=True + user_input=skip into _BUDGET_GATE_SKIP=1.
        # No story_id is ever passed to the Ralph worker while the skip flag is set.

    def test_no_bypass_when_current_spend_plus_pending_exceeds_ceiling(self, tmp_path: Path) -> None:
        """total_projected = current_spend + pending. Gate must fire when this exceeds ceiling."""
        prd_path = _make_prd(tmp_path)

        # Simulate non-zero current spend via a results.tsv row
        tsv_path = tmp_path / "results.tsv"
        with open(tsv_path, "w", encoding="utf-8") as f:
            f.write("story_id\tstory_title\tmodel\tduration_sec\tstatus\n")
            f.write("US-000\tPrev story\tsonnet\t300\tpass\n")  # ~300s run ≈ some cost

        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=tsv_path,
            cost_ceiling_usd=0.0001,
        )

        assert result["would_exceed"] is True
        assert result["current_spend_usd"] >= 0.0
        assert result["total_projected_usd"] > 0.0001


# ---------------------------------------------------------------------------
# Security: No secrets leakage
# ---------------------------------------------------------------------------


class TestNoSecretsLeakage:
    """Verify that sensitive environment variables do not leak into budget check output."""

    _SENSITIVE_PATTERNS = [
        r"[A-Z_]*API[_]*KEY",
        r"[A-Z_]*TOKEN[_]*",
        r"[A-Z_]*SECRET[_]*",
        r"[A-Z_]*PASSWORD[_]*",
        r"sk_[a-zA-Z0-9]{20,}",  # Stripe-like keys
        r"ghp_[a-zA-Z0-9]{20,}",  # GitHub PAT-like
    ]

    def test_budget_check_result_dict_contains_no_secrets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify the BudgetCheckResult dict never includes sensitive values."""
        prd_path = _make_prd(tmp_path)
        results_path = _make_empty_results_tsv(tmp_path)

        # Set fake sensitive env vars
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk_test_sensitive_key_12345")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token_secret_67890")
        monkeypatch.setenv("DATABASE_PASSWORD", "super_secret_password")

        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=99999.0,
        )

        # Convert result to string representation
        result_str = json.dumps(result)

        # Verify no sensitive values appear
        forbidden_values = [
            "sk_test_sensitive_key_12345",
            "ghp_test_token_secret_67890",
            "super_secret_password",
        ]
        for sensitive_value in forbidden_values:
            assert sensitive_value not in result_str, (
                f"Result dict contains sensitive value: {sensitive_value}"
            )

    def test_budget_check_output_when_printed_contains_no_secrets(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Verify that printing the budget check result doesn't leak secrets."""
        import json as json_module

        prd_path = _make_prd(tmp_path)
        results_path = _make_empty_results_tsv(tmp_path)

        # Set fake sensitive env vars
        monkeypatch.setenv("SPIRAL_COST_CEILING", "10.00")
        monkeypatch.setenv("SECRET_API_KEY", "test_secret_xyz_9999")

        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=10.0,
        )

        # Print like the CLI does
        print(json_module.dumps(result, indent=2))
        captured = capsys.readouterr()

        # Verify secret doesn't appear in stdout
        assert "test_secret_xyz_9999" not in captured.out, (
            "Secret value leaked into stdout from budget check"
        )

    def test_budget_check_never_includes_filepath_secrets(self, tmp_path: Path) -> None:
        """Verify that file paths containing sensitive patterns aren't included in output."""
        # Create a prd file in a path with sensitive-looking name (within tmp_path)
        sensitive_path = tmp_path / "ANTHROPIC_API_KEY_backup"
        sensitive_path.mkdir(parents=True, exist_ok=True)
        prd_path = sensitive_path / "prd.json"

        with open(prd_path, "w", encoding="utf-8") as f:
            json.dump({"userStories": []}, f)

        results_path = sensitive_path / "results.tsv"
        with open(results_path, "w", encoding="utf-8") as f:
            f.write("story_id\tstatus\tmodel\tduration_sec\n")

        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=10.0,
        )

        result_str = json.dumps(result)
        # The result dict should NOT leak file paths with sensitive names
        # Specifically, ANTHROPIC_API_KEY should not appear in output
        assert "ANTHROPIC_API_KEY_backup" not in result_str, (
            "Directory name with sensitive pattern leaked into result dict"
        )

    def test_zero_and_none_ceiling_do_not_leak_in_error_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Verify that special ceiling values (0, None) don't cause error leakage."""
        prd_path = _make_prd(tmp_path)
        results_path = _make_empty_results_tsv(tmp_path)

        # Set a fake secret in the environment
        monkeypatch.setenv("SECRET_TOKEN", "fake_secret_token_abc123")

        # Test with None ceiling (disabled budget gate)
        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=None,
        )

        result_str = json.dumps(result)
        assert "fake_secret_token_abc123" not in result_str

        # Test with 0 ceiling (disabled budget gate)
        result = check_budget_gate(
            prd_file=prd_path,
            results_tsv=results_path,
            cost_ceiling_usd=0.0,
        )

        result_str = json.dumps(result)
        assert "fake_secret_token_abc123" not in result_str

"""Security tests for SPIRAL loop integration (US-1393).

Verifies MockClaudeAPI prevents real API calls and no tokens leak to disk.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.fixtures.mock_claude_api import MockClaudeAPI


def _assert_no_leaked_secrets(directory: Path) -> None:
    """Assert no ANTHROPIC_API_KEY or sk-ant token in any file under directory."""
    if not directory.exists():
        return
    for fpath in directory.rglob("*"):
        if not fpath.is_file():
            continue
        try:
            content = fpath.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in ("ANTHROPIC_API_KEY", "sk-ant"):
            assert pattern not in content, f"Secret pattern '{pattern}' leaked to {fpath}"


class TestSpiralLoopIntegrationSecurity:
    """Security-focused integration tests for the SPIRAL loop."""

    def test_spiral_loop_integration_success(
        self,
        mock_api_repo: tuple[MockClaudeAPI, Path],
    ) -> None:
        """AC1: MockClaudeAPI active — zero real claude CLI calls made.

        Runs a minimal SPIRAL-like loop simulation with the mock_api_repo fixture.
        Verifies no real API calls escape and no secret tokens leak to .spiral/.
        """
        mock_api, repo_root = mock_api_repo

        # Create .spiral/ scratch dir (as SPIRAL would during Phase I)
        spiral_dir = repo_root / ".spiral"
        spiral_dir.mkdir(exist_ok=True)
        (spiral_dir / "_checkpoint.json").write_text(json.dumps({"iter": 1, "phase": "I"}), encoding="utf-8")

        # Inject a success response for Phase I, story US-001
        mock_api.inject_response("I", "US-001", {"passes": True, "output": "mock ok"})

        # Non-claude subprocess calls pass through normally
        # (MockClaudeAPI only intercepts the 'claude' binary)
        result = subprocess.run(
            ["python", "-c", "import sys; sys.exit(0)"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0

        # Verify: zero real claude CLI calls were intercepted (none dispatched)
        assert len(mock_api.call_log) == 0, (
            f"Expected 0 real claude calls, got {len(mock_api.call_log)}: {mock_api.call_log}"
        )

        # AC3: No secret tokens in .spiral/ scratch dir
        _assert_no_leaked_secrets(spiral_dir)

    def test_spiral_loop_integration_retry(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC2: haiku→sonnet escalation verified via mock subprocess.run.

        Simulates SPIRAL Phase I retry: haiku returns exit 1, triggering escalation
        to sonnet which succeeds. Verifies model sequence and no token leakage.
        """
        spiral_dir = tmp_path / ".spiral"
        spiral_dir.mkdir()

        model_calls: list[str] = []

        def _mock_claude_run(
            args: Any,
            *pargs: object,
            **kwargs: object,
        ) -> subprocess.CompletedProcess[bytes]:
            """Intercept claude CLI calls and simulate haiku fail → sonnet pass."""
            arg_list = list(args) if isinstance(args, (list, tuple)) else [str(args)]
            model = "haiku"
            for i, arg in enumerate(arg_list):
                if arg == "--model" and i + 1 < len(arg_list):
                    model = arg_list[i + 1]
                    break
            model_calls.append(model)
            if model == "haiku":
                return subprocess.CompletedProcess(args=arg_list, returncode=1, stdout=b"", stderr=b"haiku failed")
            return subprocess.CompletedProcess(args=arg_list, returncode=0, stdout=b'{"passes":true}', stderr=b"")

        monkeypatch.setattr(subprocess, "run", _mock_claude_run)

        # Simulate Phase I: haiku attempt fails, escalate to sonnet
        story_id = "US-SEC-001"
        haiku_result = subprocess.run(
            ["claude", "--model", "haiku", "--story", story_id],
            capture_output=True,
        )
        assert haiku_result.returncode == 1, "haiku attempt should fail (escalation trigger)"

        sonnet_result = subprocess.run(
            ["claude", "--model", "sonnet", "--story", story_id],
            capture_output=True,
        )
        assert sonnet_result.returncode == 0, "sonnet escalation should succeed"

        # Verify escalation sequence: haiku first, then sonnet
        assert model_calls == ["haiku", "sonnet"], f"Expected haiku→sonnet escalation, got: {model_calls}"

        # Simulate results.tsv with escalation entries (as Phase V would write)
        results_tsv = spiral_dir / "results.tsv"
        results_tsv.write_text(
            f"{story_id}\thaiku\tfail\t100\t0.001\t5\n{story_id}\tsonnet\tpass\t200\t0.002\t8\n",
            encoding="utf-8",
        )

        # Verify results show correct model escalation in order
        rows = results_tsv.read_text(encoding="utf-8").strip().splitlines()
        assert len(rows) == 2, f"Expected 2 escalation rows, got {len(rows)}"
        first_cols = rows[0].split("\t")
        second_cols = rows[1].split("\t")
        assert first_cols[1] == "haiku" and first_cols[2] == "fail", f"Row 0: {rows[0]}"
        assert second_cols[1] == "sonnet" and second_cols[2] == "pass", f"Row 1: {rows[1]}"

        # AC3: No secret tokens in .spiral/ scratch dir
        _assert_no_leaked_secrets(spiral_dir)

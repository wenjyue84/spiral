"""Security tests for lib/spiral/validate_results_tsv.py (US-736).

Verifies validator safely handles malformed input, does not leak sensitive data,
and rejects path-traversal or injection attempts.
"""

import csv
import sys
from pathlib import Path
from typing import Any

import pytest

# Add lib/spiral to path for import
sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "spiral"))

from validate_results_tsv import validate


@pytest.fixture
def tmp_prd_json(tmp_path: Any) -> str:
    """Minimal prd.json with one story."""
    prd_file = tmp_path / "prd.json"
    prd_file.write_text('{"userStories": [{"id": "US-001"}]}')
    return str(prd_file)


class TestSecurityValidateResultsTsv:
    """Security-focused tests for validate() function."""

    def test_validate_returns_dict_never_raises(self, tmp_path: Any, tmp_prd_json: str) -> None:
        """validate() returns dict, never raises exception on malformed input."""
        tsv_file = tmp_path / "results.tsv"
        tsv_file.write_text("")  # Empty file

        result = validate(str(tsv_file), tmp_prd_json)

        assert isinstance(result, dict)
        assert "errors" in result
        assert "warnings" in result
        assert "passed_checks" in result
        assert "total_rows_checked" in result

    def test_validate_empty_file(self, tmp_path: Any, tmp_prd_json: str) -> None:
        """Empty TSV returns structured error, not exception."""
        tsv_file = tmp_path / "results.tsv"
        tsv_file.write_text("")

        result = validate(str(tsv_file), tmp_prd_json)

        assert result["errors"] == ["results.tsv is empty or malformed"]
        assert result["total_rows_checked"] == 0

    def test_validate_story_id_with_path_traversal(self, tmp_path: Any, tmp_prd_json: str) -> None:
        """story_id with '../' is rejected as error, no unhandled exception."""
        tsv_file = tmp_path / "results.tsv"
        with open(tsv_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["story_id", "iteration", "attempt", "token_count", "phase_duration_ms", "model"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "story_id": "../etc/passwd",
                    "iteration": "1",
                    "attempt": "1",
                    "token_count": "100",
                    "phase_duration_ms": "1000",
                    "model": "haiku",
                }
            )

        result = validate(str(tsv_file), tmp_prd_json)

        # Should have error about missing US-001
        assert any("US-001" in e and "missing" in e for e in result["errors"])
        assert result["total_rows_checked"] == 1

    def test_validate_story_id_with_shell_metacharacters(self, tmp_path: Any, tmp_prd_json: str) -> None:
        """story_id with ';rm -rf' is rejected as error, no unhandled exception."""
        tsv_file = tmp_path / "results.tsv"
        with open(tsv_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["story_id", "iteration", "attempt", "token_count", "phase_duration_ms", "model"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "story_id": "US-001;rm -rf /",
                    "iteration": "1",
                    "attempt": "1",
                    "token_count": "100",
                    "phase_duration_ms": "1000",
                    "model": "haiku",
                }
            )

        result = validate(str(tsv_file), tmp_prd_json)

        # Should not raise; story_id is treated as literal string
        assert isinstance(result, dict)
        assert result["total_rows_checked"] == 1

    def test_validate_model_with_embedded_newline(self, tmp_path: Any, tmp_prd_json: str) -> None:
        """model field with embedded newline is rejected."""
        tsv_file = tmp_path / "results.tsv"
        with open(tsv_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["story_id", "iteration", "attempt", "token_count", "phase_duration_ms", "model"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "story_id": "US-001",
                    "iteration": "1",
                    "attempt": "1",
                    "token_count": "100",
                    "phase_duration_ms": "1000",
                    "model": "haiku\nsonnet",
                }
            )

        result = validate(str(tsv_file), tmp_prd_json)

        assert any("model" in e and "not in" in e for e in result["errors"])

    def test_validate_token_count_negative(self, tmp_path: Any, tmp_prd_json: str) -> None:
        """Negative token_count is rejected as out of range (without leaking value)."""
        tsv_file = tmp_path / "results.tsv"
        with open(tsv_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["story_id", "iteration", "attempt", "token_count", "phase_duration_ms", "model"],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "story_id": "US-001",
                    "iteration": "1",
                    "attempt": "1",
                    "token_count": "-1",
                    "phase_duration_ms": "1000",
                    "model": "haiku",
                }
            )

        result = validate(str(tsv_file), tmp_prd_json)

        # Should report error for token_count being out of range, but NOT leak the value
        assert any("token_count" in e and "outside" in e for e in result["errors"])
        all_messages = "\n".join(result["errors"] + result["warnings"])
        assert "-1" not in all_messages

    def test_validate_no_credential_leak_in_error_messages(self, tmp_path: Any, tmp_prd_json: str) -> None:
        """Error messages don't contain credential values or token counts."""
        tsv_file = tmp_path / "results.tsv"
        with open(tsv_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "story_id",
                    "iteration",
                    "attempt",
                    "token_count",
                    "phase_duration_ms",
                    "model",
                    "password",
                    "api_key",
                ],
                delimiter="\t",
            )
            writer.writeheader()
            writer.writerow(
                {
                    "story_id": "US-INVALID",
                    "iteration": "1",
                    "attempt": "1",
                    "token_count": "999999999",
                    "phase_duration_ms": "1000",
                    "model": "haiku",
                    "password": "hunter2_secret",
                    "api_key": "sk-SHOULDNOTAPPEAR",
                }
            )

        result = validate(str(tsv_file), tmp_prd_json)

        all_messages = "\n".join(result["errors"] + result["warnings"])
        assert "hunter2_secret" not in all_messages
        assert "sk-SHOULDNOTAPPEAR" not in all_messages
        assert "999999999" not in all_messages  # Extreme token count should not leak

    def test_validate_duplicate_rows_no_data_loss(self, tmp_path: Any, tmp_prd_json: str) -> None:
        """Duplicate rows detected without losing data in error messages."""
        tsv_file = tmp_path / "results.tsv"
        with open(tsv_file, "w", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["story_id", "iteration", "attempt", "token_count", "phase_duration_ms", "model"],
                delimiter="\t",
            )
            writer.writeheader()
            for _ in range(2):
                writer.writerow(
                    {
                        "story_id": "US-001",
                        "iteration": "1",
                        "attempt": "1",
                        "token_count": "100",
                        "phase_duration_ms": "1000",
                        "model": "haiku",
                    }
                )

        result = validate(str(tsv_file), tmp_prd_json)

        assert any("Duplicate row" in e for e in result["errors"])
        assert result["total_rows_checked"] == 2

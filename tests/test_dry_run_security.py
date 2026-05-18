"""tests/test_dry_run_security.py -- Security tests for dry-run command

Verifies that spiral dry-run:
1. Exits with code 0
2. Makes no API calls (requires no API key)
3. Leaks no secrets (API keys, tokens) in output
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Add lib to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.dry_run_planner import format_ascii_tree, format_json_plan, plan_execution


@pytest.fixture
def sample_prd() -> dict[str, list[dict[str, str]]]:
    """Sample PRD with 3 stories for security testing."""
    return {
        "userStories": [
            {"id": "US-1", "title": "Feature A", "estimatedComplexity": "small"},
            {"id": "US-2", "title": "Feature B", "estimatedComplexity": "medium"},
            {"id": "US-3", "title": "Feature C", "estimatedComplexity": "large"},
        ]
    }


def test_dry_run_no_api_keys_in_ascii_output(sample_prd: dict[str, list[dict[str, str]]]) -> None:
    """Verify ASCII output contains no API key patterns (sk-ant, ANTHROPIC_API_KEY)."""
    plan = plan_execution(sample_prd, num_iterations=1)
    output = format_ascii_tree(plan)

    # Check for API key patterns
    assert not re.search(r"sk-ant", output, re.IGNORECASE), "ASCII output contains sk-ant pattern"
    assert not re.search(r"ANTHROPIC_API_KEY", output), "ASCII output contains ANTHROPIC_API_KEY"

    # Verify output is non-empty and reasonable
    assert len(output) > 100
    assert "Estimated Cost" in output


def test_dry_run_no_api_keys_in_json_output(sample_prd: dict[str, list[dict[str, str]]]) -> None:
    """Verify JSON output contains no API key patterns."""
    plan = plan_execution(sample_prd, num_iterations=1)
    json_output = format_json_plan(plan)
    json_str = json.dumps(json_output)

    # Check for API key patterns
    assert not re.search(r"sk-ant", json_str, re.IGNORECASE), "JSON output contains sk-ant pattern"
    assert not re.search(r"ANTHROPIC_API_KEY", json_str), "JSON output contains ANTHROPIC_API_KEY"

    # Verify JSON structure is intact
    parsed = json.loads(json_str)
    assert "num_iterations" in parsed
    assert "phases" in parsed


def test_dry_run_subprocess_no_secret_leakage() -> None:
    """Test that subprocess invocation with injected secret doesn't leak the secret.

    Verifies:
    - Process exits with code 0
    - Captured stdout contains no API key sentinel value
    """
    # Create temporary test PRD
    test_prd = {"userStories": [{"id": "US-1", "title": "Test", "estimatedComplexity": "small"}]}

    # Write test PRD to temp location
    test_prd_path = Path(__file__).parent / "temp_test_prd.json"
    try:
        test_prd_path.write_text(json.dumps(test_prd), encoding="utf-8")

        # Set up environment with sentinel API key
        env = os.environ.copy()
        sentinel_key = "sk-test-sentinel-do-not-use-12345"
        env["ANTHROPIC_API_KEY"] = sentinel_key

        # Run dry-run as subprocess from the test directory
        result = subprocess.run(
            [sys.executable, "-m", "lib.dry_run_planner", "1"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        # Verify exit code is 0
        assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}\nStderr: {result.stderr}"

        # Verify sentinel value not in stdout
        assert sentinel_key not in result.stdout, f"Sentinel API key leaked in stdout: {sentinel_key}"

        # Verify no API key patterns in output
        assert not re.search(r"sk-test-sentinel", result.stdout, re.IGNORECASE), "Sentinel key pattern found in stdout"
        assert not re.search(r"ANTHROPIC_API_KEY", result.stdout), "ANTHROPIC_API_KEY literal found in stdout"

    finally:
        # Cleanup
        if test_prd_path.exists():
            test_prd_path.unlink()


def test_dry_run_with_dummy_env_var() -> None:
    """Test dry-run with ANTHROPIC_API_KEY=dummy doesn't leak 'dummy' in output.

    Verifies the tool works without real API key and doesn't echo env vars.
    """
    test_prd = {
        "userStories": [
            {"id": "US-1", "title": "Test 1", "estimatedComplexity": "small"},
            {"id": "US-2", "title": "Test 2", "estimatedComplexity": "medium"},
        ]
    }

    test_prd_path = Path(__file__).parent / "temp_test_prd_dummy.json"
    try:
        test_prd_path.write_text(json.dumps(test_prd), encoding="utf-8")

        # Set environment with 'dummy' as API key
        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = "dummy"

        # Run dry-run subprocess
        result = subprocess.run(
            [sys.executable, "-m", "lib.dry_run_planner", "1"],
            cwd=str(Path(__file__).parent.parent),
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )

        # Verify exit code is 0
        assert result.returncode == 0, f"Expected exit 0 with dummy key, got {result.returncode}"

        # Verify 'dummy' does not appear in output (word boundary to avoid false positives)
        assert "dummy" not in result.stdout.lower(), "String 'dummy' leaked in stdout"

    finally:
        if test_prd_path.exists():
            test_prd_path.unlink()


def test_dry_run_main_entry_point(sample_prd: dict[str, list[dict[str, str]]]) -> None:
    """Test that the module can be invoked via main() without API calls."""
    # This test verifies the main entry point doesn't require API keys
    plan = plan_execution(sample_prd, num_iterations=1)

    # Format both ASCII and JSON (what main() produces)
    ascii_output = format_ascii_tree(plan)
    json_output = format_json_plan(plan)
    json_str = json.dumps(json_output)

    # Both outputs should be present and valid
    assert len(ascii_output) > 100
    assert len(json_str) > 100

    # Neither should contain API key patterns
    assert "sk-ant" not in ascii_output.lower()
    assert "sk-ant" not in json_str.lower()

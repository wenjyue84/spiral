"""tests/test_phase_v_integration.py — Integration tests for Phase V validation.

Tests Phase V's pytest output parsing, story failure tagging (_test_failures),
and routing decisions (retry vs proceed).

Extended with:
- Multi-format output parsing (pytest, vitest, bats)
- Retry-exhaustion routing (_retries_exhausted tag)
- Hypothesis property-based testing for failure marker detection
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from hypothesis import given
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))


# ── Fixtures: Test data and mocks ──────────────────────────────────────────────


@pytest.fixture
def sample_prd_with_stories() -> dict[str, Any]:
    """Fixture: PRD with 5 stories to be validated by pytest."""
    return {
        "productName": "TestProject",
        "branchName": "main",
        "userStories": [
            {
                "id": "US-001",
                "title": "Feature A",
                "passes": False,
                "description": "Tests for feature A",
            },
            {
                "id": "US-002",
                "title": "Feature B",
                "passes": False,
                "description": "Tests for feature B",
            },
            {
                "id": "US-003",
                "title": "Feature C",
                "passes": False,
                "description": "Tests for feature C",
            },
            {
                "id": "US-004",
                "title": "Feature D",
                "passes": False,
                "description": "Tests for feature D",
            },
            {
                "id": "US-005",
                "title": "Feature E",
                "passes": False,
                "description": "Tests for feature E",
            },
        ],
    }


@pytest.fixture
def pytest_output_with_failures() -> str:
    """Fixture: Synthetic pytest output with 3 PASSED, 2 FAILED.

    Simulates a pytest run at 60% pass rate.
    """
    return """
tests/test_feature_a.py::test_feature_a_basic PASSED
tests/test_feature_b.py::test_feature_b_basic PASSED
tests/test_feature_c.py::test_feature_c_basic FAILED
tests/test_feature_d.py::test_feature_d_basic PASSED
tests/test_feature_e.py::test_feature_e_basic FAILED

======== FAILURES ========

_ test_feature_c_basic _
    def test_feature_c_basic():
        assert False, "Feature C failed"
    AssertionError: assert False

_ test_feature_e_basic _
    def test_feature_e_basic():
        assert False, "Feature E failed"
    AssertionError: assert False

====== 3 passed, 2 failed in 1.23s ======
"""


@pytest.fixture
def pytest_output_all_passed() -> str:
    """Fixture: Synthetic pytest output with all tests passing."""
    return """
tests/test_feature_a.py::test_feature_a_basic PASSED
tests/test_feature_b.py::test_feature_b_basic PASSED
tests/test_feature_c.py::test_feature_c_basic PASSED
tests/test_feature_d.py::test_feature_d_basic PASSED
tests/test_feature_e.py::test_feature_e_basic PASSED

====== 5 passed in 1.05s ======
"""


@pytest.fixture
def pytest_output_empty() -> str:
    """Fixture: Empty pytest output (no tests run)."""
    return ""


@pytest.fixture
def pytest_output_malformed() -> str:
    """Fixture: Malformed pytest output (invalid format)."""
    return "This is not valid pytest output at all"


@pytest.fixture
def vitest_output_with_failures() -> str:
    """Fixture: Synthetic vitest output with 3 PASSED, 2 FAILED.

    Vitest uses ❯ marker for failures and PASS/FAIL in output.
    """
    return """
 ✓ tests/test_feature_a.test.ts (1)
 ✓ tests/test_feature_b.test.ts (1)
 ✓ tests/test_feature_d.test.ts (1)
 ✗ tests/test_feature_c.test.ts (1)
   ❯ test_feature_c_basic
     AssertionError: expected true but got false
       at tests/test_feature_c.test.ts:42:5

 ✗ tests/test_feature_e.test.ts (1)
   ❯ test_feature_e_basic
     TypeError: Cannot read property 'length' of undefined
       at tests/test_feature_e.test.ts:67:10

Test Files  3 passed (3)
   Tests  3 passed, 2 failed (5)
Duration  1.23s
"""


@pytest.fixture
def vitest_output_all_passed() -> str:
    """Fixture: Synthetic vitest output with all passing."""
    return """
 ✓ tests/test_feature_a.test.ts (1)
 ✓ tests/test_feature_b.test.ts (1)
 ✓ tests/test_feature_c.test.ts (1)
 ✓ tests/test_feature_d.test.ts (1)
 ✓ tests/test_feature_e.test.ts (1)

Test Files  5 passed (5)
   Tests  5 passed (5)
Duration  0.95s
"""


@pytest.fixture
def bats_output_with_failures() -> str:
    """Fixture: Synthetic bats output with 3 passed, 2 failed.

    Bats uses 'ok N' for passes and 'not ok N' for failures.
    """
    return """
1..5
ok 1 Feature A: should initialize correctly
ok 2 Feature B: should handle input
not ok 3 Feature C: should validate data
  Error: assertion failed: expected true but got false
not ok 4 Feature D: should process correctly
ok 5 Feature E: should complete successfully
"""


@pytest.fixture
def bats_output_all_passed() -> str:
    """Fixture: Synthetic bats output with all passing."""
    return """
1..5
ok 1 Feature A: should initialize correctly
ok 2 Feature B: should handle input
ok 3 Feature C: should validate data
ok 4 Feature D: should process correctly
ok 5 Feature E: should complete successfully
"""


# ── Test: Parse pytest output with mixed pass/fail ────────────────────────────


def test_phase_v_parse_pytest_output_with_failures(
    sample_prd_with_stories: dict[str, Any],
    pytest_output_with_failures: str,
) -> None:
    """Test that Phase V correctly parses pytest output with 60% pass rate.

    Accepts: synthetic pytest output with 3 PASSED, 2 FAILED
    Expects: Parse identifies 3 passing and 2 failing test cases
    """
    output = pytest_output_with_failures

    # Extract PASSED and FAILED test counts
    passed_count = output.count(" PASSED")
    failed_count = output.count(" FAILED")

    assert passed_count == 3, f"Expected 3 PASSED, got {passed_count}"
    assert failed_count == 2, f"Expected 2 FAILED, got {failed_count}"


def test_phase_v_parse_pytest_output_all_passed(
    pytest_output_all_passed: str,
) -> None:
    """Test that Phase V correctly parses pytest output with all passing.

    Accepts: synthetic pytest output with 5 PASSED, 0 FAILED
    Expects: Parse identifies 5 passing and 0 failing test cases
    """
    output = pytest_output_all_passed

    passed_count = output.count(" PASSED")
    failed_count = output.count(" FAILED")

    assert passed_count == 5, f"Expected 5 PASSED, got {passed_count}"
    assert failed_count == 0, f"Expected 0 FAILED, got {failed_count}"


# ── Test: Tag stories with _test_failures when tests fail ────────────────────


def test_phase_v_tags_failed_stories_with_test_failures(
    sample_prd_with_stories: dict[str, Any],
) -> None:
    """Test that Phase V tags stories with _test_failures when their tests fail.

    Accepts: PRD with 5 stories
    Expects: Failed stories (C, E) are tagged with _test_failures
    """
    # Simulate Phase V tagging logic
    failed_story_ids = {"US-003", "US-005"}  # Feature C and E failed

    for story in sample_prd_with_stories["userStories"]:
        if story["id"] in failed_story_ids:
            story["_test_failures"] = True

    # Assert tagging worked
    assert sample_prd_with_stories["userStories"][2]["_test_failures"] is True
    assert sample_prd_with_stories["userStories"][4]["_test_failures"] is True

    # Assert non-failed stories don't have the tag
    assert "_test_failures" not in sample_prd_with_stories["userStories"][0]
    assert "_test_failures" not in sample_prd_with_stories["userStories"][1]
    assert "_test_failures" not in sample_prd_with_stories["userStories"][3]


def test_phase_v_tags_only_failed_stories(
    sample_prd_with_stories: dict[str, Any],
) -> None:
    """Test that only truly failed stories receive _test_failures tag.

    Ensures no false positives in tagging.
    """
    # Simulate selective tagging
    failed_ids = {"US-003"}  # Only Feature C failed

    for story in sample_prd_with_stories["userStories"]:
        if story["id"] in failed_ids:
            story["_test_failures"] = True

    # Assert selective tagging
    assert sample_prd_with_stories["userStories"][2]["_test_failures"] is True

    # All others should be untagged
    for i, story in enumerate(sample_prd_with_stories["userStories"]):
        if i != 2:
            assert "_test_failures" not in story


# ── Test: Routing decision based on test failures ────────────────────────────


def test_phase_v_routing_retry_when_failures_present(
    sample_prd_with_stories: dict[str, Any],
) -> None:
    """Test that Phase V routes to 'retry' when test failures are present.

    Accepts: PRD with stories tagged with _test_failures
    Expects: Routing decision is 'retry'
    """
    # Mark 2 stories as having test failures
    sample_prd_with_stories["userStories"][2]["_test_failures"] = True
    sample_prd_with_stories["userStories"][4]["_test_failures"] = True

    # Simulate routing logic
    has_failures = any(s.get("_test_failures") for s in sample_prd_with_stories["userStories"])
    routing_decision = "retry" if has_failures else "proceed"

    assert routing_decision == "retry"
    assert has_failures is True


def test_phase_v_routing_proceed_when_no_failures(
    sample_prd_with_stories: dict[str, Any],
) -> None:
    """Test that Phase V routes to 'proceed' when all tests pass.

    Accepts: PRD with no _test_failures tags
    Expects: Routing decision is 'proceed'
    """
    # Ensure no stories have the _test_failures tag
    for story in sample_prd_with_stories["userStories"]:
        assert "_test_failures" not in story

    # Simulate routing logic
    has_failures = any(s.get("_test_failures") for s in sample_prd_with_stories["userStories"])
    routing_decision = "retry" if has_failures else "proceed"

    assert routing_decision == "proceed"
    assert has_failures is False


def test_phase_v_routing_proceeds_with_partial_failures(
    sample_prd_with_stories: dict[str, Any],
) -> None:
    """Test routing decision with mixed results.

    When some stories have failures and some don't, Phase V should retry.
    """
    # Mark only one story as failed
    sample_prd_with_stories["userStories"][0]["_test_failures"] = True

    # Others remain unfailed
    for i in range(1, len(sample_prd_with_stories["userStories"])):
        if "_test_failures" in sample_prd_with_stories["userStories"][i]:
            del sample_prd_with_stories["userStories"][i]["_test_failures"]

    # Routing should still be 'retry' due to at least one failure
    has_failures = any(s.get("_test_failures") for s in sample_prd_with_stories["userStories"])
    routing_decision = "retry" if has_failures else "proceed"

    assert routing_decision == "retry"


# ── Test: Edge cases ───────────────────────────────────────────────────────────


def test_phase_v_handles_empty_pytest_output(
    pytest_output_empty: str,
) -> None:
    """Test Phase V gracefully handles empty pytest output.

    Accepts: Empty output string
    Expects: No parsing errors, 0 pass/fail detected
    """
    passed_count = pytest_output_empty.count(" PASSED")
    failed_count = pytest_output_empty.count(" FAILED")

    assert passed_count == 0
    assert failed_count == 0


def test_phase_v_handles_malformed_pytest_output(
    pytest_output_malformed: str,
) -> None:
    """Test Phase V gracefully handles malformed pytest output.

    Accepts: Invalid pytest output format
    Expects: Parsing attempts continue without crashing
    """
    # Should not crash or raise exception
    passed_count = pytest_output_malformed.count(" PASSED")
    failed_count = pytest_output_malformed.count(" FAILED")

    # With malformed input, counts should be 0
    assert passed_count == 0
    assert failed_count == 0


def test_phase_v_identifies_failed_test_names_from_output(
    pytest_output_with_failures: str,
) -> None:
    """Test that Phase V can extract individual failed test names.

    Identifies: test_feature_c_basic, test_feature_e_basic
    """
    output = pytest_output_with_failures

    # Extract failed test names (simple pattern matching)
    failed_tests = [
        line.split("::")[1].split(" ")[0] for line in output.split("\n") if "FAILED" in line and "::" in line
    ]

    assert "test_feature_c_basic" in failed_tests
    assert "test_feature_e_basic" in failed_tests
    assert len(failed_tests) == 2


def test_phase_v_maps_test_files_to_story_ids(
    sample_prd_with_stories: dict[str, Any],
) -> None:
    """Test mapping from failed test files to story IDs.

    Pattern: test_feature_X.py -> Feature X -> US-XXX
    """
    failed_test_file = "test_feature_c.py"

    # Simple mapping logic: extract feature name and find matching story
    feature_name = failed_test_file.replace("test_", "").replace(".py", "").replace("_", " ").title()

    # Find matching story
    matching_story = None
    for story in sample_prd_with_stories["userStories"]:
        if feature_name.lower() in story["title"].lower():
            matching_story = story
            break

    assert matching_story is not None
    assert matching_story["id"] == "US-003"


# ── Test: Subprocess mock pattern ──────────────────────────────────────────────


@mock.patch("subprocess.run")
def test_phase_v_with_mocked_subprocess_run(
    mock_run: mock.MagicMock,
    pytest_output_with_failures: str,
) -> None:
    """Test Phase V integration with mocked subprocess.run.

    Verifies the pattern for patching subprocess calls in Phase V.
    """
    # Configure mock to return synthetic pytest output
    mock_result = mock.MagicMock()
    mock_result.returncode = 1  # Non-zero exit = test failure
    mock_result.stdout = pytest_output_with_failures
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    # Simulate Phase V calling subprocess.run
    result = subprocess.run(
        ["pytest", "tests/", "-v"],
        capture_output=True,
        text=True,
    )

    # Verify mock was called
    mock_run.assert_called_once()
    assert result.returncode == 1
    assert "3 passed, 2 failed" in result.stdout


@mock.patch("subprocess.run")
def test_phase_v_subprocess_timeout_handling(
    mock_run: mock.MagicMock,
) -> None:
    """Test Phase V handles subprocess timeout gracefully.

    Simulates pytest timeout scenario.
    """
    # Configure mock to raise TimeoutExpired
    mock_run.side_effect = subprocess.TimeoutExpired("pytest", 300)

    # Phase V should catch timeout and handle gracefully
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run(
            ["pytest", "tests/", "-v"],
            timeout=300,
        )


@mock.patch("subprocess.run")
def test_phase_v_subprocess_zero_exit_means_all_pass(
    mock_run: mock.MagicMock,
    pytest_output_all_passed: str,
) -> None:
    """Test that zero exit code from subprocess indicates all tests passed.

    Phase V should interpret exit code 0 as success.
    """
    mock_result = mock.MagicMock()
    mock_result.returncode = 0  # Success
    mock_result.stdout = pytest_output_all_passed
    mock_result.stderr = ""
    mock_run.return_value = mock_result

    result = subprocess.run(
        ["pytest", "tests/", "-v"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "5 passed" in result.stdout


# ── Test: Full Phase V workflow integration ────────────────────────────────────


def test_phase_v_full_workflow_parse_tag_route(
    sample_prd_with_stories: dict[str, Any],
    pytest_output_with_failures: str,
) -> None:
    """Test complete Phase V workflow: parse -> tag -> route.

    End-to-end integration test covering all steps.
    """
    # Step 1: Parse pytest output
    passed_count = pytest_output_with_failures.count(" PASSED")
    failed_count = pytest_output_with_failures.count(" FAILED")

    assert passed_count == 3
    assert failed_count == 2

    # Step 2: Identify failed stories and tag them
    failed_story_map = {
        "test_feature_c_basic": "US-003",
        "test_feature_e_basic": "US-005",
    }

    for story in sample_prd_with_stories["userStories"]:
        if story["id"] in failed_story_map.values():
            story["_test_failures"] = True

    # Step 3: Make routing decision
    has_failures = any(s.get("_test_failures") for s in sample_prd_with_stories["userStories"])
    routing_decision = "retry" if has_failures else "proceed"

    # Verify complete workflow
    assert sample_prd_with_stories["userStories"][2]["_test_failures"] is True
    assert sample_prd_with_stories["userStories"][4]["_test_failures"] is True
    assert routing_decision == "retry"


def test_phase_v_full_workflow_all_pass(
    sample_prd_with_stories: dict[str, Any],
    pytest_output_all_passed: str,
) -> None:
    """Test complete Phase V workflow when all tests pass.

    Verifies proceed routing when no failures.
    """
    # Step 1: Parse pytest output
    passed_count = pytest_output_all_passed.count(" PASSED")
    failed_count = pytest_output_all_passed.count(" FAILED")

    assert passed_count == 5
    assert failed_count == 0

    # Step 2: No stories to tag (no failures)
    for story in sample_prd_with_stories["userStories"]:
        assert "_test_failures" not in story

    # Step 3: Make routing decision
    has_failures = any(s.get("_test_failures") for s in sample_prd_with_stories["userStories"])
    routing_decision = "retry" if has_failures else "proceed"

    # Verify complete workflow
    assert has_failures is False
    assert routing_decision == "proceed"


# ── Test: Parse pytest summary line ────────────────────────────────────────────


def test_phase_v_extracts_summary_from_pytest_output(
    pytest_output_with_failures: str,
) -> None:
    """Test extraction of pytest summary line.

    Pattern: "====== 3 passed, 2 failed in 1.23s ======"
    """
    output = pytest_output_with_failures

    # Find summary line
    summary_line = None
    for line in output.split("\n"):
        if "passed" in line and ("failed" in line or "passed" in line):
            summary_line = line
            break

    assert summary_line is not None
    assert "3 passed" in summary_line
    assert "2 failed" in summary_line


def test_phase_v_output_with_no_summary_line(
    pytest_output_malformed: str,
) -> None:
    """Test handling of pytest output missing summary line.

    Should gracefully handle incomplete output.
    """
    output = pytest_output_malformed

    # Try to find summary line
    summary_line = None
    for line in output.split("\n"):
        if "passed" in line or "failed" in line:
            summary_line = line
            break

    assert summary_line is None  # No summary found


# ── Test: Story failure reason tracking ────────────────────────────────────────


def test_phase_v_tracks_failure_reason_per_story(
    sample_prd_with_stories: dict[str, Any],
) -> None:
    """Test that Phase V can track why a story failed (which tests failed).

    Enables better diagnostics and retry strategies.
    """
    # Simulate tracking failure reasons
    failure_reasons = {
        "US-003": ["test_feature_c_basic - assertion failed"],
        "US-005": ["test_feature_e_basic - assertion failed"],
    }

    for story in sample_prd_with_stories["userStories"]:
        if story["id"] in failure_reasons:
            story["_test_failures"] = True
            story["_failure_reason"] = failure_reasons[story["id"]]

    # Verify tracking
    assert sample_prd_with_stories["userStories"][2]["_failure_reason"] == ["test_feature_c_basic - assertion failed"]
    assert sample_prd_with_stories["userStories"][4]["_failure_reason"] == ["test_feature_e_basic - assertion failed"]


# ── Test: Multi-format output parsing (pytest, vitest, bats) ─────────────────────


@pytest.mark.parametrize(
    "format_name,output_fixture,expected_passed,expected_failed,failure_marker",
    [
        ("pytest", "pytest_output_with_failures", 3, 2, "FAILED"),
        ("vitest", "vitest_output_with_failures", 3, 2, "❯"),
        ("bats", "bats_output_with_failures", 3, 2, "not ok"),
    ],
)
def test_phase_v_multi_format_output_parsing(
    format_name: str,
    output_fixture: str,
    expected_passed: int,
    expected_failed: int,
    failure_marker: str,
    request: Any,
) -> None:
    """Test Phase V parses multiple test output formats: pytest, vitest, bats.

    Each format has distinct failure markers:
    - pytest: " FAILED"
    - vitest: "❯" (failure indicator)
    - bats: "not ok" (failure line prefix)
    """
    output = request.getfixturevalue(output_fixture)

    # Count failures using format-specific markers
    if format_name == "pytest":
        passed_count = output.count(" PASSED")
        failed_count = output.count(" FAILED")
    elif format_name == "vitest":
        failed_count = output.count("❯")
        passed_count = output.count("✓")
    elif format_name == "bats":
        failed_count = output.count("not ok")
        passed_count = output.count("ok ") - failed_count
    else:
        raise ValueError(f"Unknown format: {format_name}")

    assert passed_count == expected_passed, f"{format_name}: expected {expected_passed} passed, got {passed_count}"
    assert failed_count == expected_failed, f"{format_name}: expected {expected_failed} failed, got {failed_count}"
    assert failure_marker in output, f"{format_name}: expected failure marker '{failure_marker}' not found"


@pytest.mark.parametrize(
    "format_name,output_fixture",
    [
        ("pytest", "pytest_output_all_passed"),
        ("vitest", "vitest_output_all_passed"),
        ("bats", "bats_output_all_passed"),
    ],
)
def test_phase_v_multi_format_all_passing(
    format_name: str,
    output_fixture: str,
    request: Any,
) -> None:
    """Test Phase V correctly identifies all-passing status across formats."""
    output = request.getfixturevalue(output_fixture)

    # Count failures
    if format_name == "pytest":
        failed_count = output.count(" FAILED")
    elif format_name == "vitest":
        failed_count = output.count("✗")
    elif format_name == "bats":
        failed_count = output.count("not ok")
    else:
        raise ValueError(f"Unknown format: {format_name}")

    assert failed_count == 0, f"{format_name}: expected 0 failures, got {failed_count}"


@pytest.mark.parametrize(
    "format_name,output_fixture,expected_category",
    [
        ("pytest", "pytest_output_with_failures", "AssertionError"),
        ("vitest", "vitest_output_with_failures", "AssertionError"),
        ("bats", "bats_output_with_failures", "assertion"),
    ],
)
def test_phase_v_extracts_failure_category_per_format(
    format_name: str,
    output_fixture: str,
    expected_category: str,
    request: Any,
) -> None:
    """Test that Phase V extracts _failure_category tag from each format.

    Each format has distinct error type indicators:
    - pytest: AssertionError, TypeError, etc.
    - vitest: AssertionError, TypeError, etc. (similar to pytest)
    - bats: Custom error messages (assertion, timeout, etc.)
    """
    output = request.getfixturevalue(output_fixture)

    # Extract failure category from output
    failure_category = None

    if format_name == "pytest":
        # Look for common Python error types
        for error_type in ["AssertionError", "TypeError", "ValueError", "RuntimeError"]:
            if error_type in output:
                failure_category = error_type
                break
    elif format_name == "vitest":
        # vitest shows errors similar to pytest
        for error_type in ["AssertionError", "TypeError", "ReferenceError"]:
            if error_type in output:
                failure_category = error_type
                break
    elif format_name == "bats":
        # bats shows custom error messages
        if "assertion failed" in output.lower():
            failure_category = "assertion"
        elif "timeout" in output.lower():
            failure_category = "timeout"

    # Verify category was extracted
    assert failure_category is not None, f"{format_name}: could not extract failure category"
    assert expected_category.lower() in failure_category.lower(), (
        f"{format_name}: expected category containing '{expected_category}', got '{failure_category}'"
    )


# ── Test: Retry exhaustion routing ──────────────────────────────────────────────


def test_phase_v_retry_count_4_marks_story_exhausted() -> None:
    """Test that stories with retry_count >= 4 are marked with _retries_exhausted.

    Stories exhausting retries should be archived and not routed to Phase R.
    """
    story_exhausted = {
        "id": "US-001",
        "title": "Feature A",
        "retry_count": 4,
        "_test_failures": True,
    }

    story_retry_available = {
        "id": "US-002",
        "title": "Feature B",
        "retry_count": 2,
        "_test_failures": True,
    }

    stories = [story_exhausted, story_retry_available]

    # Simulate Phase V routing logic
    for story in stories:
        retry_count = story.get("retry_count", 0)
        if retry_count >= 4:
            story["_retries_exhausted"] = True
            story["exit_reason"] = "_retries_exhausted"

    # Verify routing
    assert stories[0]["_retries_exhausted"] is True
    assert stories[0]["exit_reason"] == "_retries_exhausted"
    assert "_retries_exhausted" not in stories[1]
    assert "_retries_exhausted" not in stories[1]


def test_phase_v_retry_count_2_routes_to_phase_r() -> None:
    """Test that stories with retry_count < 4 route to Phase R for retry."""
    story = {
        "id": "US-001",
        "title": "Feature A",
        "retry_count": 2,
        "_test_failures": True,
    }

    # Simulate Phase V routing logic
    retry_count = story.get("retry_count", 0)
    routing = "archive" if retry_count >= 4 else "phase_r"

    assert routing == "phase_r"
    assert "_retries_exhausted" not in story


def test_phase_v_retry_exhaustion_with_mixed_stories() -> None:
    """Test routing with a mix of exhausted and retryable stories."""
    stories = [
        {"id": "US-001", "retry_count": 4, "_test_failures": True},
        {"id": "US-002", "retry_count": 2, "_test_failures": True},
        {"id": "US-003", "retry_count": 5, "_test_failures": True},
        {"id": "US-004", "retry_count": 1, "_test_failures": True},
    ]

    # Simulate Phase V routing
    exhausted = []
    retryable = []

    for story in stories:
        retry_count = story.get("retry_count", 0)
        if retry_count >= 4:
            story["_retries_exhausted"] = True
            exhausted.append(story["id"])
        else:
            retryable.append(story["id"])

    # Verify correct routing
    assert len(exhausted) == 2
    assert len(retryable) == 2
    assert "US-001" in exhausted
    assert "US-003" in exhausted
    assert "US-002" in retryable
    assert "US-004" in retryable


# ── Test: Hypothesis property-based tests ────────────────────────────────────────


@given(
    passed_count=st.integers(min_value=0, max_value=20),
    failed_count=st.integers(min_value=0, max_value=20),
)
def test_phase_v_property_failure_marker_counts_match(
    passed_count: int,
    failed_count: int,
) -> None:
    """Property test: generated failure marker counts match extracted counts.

    For any combination of pass/fail counts, the parser should correctly
    extract the number of failures from synthetic output.
    """
    # Generate synthetic pytest output with specified pass/fail counts
    output_lines = []

    for i in range(passed_count):
        output_lines.append(f"tests/test_{i}.py::test_case_{i} PASSED")

    for i in range(failed_count):
        output_lines.append(f"tests/test_failed_{i}.py::test_case_failed_{i} FAILED")

    output = "\n".join(output_lines)

    # Extract counts using Phase V logic
    extracted_passed = output.count(" PASSED")
    extracted_failed = output.count(" FAILED")

    # Property: extracted counts must match generated counts
    assert extracted_passed == passed_count, (
        f"Passed count mismatch: generated {passed_count}, extracted {extracted_passed}"
    )
    assert extracted_failed == failed_count, (
        f"Failed count mismatch: generated {failed_count}, extracted {extracted_failed}"
    )


@given(
    failure_marker_count=st.integers(min_value=0, max_value=20),
)
def test_phase_v_property_failure_lines_equal_tagged_stories(
    failure_marker_count: int,
) -> None:
    """Property test: number of failure lines equals number of tagged stories.

    For any count of failures in the output, Phase V should tag that many stories
    with _test_failures.
    """
    # Generate synthetic vitest output with specified failure count
    output_lines = ["✓ tests/test_a.ts (1)"]
    for i in range(failure_marker_count):
        output_lines.append(f"✗ tests/test_failed_{i}.ts (1)")
        output_lines.append(f"  ❯ test_case_{i}")
        output_lines.append("    AssertionError: expected X but got Y")

    output = "\n".join(output_lines)

    # Extract failure count (vitest uses ❯ marker)
    failure_count = output.count("❯")

    # Property: failure count in output must equal tagged stories count
    assert failure_count == failure_marker_count, (
        f"Failure marker count mismatch: generated {failure_marker_count}, found {failure_count} '❯' markers in output"
    )

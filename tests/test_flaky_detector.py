"""Tests for lib/flaky_detector.py — Flaky Test Detection (US-774)"""

import json
import os

# Import the module under test
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from flaky_detector import (
    get_flaky_tests,
    get_flaky_tests_with_rates,
    is_flaky_test,
    record_test_result,
)


@pytest.fixture
def tmp_spiral_home():
    """Create a temporary SPIRAL_HOME directory for testing."""
    with tempfile.TemporaryDirectory() as tmp:
        yield tmp


def test_record_test_result_creates_history_file(tmp_spiral_home):
    """AC: record_test_result() creates .spiral/test_failure_history.json"""
    test_id = "tests.unit.test_example.test_basic"
    record_test_result(test_id, True, spiral_home=tmp_spiral_home)

    history_file = os.path.join(tmp_spiral_home, ".spiral", "test_failure_history.json")
    assert os.path.isfile(history_file), "History file should be created"

    with open(history_file) as f:
        history = json.load(f)
    assert test_id in history
    assert history[test_id]["results"] == [1]  # 1 = pass


def test_record_test_result_pass_fail(tmp_spiral_home):
    """AC: record_test_result() tracks passes and failures correctly"""
    test_id = "tests.unit.test_example.test_func"
    record_test_result(test_id, True, spiral_home=tmp_spiral_home)
    record_test_result(test_id, False, spiral_home=tmp_spiral_home)
    record_test_result(test_id, True, spiral_home=tmp_spiral_home)

    history_file = os.path.join(tmp_spiral_home, ".spiral", "test_failure_history.json")
    with open(history_file) as f:
        history = json.load(f)

    assert history[test_id]["results"] == [1, 0, 1]  # pass, fail, pass


def test_is_flaky_test_with_insufficient_history(tmp_spiral_home):
    """AC: is_flaky_test() returns False when < window_size results exist"""
    test_id = "tests.unit.test_example.test_insufficient"
    # Only 3 results, window_size is 5 by default
    record_test_result(test_id, True, spiral_home=tmp_spiral_home)
    record_test_result(test_id, False, spiral_home=tmp_spiral_home)
    record_test_result(test_id, True, spiral_home=tmp_spiral_home)

    assert not is_flaky_test(test_id, window_size=5, spiral_home=tmp_spiral_home)


def test_is_flaky_test_failing_once_in_five(tmp_spiral_home):
    """AC: test failing 1/5 iterations is flaky (20% failure rate < 50% threshold)"""
    test_id = "tests.unit.test_example.test_one_fail"
    # Record 5 results: 1 fail, 4 pass = 20% failure rate (flaky)
    record_test_result(test_id, True, spiral_home=tmp_spiral_home)
    record_test_result(test_id, True, spiral_home=tmp_spiral_home)
    record_test_result(test_id, False, spiral_home=tmp_spiral_home)
    record_test_result(test_id, True, spiral_home=tmp_spiral_home)
    record_test_result(test_id, True, spiral_home=tmp_spiral_home)

    assert is_flaky_test(test_id, window_size=5, threshold=0.5, spiral_home=tmp_spiral_home)


def test_is_flaky_test_failing_three_in_five(tmp_spiral_home):
    """Test failing 3/5 (60%) is NOT flaky when threshold is 0.5"""
    test_id = "tests.unit.test_example.test_not_flaky"
    # Record 5 results: 3 fail, 2 pass = 60% failure rate (not flaky, >= 0.5)
    record_test_result(test_id, True, spiral_home=tmp_spiral_home)
    record_test_result(test_id, False, spiral_home=tmp_spiral_home)
    record_test_result(test_id, False, spiral_home=tmp_spiral_home)
    record_test_result(test_id, True, spiral_home=tmp_spiral_home)
    record_test_result(test_id, False, spiral_home=tmp_spiral_home)

    assert not is_flaky_test(test_id, window_size=5, threshold=0.5, spiral_home=tmp_spiral_home)


def test_get_flaky_tests_returns_all_flaky(tmp_spiral_home):
    """AC: get_flaky_tests() returns list of all flaky tests"""
    # Record 3 tests: 2 flaky, 1 not flaky
    test_ids = [
        "tests.unit.test_a.test_flaky1",
        "tests.unit.test_b.test_flaky2",
        "tests.unit.test_c.test_stable",
    ]

    # Flaky 1: fails 1/5 times
    for _ in range(4):
        record_test_result(test_ids[0], True, spiral_home=tmp_spiral_home)
    record_test_result(test_ids[0], False, spiral_home=tmp_spiral_home)

    # Flaky 2: fails 2/5 times
    for _ in range(3):
        record_test_result(test_ids[1], True, spiral_home=tmp_spiral_home)
    for _ in range(2):
        record_test_result(test_ids[1], False, spiral_home=tmp_spiral_home)

    # Stable: fails 0/5 times
    for _ in range(5):
        record_test_result(test_ids[2], True, spiral_home=tmp_spiral_home)

    flaky = get_flaky_tests(window_size=5, threshold=0.5, spiral_home=tmp_spiral_home)
    assert len(flaky) == 2
    assert test_ids[0] in flaky
    assert test_ids[1] in flaky
    assert test_ids[2] not in flaky


def test_get_flaky_tests_with_rates(tmp_spiral_home):
    """AC: get_flaky_tests_with_rates() returns test names with failure rates"""
    test_id = "tests.unit.test_rates.test_example"
    # Fail 1/5: 20% failure rate
    for _ in range(4):
        record_test_result(test_id, True, spiral_home=tmp_spiral_home)
    record_test_result(test_id, False, spiral_home=tmp_spiral_home)

    results = get_flaky_tests_with_rates(window_size=5, threshold=0.5, spiral_home=tmp_spiral_home)
    assert len(results) == 1
    test_id_result, rate = results[0]
    assert test_id_result == test_id
    assert abs(rate - 0.2) < 0.01  # 20% failure rate


def test_flaky_detector_excluded_from_story_generation(tmp_spiral_home):
    """Integration: Phase T should exclude flaky tests from story generation"""
    # This test verifies the end-to-end flow: record results → mark flaky → exclude from synthesis
    test_id = "tests.unit.test_integration.test_example"

    # Simulate 5 iterations: test fails only once
    for _ in range(4):
        record_test_result(test_id, True, spiral_home=tmp_spiral_home)
    record_test_result(test_id, False, spiral_home=tmp_spiral_home)

    # Verify it's marked flaky
    assert is_flaky_test(test_id, window_size=5, threshold=0.5, spiral_home=tmp_spiral_home)

    # Verify it appears in flaky list
    flaky = get_flaky_tests(window_size=5, threshold=0.5, spiral_home=tmp_spiral_home)
    assert test_id in flaky


def test_is_flaky_test_missing_test_id(tmp_spiral_home):
    """Edge case: is_flaky_test() returns False for unknown test ID"""
    unknown_test = "tests.unit.test_does_not_exist.test_never_recorded"
    assert not is_flaky_test(unknown_test, spiral_home=tmp_spiral_home)


def test_get_flaky_tests_empty_history(tmp_spiral_home):
    """Edge case: get_flaky_tests() returns [] when no history exists"""
    flaky = get_flaky_tests(spiral_home=tmp_spiral_home)
    assert flaky == []


def test_record_test_result_multiple_tests_in_one_file(tmp_spiral_home):
    """AC: Multiple test IDs are tracked independently"""
    test_ids = ["tests.unit.test_a.test_1", "tests.unit.test_b.test_2", "tests.unit.test_c.test_3"]

    for test_id in test_ids:
        record_test_result(test_id, True, spiral_home=tmp_spiral_home)
    record_test_result(test_ids[0], False, spiral_home=tmp_spiral_home)

    history_file = os.path.join(tmp_spiral_home, ".spiral", "test_failure_history.json")
    with open(history_file) as f:
        history = json.load(f)

    assert history[test_ids[0]]["results"] == [1, 0]
    assert history[test_ids[1]]["results"] == [1]
    assert history[test_ids[2]]["results"] == [1]

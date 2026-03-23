"""Tests for lib/test_failure_clustering.py"""

import pytest
from lib.test_failure_clustering import extract_source_file, cluster_failures


def test_extract_source_file():
    """Test source file extraction from test ID."""
    test_id = "tests.unit.merge.test_merge.TestMergeFunctions.test_dedup"
    result = extract_source_file(test_id)
    assert result == "tests/unit/merge/test_merge.py"


def test_cluster_3_failures_same_source():
    """Test that 3+ failures from same source produce 1 clustered story."""
    stories = [
        {
            "title": "Fix failing test: test_foo",
            "priority": "medium",
            "description": "Test test_foo failing",
            "acceptanceCriteria": ["Test passes"],
            "technicalNotes": ["Test: tests.unit.test_merge.test_foo"],
            "dependencies": [],
            "estimatedComplexity": "small",
            "_source": "test-synthesis:tests.unit.test_merge.TestMerge.test_foo",
        },
        {
            "title": "Fix failing test: test_bar",
            "priority": "medium",
            "description": "Test test_bar failing",
            "acceptanceCriteria": ["Test passes"],
            "technicalNotes": ["Test: tests.unit.test_merge.test_bar"],
            "dependencies": [],
            "estimatedComplexity": "small",
            "_source": "test-synthesis:tests.unit.test_merge.TestMerge.test_bar",
        },
        {
            "title": "Fix failing test: test_baz",
            "priority": "medium",
            "description": "Test test_baz failing",
            "acceptanceCriteria": ["Test passes"],
            "technicalNotes": ["Test: tests.unit.test_merge.test_baz"],
            "dependencies": [],
            "estimatedComplexity": "small",
            "_source": "test-synthesis:tests.unit.test_merge.TestMerge.test_baz",
        },
    ]

    result = cluster_failures(stories)

    # Should produce 1 clustered story, not 3
    assert len(result) == 1
    assert "[Root Cause]" in result[0]["title"]
    assert "test_merge" in result[0]["title"]
    assert "3 test failures" in result[0]["title"]
    assert "_clustered_from" in result[0]
    assert len(result[0]["_clustered_from"]) == 3


def test_cluster_2_failures_stay_separate():
    """Test that <3 failures from same source stay individual."""
    stories = [
        {
            "title": "Fix failing test: test_foo",
            "priority": "medium",
            "description": "Test failing",
            "acceptanceCriteria": ["Test passes"],
            "technicalNotes": [],
            "dependencies": [],
            "estimatedComplexity": "small",
            "_source": "test-synthesis:tests.unit.test_merge.TestMerge.test_foo",
        },
        {
            "title": "Fix failing test: test_bar",
            "priority": "medium",
            "description": "Test failing",
            "acceptanceCriteria": ["Test passes"],
            "technicalNotes": [],
            "dependencies": [],
            "estimatedComplexity": "small",
            "_source": "test-synthesis:tests.unit.test_merge.TestMerge.test_bar",
        },
    ]

    result = cluster_failures(stories)

    # Should keep both stories separate
    assert len(result) == 2
    for story in result:
        assert "[Root Cause]" not in story["title"]


def test_cluster_mixed_sources():
    """Test clustering with failures from multiple sources."""
    stories = [
        # 3 from test_merge
        {
            "title": "Test 1",
            "_source": "test-synthesis:tests.unit.test_merge.TestMerge.test_1",
            "priority": "medium",
            "description": "Test",
            "acceptanceCriteria": [],
            "technicalNotes": [],
            "dependencies": [],
            "estimatedComplexity": "small",
        },
        {
            "title": "Test 2",
            "_source": "test-synthesis:tests.unit.test_merge.TestMerge.test_2",
            "priority": "medium",
            "description": "Test",
            "acceptanceCriteria": [],
            "technicalNotes": [],
            "dependencies": [],
            "estimatedComplexity": "small",
        },
        {
            "title": "Test 3",
            "_source": "test-synthesis:tests.unit.test_merge.TestMerge.test_3",
            "priority": "medium",
            "description": "Test",
            "acceptanceCriteria": [],
            "technicalNotes": [],
            "dependencies": [],
            "estimatedComplexity": "small",
        },
        # 2 from test_decompose (stay separate)
        {
            "title": "Test 4",
            "_source": "test-synthesis:tests.unit.test_decompose.TestDecompose.test_4",
            "priority": "high",
            "description": "Test",
            "acceptanceCriteria": [],
            "technicalNotes": [],
            "dependencies": [],
            "estimatedComplexity": "small",
        },
        {
            "title": "Test 5",
            "_source": "test-synthesis:tests.unit.test_decompose.TestDecompose.test_5",
            "priority": "high",
            "description": "Test",
            "acceptanceCriteria": [],
            "technicalNotes": [],
            "dependencies": [],
            "estimatedComplexity": "small",
        },
    ]

    result = cluster_failures(stories)

    # Should have 1 clustered (from test_merge) + 2 individual (from test_decompose)
    assert len(result) == 3
    clustered = [s for s in result if "[Root Cause]" in s["title"]]
    assert len(clustered) == 1
    assert "3 test failures" in clustered[0]["title"]

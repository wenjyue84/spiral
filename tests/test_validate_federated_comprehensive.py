"""Comprehensive integration tests for validate-federated CLI (US-626).

Tests all error types caught by validate_federated:
- AC1: missing story.description, malformed ID, orphan story with unresolved dep
- AC2: circular dependency with full cycle path reported
- AC3: error messages are actionable (include story ID and fix suggestion)
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib" / "commands"))
from validate_federated import validate_federated

# ── AC1: Invalid inputs detected ─────────────────────────────────────────────


def test_missing_description_is_detected(tmp_path: Path) -> None:
    """AC1: Story without description field triggers actionable error."""
    prd_data = {
        "schemaVersion": 1,
        "userStories": [
            {"id": "repo-a:US-001", "title": "Story missing description"},
        ],
    }
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

    report = validate_federated(prd_file)

    assert report["valid"] is False
    assert len(report["errors"]) > 0
    # Error must include story ID
    assert any("repo-a:US-001" in e for e in report["errors"])
    # Error must include fix suggestion
    assert any("description" in e.lower() for e in report["errors"])


def test_malformed_id_invalid_namespace(tmp_path: Path) -> None:
    """AC1: Malformed ID 'US-111-xyz' (invalid namespace) triggers error with fix suggestion."""
    prd_data = {
        "schemaVersion": 1,
        "userStories": [
            {
                "id": "US-111-xyz",
                "title": "Malformed ID story",
                "description": "A story with a malformed ID",
            },
        ],
    }
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

    report = validate_federated(prd_file)

    assert report["valid"] is False
    assert len(report["errors"]) > 0
    # Error must identify the bad ID
    assert any("US-111-xyz" in e for e in report["errors"])
    # Error must include a fix suggestion (e.g., expected format)
    assert any("Fix" in e or "expected" in e.lower() for e in report["errors"])


def test_orphan_story_unresolved_dependency(tmp_path: Path) -> None:
    """AC1: Story depending on non-existent ID (orphan) is reported with story ID."""
    prd_data = {
        "schemaVersion": 1,
        "userStories": [
            {
                "id": "repo-a:US-001",
                "title": "Orphan story",
                "description": "Story with no resolvable parent dependency",
                "dependencies": ["repo-b:US-999"],  # does not exist
            },
        ],
    }
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

    report = validate_federated(prd_file)

    assert report["valid"] is False
    assert len(report["errors"]) > 0
    # Error must reference both the orphan story and the missing dep
    assert any("repo-a:US-001" in e for e in report["errors"])
    assert any("repo-b:US-999" in e for e in report["errors"])


# ── AC2: Circular dependency with full cycle path ─────────────────────────────


def test_circular_dependency_full_cycle_path(tmp_path: Path) -> None:
    """AC2: US-111-a depends on US-201-b depends on US-111-a → cycle path reported."""
    prd_data = {
        "schemaVersion": 1,
        "userStories": [
            {
                "id": "US-111-a",
                "title": "Story A",
                "description": "Part of circular dependency",
                "dependencies": ["US-201-b"],
            },
            {
                "id": "US-201-b",
                "title": "Story B",
                "description": "Part of circular dependency",
                "dependencies": ["US-111-a"],
            },
        ],
    }
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

    report = validate_federated(prd_file)

    assert report["valid"] is False
    assert len(report["cycles"]) > 0, "Should detect at least one cycle"

    # Cycle path must contain both story IDs
    cycle = report["cycles"][0]
    cycle_ids = set(cycle)
    assert "US-111-a" in cycle_ids, "Cycle must include US-111-a"
    assert "US-201-b" in cycle_ids, "Cycle must include US-201-b"

    # Cycle must start and end with the same node (full path)
    assert cycle[0] == cycle[-1], "Cycle path must start and end with same node"

    # Cycle path length: 2 nodes + repeated start = 3 elements
    assert len(cycle) == 3, f"Expected cycle [A, B, A] length 3, got {cycle}"


# ── AC3: All error types are actionable ───────────────────────────────────────


def test_all_error_types_are_actionable(tmp_path: Path) -> None:
    """AC3: All error messages include story ID and fix suggestion."""
    prd_data = {
        "schemaVersion": 1,
        "userStories": [
            # Missing description
            {"id": "repo-a:US-001", "title": "No description"},
            # Malformed ID
            {
                "id": "US-111-xyz",
                "title": "Bad ID",
                "description": "Has malformed ID",
            },
            # Orphan (unresolved dependency)
            {
                "id": "repo-b:US-002",
                "title": "Orphan",
                "description": "Depends on missing story",
                "dependencies": ["repo-c:US-999"],
            },
        ],
    }
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(json.dumps(prd_data), encoding="utf-8")

    report = validate_federated(prd_file)

    assert report["valid"] is False
    errors = report["errors"]
    assert len(errors) >= 3, f"Expected at least 3 errors, got {len(errors)}: {errors}"

    # AC3: report includes file path
    assert "file" in report, "Report must include 'file' key with prd path"
    assert str(prd_file) in report["file"] or report["file"].endswith("prd.json")

    # AC3: each error is a non-empty string
    for err in errors:
        assert isinstance(err, str) and len(err) > 0

    # AC3: missing-description error includes story ID
    desc_errors = [e for e in errors if "description" in e.lower()]
    assert len(desc_errors) >= 1, "Should have at least one missing-description error"
    assert any("repo-a:US-001" in e for e in desc_errors), "Missing-description error must identify the story ID"

    # AC3: invalid-ID error includes the bad ID and a fix suggestion
    id_errors = [e for e in errors if "US-111-xyz" in e]
    assert len(id_errors) >= 1, "Should flag malformed ID 'US-111-xyz'"
    assert any("Fix" in e or "expected" in e.lower() for e in id_errors), (
        "Invalid-ID error must include a fix suggestion"
    )

    # AC3: unresolved-dep error includes both story IDs
    dep_errors = [e for e in errors if "repo-c:US-999" in e]
    assert len(dep_errors) >= 1, "Should flag unresolved dependency"
    assert any("repo-b:US-002" in e for e in dep_errors), (
        "Unresolved-dep error must include the story that has the missing dep"
    )

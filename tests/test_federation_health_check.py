"""Tests for federation-health-check command (US-653)."""

import json
from pathlib import Path

import pytest

from lib.commands.federation_health_check import (
    check_unknown_sub_projects,
    detect_circular_dependencies,
    run_health_check,
    validate_id_namespace,
)

# ── Test Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def prd_path(tmp_path: Path) -> Path:
    """Return a test prd.json path."""
    return tmp_path / "prd.json"


def _write_prd(prd_path: Path, prd_dict: dict) -> Path:
    """Helper to write prd.json and return path."""
    prd_path.parent.mkdir(parents=True, exist_ok=True)
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd_dict, f)
    return prd_path


# ────────────────────────────────────────────────────────────────────────────
# AC1: Detect unknown sub_project references
# ────────────────────────────────────────────────────────────────────────────


class TestCheckUnknownSubProjects:
    """Tests for AC1: Detect unknown sub_project references."""

    def test_valid_sub_project_reference(self, tmp_path: Path) -> None:
        """Story references existing sub_project."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "subProjects": [{"namespace": "payment"}, {"namespace": "api"}],
            "userStories": [
                {
                    "id": "PAYMENT-001",
                    "title": "Payment feature",
                    "sub_project": "payment",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                }
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        errors = check_unknown_sub_projects(prd_dict, prd_path)
        assert len(errors) == 0

    def test_unknown_sub_project_reference(self, tmp_path: Path) -> None:
        """Story references non-existent sub_project."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "subProjects": [{"namespace": "payment"}],
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Unknown project story",
                    "sub_project": "proj1",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                }
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        errors = check_unknown_sub_projects(prd_dict, prd_path)
        assert len(errors) == 1
        assert "US-001" in errors[0]
        assert "unknown sub_project: proj1" in errors[0]

    def test_no_sub_project_configured(self, tmp_path: Path) -> None:
        """No subProjects configured, all stories are default."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Story 1",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                }
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        errors = check_unknown_sub_projects(prd_dict, prd_path)
        assert len(errors) == 0

    def test_default_sub_project_is_always_valid(self, tmp_path: Path) -> None:
        """'default' sub_project is always valid."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "subProjects": [{"namespace": "payment"}],
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Default story",
                    "sub_project": "default",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                }
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        errors = check_unknown_sub_projects(prd_dict, prd_path)
        assert len(errors) == 0

    def test_multiple_unknown_references(self, tmp_path: Path) -> None:
        """Multiple stories reference unknown sub_projects."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "subProjects": [{"namespace": "payment"}],
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Story 1",
                    "sub_project": "unknown1",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                },
                {
                    "id": "US-002",
                    "title": "Story 2",
                    "sub_project": "unknown2",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                },
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        errors = check_unknown_sub_projects(prd_dict, prd_path)
        assert len(errors) == 2


# ────────────────────────────────────────────────────────────────────────────
# AC2: Detect circular cross-project dependencies
# ────────────────────────────────────────────────────────────────────────────


class TestDetectCircularDependencies:
    """Tests for AC2: Detect circular cross-project dependencies with cycle paths."""

    def test_no_circular_dependencies(self) -> None:
        """Valid linear dependency chain."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Story 1",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                },
                {
                    "id": "US-002",
                    "title": "Story 2",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": ["US-001"],
                },
            ],
        }
        errors = detect_circular_dependencies(prd_dict)
        assert len(errors) == 0

    def test_simple_circular_dependency(self) -> None:
        """Simple 2-node cycle: A → B → A."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Story A",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": ["US-002"],
                },
                {
                    "id": "US-002",
                    "title": "Story B",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": ["US-001"],
                },
            ],
        }
        errors = detect_circular_dependencies(prd_dict)
        assert len(errors) == 1
        # Should report cycle path
        assert "Circular dependency detected:" in errors[0]
        assert "→" in errors[0]

    def test_three_node_circular_dependency(self) -> None:
        """3-node cycle: A → B → C → A."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "PROJ1-001",
                    "title": "Story A",
                    "sub_project": "proj1",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": ["PROJ2-005"],
                },
                {
                    "id": "PROJ2-005",
                    "title": "Story B",
                    "sub_project": "proj2",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": ["PROJ1-003"],
                },
                {
                    "id": "PROJ1-003",
                    "title": "Story C",
                    "sub_project": "proj1",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": ["PROJ1-001"],
                },
            ],
        }
        errors = detect_circular_dependencies(prd_dict)
        assert len(errors) == 1
        error = errors[0]
        assert "Circular dependency detected:" in error
        # Should contain all three IDs in cycle
        assert "PROJ1-001" in error
        assert "PROJ2-005" in error
        assert "PROJ1-003" in error

    def test_cycle_with_external_deps(self) -> None:
        """Cycle with additional non-cyclic dependencies."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Story 1",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": ["US-002"],  # Part of cycle
                },
                {
                    "id": "US-002",
                    "title": "Story 2",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": ["US-001", "US-003"],  # Cycle + external
                },
                {
                    "id": "US-003",
                    "title": "Story 3",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                },
            ],
        }
        errors = detect_circular_dependencies(prd_dict)
        assert len(errors) == 1
        assert "Circular dependency detected:" in errors[0]


# ────────────────────────────────────────────────────────────────────────────
# AC3: Validate story ID namespace matches sub_project
# ────────────────────────────────────────────────────────────────────────────


class TestValidateIdNamespace:
    """Tests for AC3: Validate story ID prefix matches sub_project."""

    def test_matching_namespace(self, tmp_path: Path) -> None:
        """Story ID prefix matches sub_project."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "PAYMENT-001",
                    "title": "Payment feature",
                    "sub_project": "payment",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                }
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        errors = validate_id_namespace(prd_dict, prd_path)
        assert len(errors) == 0

    def test_mismatched_namespace(self, tmp_path: Path) -> None:
        """Story ID prefix does not match sub_project."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Payment feature",
                    "sub_project": "payment",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                }
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        errors = validate_id_namespace(prd_dict, prd_path)
        assert len(errors) == 1
        assert "US-001" in errors[0]
        assert "sub_project 'payment'" in errors[0]
        assert "prefix 'US' does not match (expected 'PAYMENT')" in errors[0]
        assert "Fix:" in errors[0]

    def test_case_insensitive_sub_project_to_uppercase(self, tmp_path: Path) -> None:
        """sub_project is lowercase, ID should be uppercase."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "PRICING-042",
                    "title": "Pricing feature",
                    "sub_project": "pricing",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                }
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        errors = validate_id_namespace(prd_dict, prd_path)
        assert len(errors) == 0

    def test_no_sub_project_no_validation(self, tmp_path: Path) -> None:
        """Stories without sub_project are not validated."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Default story",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                }
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        errors = validate_id_namespace(prd_dict, prd_path)
        assert len(errors) == 0

    def test_default_sub_project_no_validation(self, tmp_path: Path) -> None:
        """'default' sub_project does not trigger validation."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Default story",
                    "sub_project": "default",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                }
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        errors = validate_id_namespace(prd_dict, prd_path)
        assert len(errors) == 0

    def test_multiple_namespace_violations(self, tmp_path: Path) -> None:
        """Multiple stories have namespace mismatches."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Payment story",
                    "sub_project": "payment",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                },
                {
                    "id": "INVOICE-005",
                    "title": "API story",
                    "sub_project": "api",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                },
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        errors = validate_id_namespace(prd_dict, prd_path)
        assert len(errors) == 2


# ────────────────────────────────────────────────────────────────────────────
# Integration: run_health_check
# ────────────────────────────────────────────────────────────────────────────


class TestRunHealthCheck:
    """Integration tests for full health check."""

    def test_health_check_all_pass(self, tmp_path: Path) -> None:
        """All checks pass."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "subProjects": [{"namespace": "payment"}],
            "userStories": [
                {
                    "id": "PAYMENT-001",
                    "title": "Valid story",
                    "sub_project": "payment",
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": [],
                }
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        result = run_health_check(prd_dict, prd_path)
        assert result["valid"] is True
        assert len(result["errors"]) == 0

    def test_health_check_multiple_errors(self, tmp_path: Path) -> None:
        """Multiple checks fail."""
        prd_dict = {
            "productName": "Test",
            "branchName": "main",
            "subProjects": [{"namespace": "payment"}],
            "userStories": [
                {
                    "id": "US-001",
                    "title": "Story 1",
                    "sub_project": "unknown",  # Unknown ref
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": ["US-002"],  # Cycle
                },
                {
                    "id": "US-002",
                    "title": "Story 2",
                    "sub_project": "payment",  # Mismatch: US vs PAYMENT
                    "passes": False,
                    "acceptanceCriteria": ["AC1"],
                    "dependencies": ["US-001"],  # Cycle
                },
            ],
        }
        prd_path = _write_prd(tmp_path / "prd.json", prd_dict)
        result = run_health_check(prd_dict, prd_path)
        assert result["valid"] is False
        assert len(result["errors"]) >= 3  # At least: unknown, cycle, namespace mismatch
        assert any("unknown sub_project" in e for e in result["errors"])
        assert any("Circular dependency" in e for e in result["errors"])
        assert any("does not match" in e for e in result["errors"])

"""Tests for Phase M quota enforcement (US-1050).

Validates per-sub-project story limits read from SPIRAL_QUOTA_* environment variables.
"""

import json
import os
import sys
from typing import Any

import pytest

# Add lib to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib", "spiral"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from phase_m import prd_merge, validate_quota


def _make_prd(stories: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create a minimal PRD structure."""
    return {
        "schemaVersion": 1,
        "productName": "TestProject",
        "branchName": "main",
        "goals": ["Build a robust system"],
        "userStories": stories or [],
    }


def _make_story(story_id: str, sub_project: str | None = None, passes: bool = True) -> dict[str, Any]:
    """Create a story with sub_project field."""
    return {
        "id": story_id,
        "title": f"Story {story_id}",
        "description": "Test story",
        "priority": "medium",
        "acceptanceCriteria": ["AC1"],
        "passes": passes,
        "sub_project": sub_project,
        "dependencies": [],
    }


def _make_candidate(title: str, sub_project: str | None = None) -> dict[str, Any]:
    """Create a candidate story."""
    return {
        "title": title,
        "description": "Candidate story",
        "priority": "medium",
        "sub_project": sub_project,
        "acceptanceCriteria": ["AC1"],
        "technicalNotes": [],
        "estimatedComplexity": "small",
    }


# ── No quotas: should always pass ─────────────────────────────────────────────


class TestNoQuotas:
    def test_validation_passes_when_no_quotas_defined(self, tmp_path):
        """When no SPIRAL_QUOTA_* env vars are set, validation always passes."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(_make_prd([_make_story("US-001", "frontend")])))

        # Clear any existing SPIRAL_QUOTA_* vars
        with pytest.MonkeyPatch.context():
            for key in list(os.environ.keys()):
                if key.startswith("SPIRAL_QUOTA_"):
                    del os.environ[key]

            candidates = [_make_candidate("New story", "frontend")]
            valid, msg = validate_quota(candidates, prd_path)
            assert valid is True
            assert msg == ""

    def test_merge_succeeds_with_no_quotas(self, tmp_path):
        """prd_merge should succeed when no quotas are defined."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(_make_prd([_make_story("US-001", "frontend")])))

        with pytest.MonkeyPatch.context():
            for key in list(os.environ.keys()):
                if key.startswith("SPIRAL_QUOTA_"):
                    del os.environ[key]

            candidates = [_make_candidate("New story", "frontend")]
            result = prd_merge(candidates, prd_path, skip_ordering=True, skip_quota=False)
            assert len(result) == 1


# ── Single sub-project quota enforcement ──────────────────────────────────────


class TestSingleSubProjectQuota:
    def test_quota_allows_stories_under_limit(self, tmp_path, monkeypatch):
        """Stories under quota limit should be allowed."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "frontend"),
                        _make_story("US-002", "frontend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "5")

        candidates = [_make_candidate("New story 1", "frontend")]
        valid, msg = validate_quota(candidates, prd_path)
        assert valid is True
        assert msg == ""

    def test_quota_rejects_stories_at_limit(self, tmp_path, monkeypatch):
        """When current + candidates > limit, should raise ValueError."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "frontend"),
                        _make_story("US-002", "frontend"),
                        _make_story("US-003", "frontend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "3")

        candidates = [_make_candidate("New story", "frontend")]
        with pytest.raises(ValueError, match="Quota exceeded for frontend: 4/3"):
            validate_quota(candidates, prd_path)

    def test_quota_message_format(self, tmp_path, monkeypatch):
        """Quota exceeded message should match format 'Quota exceeded for <subproject>: <count>/<limit>'."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "backend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_BACKEND", "2")

        candidates = [
            _make_candidate("New story 1", "backend"),
            _make_candidate("New story 2", "backend"),
        ]
        with pytest.raises(ValueError, match="Quota exceeded for backend: 3/2"):
            validate_quota(candidates, prd_path)

    def test_quota_exact_at_limit(self, tmp_path, monkeypatch):
        """Exactly at limit should be allowed."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "frontend"),
                        _make_story("US-002", "frontend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "3")

        candidates = [_make_candidate("New story", "frontend")]
        valid, msg = validate_quota(candidates, prd_path)
        assert valid is True
        assert msg == ""


# ── Multiple sub-project quotas ───────────────────────────────────────────────


class TestMultipleSubProjectQuotas:
    def test_multiple_quotas_all_under_limit(self, tmp_path, monkeypatch):
        """When multiple sub-projects have quotas, all must be checked."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "frontend"),
                        _make_story("US-002", "backend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "5")
        monkeypatch.setenv("SPIRAL_QUOTA_BACKEND", "5")

        candidates = [
            _make_candidate("New frontend", "frontend"),
            _make_candidate("New backend", "backend"),
        ]
        valid, msg = validate_quota(candidates, prd_path)
        assert valid is True

    def test_multiple_quotas_one_exceeded(self, tmp_path, monkeypatch):
        """If any sub-project exceeds quota, validation fails."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "frontend"),
                        _make_story("US-002", "backend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "5")
        monkeypatch.setenv("SPIRAL_QUOTA_BACKEND", "2")  # Backend is tight

        candidates = [
            _make_candidate("New frontend", "frontend"),
            _make_candidate("New backend 1", "backend"),
            _make_candidate("New backend 2", "backend"),
        ]
        with pytest.raises(ValueError, match="Quota exceeded for backend: 3/2"):
            validate_quota(candidates, prd_path)

    def test_multiple_quotas_frontend_exceeds(self, tmp_path, monkeypatch):
        """Test when frontend (not backend) exceeds quota."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "frontend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "2")
        monkeypatch.setenv("SPIRAL_QUOTA_BACKEND", "100")

        candidates = [
            _make_candidate("New frontend 1", "frontend"),
            _make_candidate("New frontend 2", "frontend"),
        ]
        with pytest.raises(ValueError, match="Quota exceeded for frontend: 3/2"):
            validate_quota(candidates, prd_path)


# ── Case-insensitive sub-project names ────────────────────────────────────────


class TestCaseInsensitivity:
    def test_subproject_name_case_insensitive(self, tmp_path, monkeypatch):
        """Sub-project names should be lowercased for comparison."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "Frontend"),  # Capitalized
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "2")

        candidates = [_make_candidate("New story", "FRONTEND")]  # Uppercase
        valid, msg = validate_quota(candidates, prd_path)
        assert valid is True

    def test_quota_env_var_case_preserved(self, tmp_path, monkeypatch):
        """SPIRAL_QUOTA_MYPROJ should match sub_project='myproj'."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "MyProj"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_MYPROJ", "1")

        candidates = [_make_candidate("New story", "myproj")]
        with pytest.raises(ValueError, match="Quota exceeded for myproj: 2/1"):
            validate_quota(candidates, prd_path)


# ── Stories with null/empty sub_project ───────────────────────────────────────


class TestNullSubProject:
    def test_null_subproject_uses_default(self, tmp_path, monkeypatch):
        """Stories with null sub_project should be counted under 'default'."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", None),  # No sub_project
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_DEFAULT", "1")

        candidates = [_make_candidate("New story", None)]
        with pytest.raises(ValueError, match="Quota exceeded for default: 2/1"):
            validate_quota(candidates, prd_path)

    def test_mixed_null_and_named_subprojects(self, tmp_path, monkeypatch):
        """Can mix null sub_projects with named ones."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", None),
                        _make_story("US-002", "frontend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_DEFAULT", "5")
        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "5")

        candidates = [
            _make_candidate("New default", None),
            _make_candidate("New frontend", "frontend"),
        ]
        valid, msg = validate_quota(candidates, prd_path)
        assert valid is True


# ── Empty/missing prd.json ────────────────────────────────────────────────────


class TestMissingPRD:
    def test_validation_handles_missing_prd_file(self, tmp_path, monkeypatch):
        """If prd.json doesn't exist, candidates are counted as new."""
        prd_path = tmp_path / "prd.json"  # File doesn't exist

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "5")

        candidates = [
            _make_candidate("New 1", "frontend"),
            _make_candidate("New 2", "frontend"),
        ]
        valid, msg = validate_quota(candidates, prd_path)
        assert valid is True

    def test_validation_with_nonexistent_file_exceeded(self, tmp_path, monkeypatch):
        """Even with missing prd.json, quota can be exceeded by candidates alone."""
        prd_path = tmp_path / "prd.json"  # File doesn't exist

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "2")

        candidates = [
            _make_candidate("New 1", "frontend"),
            _make_candidate("New 2", "frontend"),
            _make_candidate("New 3", "frontend"),
        ]
        with pytest.raises(ValueError, match="Quota exceeded for frontend: 3/2"):
            validate_quota(candidates, prd_path)


# ── Malformed environment variables ───────────────────────────────────────────


class TestMalformedEnv:
    def test_non_integer_quota_values_skipped(self, tmp_path, monkeypatch):
        """Non-integer SPIRAL_QUOTA_* values should be silently skipped."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "frontend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "not_a_number")
        monkeypatch.setenv("SPIRAL_QUOTA_BACKEND", "5")  # Valid

        # Should not raise error; frontend quota is skipped, backend is valid
        candidates = [
            _make_candidate("New", "frontend"),
            _make_candidate("New", "backend"),
        ]
        valid, msg = validate_quota(candidates, prd_path)
        assert valid is True

    def test_zero_quota_enforced(self, tmp_path, monkeypatch):
        """Quota of 0 means no stories allowed."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(_make_prd([])))

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "0")

        candidates = [_make_candidate("New", "frontend")]
        with pytest.raises(ValueError, match="Quota exceeded for frontend: 1/0"):
            validate_quota(candidates, prd_path)

    def test_negative_quota_enforced(self, tmp_path, monkeypatch):
        """Negative quotas should still be enforced (can be set for emergency lockdown)."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(json.dumps(_make_prd([])))

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "-5")

        candidates = [_make_candidate("New", "frontend")]
        with pytest.raises(ValueError, match="Quota exceeded for frontend: 1/-5"):
            validate_quota(candidates, prd_path)


# ── Integration with prd_merge ────────────────────────────────────────────────


class TestIntegrationWithPRDMerge:
    def test_prd_merge_validates_quota_by_default(self, tmp_path, monkeypatch):
        """prd_merge should call validate_quota unless skip_quota=True."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "frontend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "1")

        candidates = [_make_candidate("New", "frontend")]
        with pytest.raises(ValueError, match="Quota exceeded"):
            prd_merge(candidates, prd_path, skip_ordering=True, skip_quota=False)

    def test_prd_merge_can_skip_quota_check(self, tmp_path, monkeypatch):
        """prd_merge with skip_quota=True should bypass quota validation."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "frontend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "1")

        candidates = [_make_candidate("New", "frontend")]
        result = prd_merge(candidates, prd_path, skip_ordering=True, skip_quota=True)
        assert len(result) == 1

    def test_prd_merge_empty_candidates_passes_quota(self, tmp_path, monkeypatch):
        """Empty candidates list should pass quota check (0 new stories)."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "frontend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "1")

        result = prd_merge([], prd_path, skip_ordering=True, skip_quota=False)
        assert result == []


# ── Real-world scenario: federated Spiral ────────────────────────────────────


class TestFederatedScenario:
    def test_federated_spiral_enforces_per_project_limits(self, tmp_path, monkeypatch):
        """Simulate federated Spiral with separate frontend/backend quotas."""
        prd_path = tmp_path / "prd.json"
        prd_path.write_text(
            json.dumps(
                _make_prd(
                    [
                        _make_story("US-001", "frontend"),
                        _make_story("US-002", "frontend"),
                        _make_story("US-003", "backend"),
                        _make_story("US-004", "backend"),
                        _make_story("US-005", "backend"),
                    ]
                )
            )
        )

        monkeypatch.setenv("SPIRAL_QUOTA_FRONTEND", "3")
        monkeypatch.setenv("SPIRAL_QUOTA_BACKEND", "5")

        # Should succeed: frontend would be 3, backend would be 5
        candidates = [
            _make_candidate("New frontend", "frontend"),
            _make_candidate("New backend", "backend"),
        ]
        valid, msg = validate_quota(candidates, prd_path)
        assert valid is True

        # Should fail: backend would exceed 5 (3 existing + 3 new = 6)
        candidates_exceed = [
            _make_candidate("New backend 1", "backend"),
            _make_candidate("New backend 2", "backend"),
            _make_candidate("New backend 3", "backend"),
        ]
        with pytest.raises(ValueError, match="Quota exceeded for backend: 6/5"):
            validate_quota(candidates_exceed, prd_path)

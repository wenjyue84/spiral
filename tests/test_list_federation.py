"""tests/test_list_federation.py — Tests for lib/list_federation.py (US-665).

Covers:
- Output counts match prd.json tallies
- JSON matches federation schema
- Empty sub_project defaults to 'default'
- Exit code 1 if federation.toml missing
- Exit code 1 if sub_project inconsistent with config
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from list_federation import (  # type: ignore[import-untyped]
    build_summary,
    count_stories_by_project,
    load_federation_config,
    validate_consistency,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


def make_toml_bytes(sub_projects: list[dict]) -> bytes:
    """Build raw federation.toml bytes from sub_projects list."""
    lines = []
    for proj in sub_projects:
        lines.append("[[sub_projects]]")
        lines.append(f'name = "{proj["name"]}"')
        lines.append(f"workers = {proj['workers']}")
        lines.append("")
    return "\n".join(lines).encode()


def make_config(sub_projects: list[dict]) -> dict:
    """Build config dict as returned by load_federation_config()."""
    return {"sub_projects": [{"name": p["name"], "workers": p["workers"]} for p in sub_projects]}


# ── TestLoadFederationConfig ─────────────────────────────────────────────────


class TestLoadFederationConfig:
    def test_missing_file_raises_file_not_found(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="not found"):
            load_federation_config(tmp_path / "missing.toml")

    def test_valid_config_returns_sub_projects(self, tmp_path: Path) -> None:
        toml_bytes = make_toml_bytes([{"name": "frontend", "workers": 2}, {"name": "backend", "workers": 1}])
        config_path = tmp_path / "federation.toml"
        config_path.write_bytes(toml_bytes)
        result = load_federation_config(config_path)
        assert len(result["sub_projects"]) == 2
        assert result["sub_projects"][0] == {"name": "frontend", "workers": 2}
        assert result["sub_projects"][1] == {"name": "backend", "workers": 1}

    def test_missing_name_raises_value_error(self, tmp_path: Path) -> None:
        raw = b"[[sub_projects]]\nworkers = 1\n"
        config_path = tmp_path / "federation.toml"
        config_path.write_bytes(raw)
        with pytest.raises(ValueError, match="missing 'name'"):
            load_federation_config(config_path)

    def test_defaults_workers_to_1_when_missing(self, tmp_path: Path) -> None:
        raw = b'[[sub_projects]]\nname = "core"\n'
        config_path = tmp_path / "federation.toml"
        config_path.write_bytes(raw)
        result = load_federation_config(config_path)
        assert result["sub_projects"][0]["workers"] == 1

    def test_empty_sub_projects_list(self, tmp_path: Path) -> None:
        raw = b"# empty config\n"
        config_path = tmp_path / "federation.toml"
        config_path.write_bytes(raw)
        result = load_federation_config(config_path)
        assert result["sub_projects"] == []


# ── TestCountStoriesByProject ────────────────────────────────────────────────


class TestCountStoriesByProject:
    def test_counts_by_sub_project(self) -> None:
        stories = [
            {"id": "US-001", "sub_project": "frontend"},
            {"id": "US-002", "sub_project": "frontend"},
            {"id": "US-003", "sub_project": "backend"},
        ]
        counts = count_stories_by_project(stories)
        assert counts["frontend"] == 2
        assert counts["backend"] == 1

    def test_empty_sub_project_defaults_to_default(self) -> None:
        stories = [
            {"id": "US-001", "sub_project": ""},
            {"id": "US-002"},
        ]
        counts = count_stories_by_project(stories)
        assert counts.get("default") == 2
        assert "" not in counts

    def test_none_sub_project_defaults_to_default(self) -> None:
        stories = [{"id": "US-001", "sub_project": None}]
        counts = count_stories_by_project(stories)
        assert counts.get("default") == 1

    def test_whitespace_only_defaults_to_default(self) -> None:
        stories = [{"id": "US-001", "sub_project": "   "}]
        counts = count_stories_by_project(stories)
        assert counts.get("default") == 1

    def test_empty_stories_returns_empty_dict(self) -> None:
        assert count_stories_by_project([]) == {}

    def test_counts_match_prd_tallies(self) -> None:
        """Acceptance criteria: output counts match prd.json tallies."""
        stories = [
            {"id": "US-001", "sub_project": "frontend"},
            {"id": "US-002", "sub_project": "frontend"},
            {"id": "US-003", "sub_project": "frontend"},
            {"id": "US-004", "sub_project": "backend"},
            {"id": "US-005", "sub_project": "backend"},
        ]
        counts = count_stories_by_project(stories)
        assert counts["frontend"] == 3
        assert counts["backend"] == 2
        assert sum(counts.values()) == len(stories)


# ── TestValidateConsistency ──────────────────────────────────────────────────


class TestValidateConsistency:
    def test_consistent_returns_empty_errors(self) -> None:
        errors = validate_consistency({"frontend", "backend"}, {"frontend", "backend"})
        assert errors == []

    def test_extra_prd_project_returns_error(self) -> None:
        errors = validate_consistency({"frontend"}, {"frontend", "mobile"})
        assert len(errors) == 1
        assert "mobile" in errors[0]

    def test_default_project_always_allowed(self) -> None:
        errors = validate_consistency({"frontend"}, {"frontend", "default"})
        assert errors == []

    def test_multiple_missing_projects_all_reported(self) -> None:
        errors = validate_consistency(set(), {"alpha", "beta", "gamma"})
        assert len(errors) == 3

    def test_empty_story_projects_is_consistent(self) -> None:
        errors = validate_consistency({"frontend"}, set())
        assert errors == []


# ── TestBuildSummary ─────────────────────────────────────────────────────────


class TestBuildSummary:
    def test_schema_matches_acceptance_criteria(self) -> None:
        """Acceptance criteria: JSON schema {sub_projects, total_stories, total_workers}."""
        config = make_config([{"name": "frontend", "workers": 2}, {"name": "backend", "workers": 1}])
        counts = {"frontend": 12, "backend": 8}
        summary = build_summary(config, counts)
        assert "sub_projects" in summary
        assert "total_stories" in summary
        assert "total_workers" in summary
        assert summary["total_stories"] == 20
        assert summary["total_workers"] == 3

    def test_sub_projects_have_required_fields(self) -> None:
        config = make_config([{"name": "core", "workers": 3}])
        counts = {"core": 5}
        summary = build_summary(config, counts)
        proj = summary["sub_projects"][0]
        assert proj["name"] == "core"
        assert proj["story_count"] == 5
        assert proj["workers"] == 3

    def test_zero_story_count_when_no_stories(self) -> None:
        config = make_config([{"name": "frontend", "workers": 2}])
        counts: dict = {}
        summary = build_summary(config, counts)
        assert summary["sub_projects"][0]["story_count"] == 0
        assert summary["total_stories"] == 0

    def test_default_project_appended_if_not_in_config(self) -> None:
        """Empty sub_project defaults to 'default' and appears in output."""
        config = make_config([{"name": "frontend", "workers": 2}])
        counts = {"frontend": 5, "default": 3}
        summary = build_summary(config, counts)
        names = [p["name"] for p in summary["sub_projects"]]
        assert "default" in names
        assert summary["total_stories"] == 8

    def test_total_workers_sums_all_projects(self) -> None:
        config = make_config([{"name": "a", "workers": 2}, {"name": "b", "workers": 3}, {"name": "c", "workers": 1}])
        counts = {"a": 1, "b": 1, "c": 1}
        summary = build_summary(config, counts)
        assert summary["total_workers"] == 6

    def test_output_is_json_serializable(self) -> None:
        config = make_config([{"name": "frontend", "workers": 2}])
        counts = {"frontend": 10}
        summary = build_summary(config, counts)
        serialized = json.dumps(summary)
        parsed = json.loads(serialized)
        assert parsed["total_stories"] == 10

"""tests/test_federation_impact_analyzer.py — Integration tests for blast radius analyzer.

Tests transitive_closure() on a 4-subproject fixture with cross-project deps.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from federation_impact_analyzer import _detect_cycles, transitive_closure

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_story(
    story_id: str,
    sub_project: str,
    dependencies: list[str] | None = None,
) -> dict[str, object]:
    """Build a minimal story dict."""
    return {
        "id": story_id,
        "title": f"Story {story_id}",
        "sub_project": sub_project,
        "dependencies": dependencies or [],
        "passes": False,
    }


# 4-subproject fixture:
#   auth-service: US-A1, US-A2
#   user-service: US-U1 (depends on US-A1), US-U2 (depends on US-A2)
#   api-gateway:  US-G1 (depends on US-U1), US-G2 (no deps)
#   frontend:     US-F1 (depends on US-G1)  <-- transitive from auth-service
#
# Blast radius of auth-service:
#   US-A1 -> US-U1 -> US-G1 -> US-F1  (transitive chain)
#   US-A2 -> US-U2
#
# affected_sub_projects: ["api-gateway", "frontend", "user-service"]
# critical_stories: ["US-F1", "US-G1", "US-U1", "US-U2"]
FOUR_SUBPROJECT_STORIES: list[dict[str, object]] = [
    _make_story("US-A1", "auth-service"),
    _make_story("US-A2", "auth-service"),
    _make_story("US-U1", "user-service", ["US-A1"]),
    _make_story("US-U2", "user-service", ["US-A2"]),
    _make_story("US-G1", "api-gateway", ["US-U1"]),
    _make_story("US-G2", "api-gateway"),
    _make_story("US-F1", "frontend", ["US-G1"]),
]


# ---------------------------------------------------------------------------
# Unit tests for transitive_closure
# ---------------------------------------------------------------------------


class TestTransitiveClosure:
    def test_blast_radius_includes_direct_dependents(self) -> None:
        """Stories that directly depend on auth-service stories are in blast radius."""
        result = transitive_closure("auth-service", FOUR_SUBPROJECT_STORIES)
        assert "US-U1" in result["critical_stories"]
        assert "US-U2" in result["critical_stories"]

    def test_blast_radius_includes_transitive_dependents(self) -> None:
        """Stories transitively depending on auth-service are included."""
        result = transitive_closure("auth-service", FOUR_SUBPROJECT_STORIES)
        assert "US-G1" in result["critical_stories"]
        assert "US-F1" in result["critical_stories"]

    def test_blast_radius_excludes_unrelated_stories(self) -> None:
        """US-G2 has no dependency on auth-service — not in blast radius."""
        result = transitive_closure("auth-service", FOUR_SUBPROJECT_STORIES)
        assert "US-G2" not in result["critical_stories"]

    def test_affected_sub_projects_accuracy(self) -> None:
        """Three sub-projects are affected when auth-service changes."""
        result = transitive_closure("auth-service", FOUR_SUBPROJECT_STORIES)
        assert result["affected_sub_projects"] == sorted(
            ["api-gateway", "frontend", "user-service"]
        )

    def test_source_sub_project_not_in_affected(self) -> None:
        """The source sub-project itself is not listed in affected_sub_projects."""
        result = transitive_closure("auth-service", FOUR_SUBPROJECT_STORIES)
        assert "auth-service" not in result["affected_sub_projects"]

    def test_zero_cycles_reported(self) -> None:
        """Clean fixture has no cycles — cycle_detected must be False."""
        result = transitive_closure("auth-service", FOUR_SUBPROJECT_STORIES)
        assert result["cycle_detected"] is False

    def test_isolated_sub_project_empty_blast_radius(self) -> None:
        """frontend is a leaf — nothing depends on it."""
        result = transitive_closure("frontend", FOUR_SUBPROJECT_STORIES)
        assert result["critical_stories"] == []
        assert result["affected_sub_projects"] == []

    def test_unknown_sub_project_returns_empty(self) -> None:
        """Unknown sub-project has empty blast radius."""
        result = transitive_closure("nonexistent-service", FOUR_SUBPROJECT_STORIES)
        assert result["critical_stories"] == []
        assert result["affected_sub_projects"] == []
        assert result["cycle_detected"] is False

    def test_result_keys_present(self) -> None:
        """Output dict always has the three required keys."""
        result = transitive_closure("auth-service", FOUR_SUBPROJECT_STORIES)
        assert set(result.keys()) == {
            "affected_sub_projects",
            "critical_stories",
            "cycle_detected",
        }

    def test_critical_stories_sorted(self) -> None:
        """critical_stories list is sorted for deterministic output."""
        result = transitive_closure("auth-service", FOUR_SUBPROJECT_STORIES)
        assert result["critical_stories"] == sorted(result["critical_stories"])


# ---------------------------------------------------------------------------
# Cycle detection tests
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_no_cycle_acyclic_graph(self) -> None:
        forward: dict[str, list[str]] = {"A": ["B"], "B": ["C"], "C": []}
        assert _detect_cycles(forward) is False

    def test_direct_cycle_detected(self) -> None:
        forward: dict[str, list[str]] = {"A": ["B"], "B": ["A"]}
        assert _detect_cycles(forward) is True

    def test_self_loop_detected(self) -> None:
        forward: dict[str, list[str]] = {"A": ["A"]}
        assert _detect_cycles(forward) is True

    def test_transitive_cycle_detected(self) -> None:
        forward: dict[str, list[str]] = {"A": ["B"], "B": ["C"], "C": ["A"]}
        assert _detect_cycles(forward) is True

    def test_empty_graph_no_cycle(self) -> None:
        forward: dict[str, list[str]] = {}
        assert _detect_cycles(forward) is False

    def test_cycle_in_stories_sets_flag(self) -> None:
        """transitive_closure sets cycle_detected=True when stories have a cycle."""
        cyclic_stories: list[dict[str, object]] = [
            _make_story("US-X1", "svc-a", ["US-X2"]),
            _make_story("US-X2", "svc-b", ["US-X1"]),
        ]
        result = transitive_closure("svc-a", cyclic_stories)
        assert result["cycle_detected"] is True


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestCLI:
    def test_cli_outputs_valid_json(self, tmp_path: Path) -> None:
        """CLI federation-impact-analyze outputs parseable JSON."""
        prd = {"userStories": FOUR_SUBPROJECT_STORIES}
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                "main.py",
                "federation-impact-analyze",
                "auth-service",
                "--prd",
                str(prd_file),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert "affected_sub_projects" in data
        assert "critical_stories" in data
        assert "cycle_detected" in data

    def test_cli_blast_radius_accuracy(self, tmp_path: Path) -> None:
        """CLI reports correct affected sub-projects and 0 cycles for 4-project fixture."""
        prd = {"userStories": FOUR_SUBPROJECT_STORIES}
        prd_file = tmp_path / "prd.json"
        prd_file.write_text(json.dumps(prd), encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                "main.py",
                "federation-impact-analyze",
                "auth-service",
                "--prd",
                str(prd_file),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert sorted(data["affected_sub_projects"]) == [
            "api-gateway",
            "frontend",
            "user-service",
        ]
        assert data["cycle_detected"] is False

    def test_cli_missing_prd_exits_nonzero(self, tmp_path: Path) -> None:
        """CLI exits 1 when prd.json does not exist."""
        proc = subprocess.run(
            [
                sys.executable,
                "main.py",
                "federation-impact-analyze",
                "auth-service",
                "--prd",
                str(tmp_path / "nonexistent.json"),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent,
        )
        assert proc.returncode == 1

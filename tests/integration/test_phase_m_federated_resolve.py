"""Integration test: Phase M Federated Conflict Auto-Resolution (US-1073).

Simulates a 3-worker federated run where workers produce divergent file
versions.  Verifies that three_way_merge either resolves the conflict
automatically or returns a ConflictMarker for manual review.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
from phase_m.conflict_resolver import ConflictMarker, resolve_or_mark, three_way_merge

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE_PY = """\
def greet(name: str) -> str:
    return f"Hello, {name}!"


def farewell(name: str) -> str:
    return f"Goodbye, {name}!"


VERSION = "1.0.0"
"""


class TestThreeWayMergeAutoResolve:
    """AC1 & AC2: three_way_merge returns str or ConflictMarker."""

    def test_no_change_returns_base(self) -> None:
        """Merging identical versions yields the original content."""
        result = three_way_merge(BASE_PY, BASE_PY, BASE_PY)
        assert isinstance(result, str)
        assert result == BASE_PY

    def test_only_a_changed_accepted(self) -> None:
        """When only Worker-A edits a region it is accepted automatically."""
        version_a = BASE_PY.replace("Hello", "Hi")  # changes greet()
        result = three_way_merge(BASE_PY, version_a, BASE_PY)
        assert isinstance(result, str)
        assert "Hi" in result
        assert "Hello" not in result

    def test_only_b_changed_accepted(self) -> None:
        """When only Worker-B edits a region it is accepted automatically."""
        version_b = BASE_PY.replace("Goodbye", "Bye")  # changes farewell()
        result = three_way_merge(BASE_PY, BASE_PY, version_b)
        assert isinstance(result, str)
        assert "Bye" in result
        assert "Goodbye" not in result

    def test_disjoint_changes_both_applied(self) -> None:
        """Non-overlapping edits from A and B are both included in merged output."""
        version_a = BASE_PY.replace("Hello", "Hi")
        version_b = BASE_PY.replace("Goodbye", "Bye")
        result = three_way_merge(BASE_PY, version_a, version_b)
        assert isinstance(result, str)
        assert "Hi" in result
        assert "Bye" in result

    def test_identical_edits_no_conflict(self) -> None:
        """When both workers make the same edit it is accepted once."""
        version_a = BASE_PY.replace('VERSION = "1.0.0"', 'VERSION = "2.0.0"')
        version_b = BASE_PY.replace('VERSION = "1.0.0"', 'VERSION = "2.0.0"')
        result = three_way_merge(BASE_PY, version_a, version_b)
        assert isinstance(result, str)
        assert 'VERSION = "2.0.0"' in result

    def test_conflicting_edits_returns_conflict_marker(self) -> None:
        """Incompatible edits on the same line return a ConflictMarker."""
        version_a = BASE_PY.replace('VERSION = "1.0.0"', 'VERSION = "2.0.0"')
        version_b = BASE_PY.replace('VERSION = "1.0.0"', 'VERSION = "3.0.0"')
        result = three_way_merge(BASE_PY, version_a, version_b)
        assert isinstance(result, ConflictMarker)
        assert result.conflict_regions  # at least one conflict region
        assert "<<<<<<< version_a" in result.annotated
        assert "=======" in result.annotated
        assert ">>>>>>> version_b" in result.annotated

    def test_conflict_marker_preserves_both_versions(self) -> None:
        """ConflictMarker annotated text contains both A and B alternatives."""
        version_a = BASE_PY.replace('VERSION = "1.0.0"', 'VERSION = "alpha"')
        version_b = BASE_PY.replace('VERSION = "1.0.0"', 'VERSION = "beta"')
        result = three_way_merge(BASE_PY, version_a, version_b)
        assert isinstance(result, ConflictMarker)
        assert 'VERSION = "alpha"' in result.annotated
        assert 'VERSION = "beta"' in result.annotated


class TestResolveOrMark:
    """Convenience wrapper resolve_or_mark returns (content, bool)."""

    def test_auto_resolved_flag_true_on_success(self) -> None:
        version_a = BASE_PY.replace("Hello", "Greetings")
        content, resolved = resolve_or_mark(BASE_PY, version_a, BASE_PY)
        assert resolved is True
        assert "Greetings" in content

    def test_auto_resolved_flag_false_on_conflict(self) -> None:
        version_a = BASE_PY.replace('VERSION = "1.0.0"', 'VERSION = "X"')
        version_b = BASE_PY.replace('VERSION = "1.0.0"', 'VERSION = "Y"')
        content, resolved = resolve_or_mark(BASE_PY, version_a, version_b)
        assert resolved is False
        assert "<<<<<<< version_a" in content


class TestFederatedThreeWorkerScenario:
    """AC3: Simulate 3-worker federated run with file collisions."""

    def _simulate_three_workers(self, tmp_path: Path) -> None:
        """Set up shared file with 3 workers producing different versions."""
        shared_file = tmp_path / "shared_module.py"
        shared_file.write_text(BASE_PY, encoding="utf-8")

        # Worker-A: changes greet() — non-conflicting with Worker-B's edit
        worker_a_version = BASE_PY.replace("Hello", "Howdy")
        # Worker-B: changes farewell() — non-conflicting with Worker-A
        worker_b_version = BASE_PY.replace("Goodbye", "See ya")
        # Worker-C: changes VERSION — conflicts with Worker-A (who also touches it)
        worker_a_and_c_base = BASE_PY
        worker_a_full = worker_a_and_c_base.replace("Hello", "Howdy")
        worker_c_version = BASE_PY.replace('VERSION = "1.0.0"', 'VERSION = "worker-c"')
        worker_a_also_version = worker_a_full.replace('VERSION = "1.0.0"', 'VERSION = "worker-a"')

        # Store all versions as files for inspection
        (tmp_path / "worker_a.py").write_text(worker_a_version, encoding="utf-8")
        (tmp_path / "worker_b.py").write_text(worker_b_version, encoding="utf-8")
        (tmp_path / "worker_c.py").write_text(worker_c_version, encoding="utf-8")
        (tmp_path / "worker_a_with_version.py").write_text(worker_a_also_version, encoding="utf-8")

        self._worker_a = worker_a_version
        self._worker_b = worker_b_version
        self._worker_c = worker_c_version
        self._worker_a_with_version = worker_a_also_version

    def test_a_and_b_disjoint_resolve_cleanly(self, tmp_path: Path) -> None:
        """Workers A and B touch different regions — auto-resolved."""
        self._simulate_three_workers(tmp_path)
        result = three_way_merge(BASE_PY, self._worker_a, self._worker_b)
        assert isinstance(result, str), "Expected auto-resolution for disjoint edits"
        assert "Howdy" in result
        assert "See ya" in result

    def test_a_and_c_version_conflict_marked(self, tmp_path: Path) -> None:
        """Workers A and C both edit VERSION with different values — returns ConflictMarker."""
        self._simulate_three_workers(tmp_path)
        result = three_way_merge(BASE_PY, self._worker_a_with_version, self._worker_c)
        assert isinstance(result, ConflictMarker), (
            "Expected ConflictMarker when two workers make incompatible VERSION edits"
        )
        assert len(result.conflict_regions) >= 1

    def test_all_resolved_or_marked(self, tmp_path: Path) -> None:
        """Every file collision is either auto-resolved or gets a ConflictMarker (none dropped)."""
        self._simulate_three_workers(tmp_path)
        pairs = [
            ("A vs B", BASE_PY, self._worker_a, self._worker_b),
            ("A vs C", BASE_PY, self._worker_a_with_version, self._worker_c),
            ("B vs C", BASE_PY, self._worker_b, self._worker_c),
        ]
        for label, base, va, vb in pairs:
            result = three_way_merge(base, va, vb)
            assert isinstance(result, (str, ConflictMarker)), (
                f"{label}: three_way_merge returned unexpected type {type(result)}"
            )

    def test_commit_message_label_on_auto_resolve(self, tmp_path: Path) -> None:
        """resolve_or_mark sets auto_resolved=True, signalling Phase M to use
        'Auto-resolved federated conflict' commit message."""
        self._simulate_three_workers(tmp_path)
        _content, auto_resolved = resolve_or_mark(BASE_PY, self._worker_a, self._worker_b)
        assert auto_resolved is True, (
            "Phase M should commit with 'Auto-resolved federated conflict' for clean merges"
        )

    def test_manual_review_flag_on_unresolvable(self, tmp_path: Path) -> None:
        """resolve_or_mark sets auto_resolved=False for true conflicts, indicating
        the file should be marked for manual review rather than committed."""
        self._simulate_three_workers(tmp_path)
        _content, auto_resolved = resolve_or_mark(
            BASE_PY, self._worker_a_with_version, self._worker_c
        )
        assert auto_resolved is False, "Phase M must not auto-commit files with unresolvable conflicts"

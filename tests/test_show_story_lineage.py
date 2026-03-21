"""Tests for lib/show_story_lineage.py — Story decomposition lineage (US-671)."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from show_story_lineage import (
    LineageNode,
    _load_token_counts,
    _status_emoji,
    build_lineage_tree,
    format_tree,
    to_json_output,
)


class TestStatusEmoji:
    """Test status emoji generation."""

    def test_emoji_passed(self) -> None:
        """Passed stories show ✓."""
        assert _status_emoji(True) == "✓"

    def test_emoji_failed(self) -> None:
        """Failed stories show ✗."""
        assert _status_emoji(False) == "✗"

    def test_emoji_pending(self) -> None:
        """Pending stories (None) show ⏳."""
        assert _status_emoji(None) == "⏳"


class TestLineageNodeBasics:
    """Test LineageNode dataclass."""

    def test_node_creation(self) -> None:
        """Create a LineageNode."""
        node = LineageNode(
            story_id="US-001",
            title="Test Story",
            passes=True,
            tokens=1000,
        )
        assert node.story_id == "US-001"
        assert node.title == "Test Story"
        assert node.passes is True
        assert node.tokens == 1000
        assert node.children == []

    def test_node_with_children(self) -> None:
        """Create a LineageNode with children."""
        child1 = LineageNode("US-002", "Child 1", True, 500)
        child2 = LineageNode("US-003", "Child 2", False, 300)
        parent = LineageNode(
            story_id="US-001",
            title="Parent",
            passes=True,
            tokens=1000,
            children=[child1, child2],
        )
        assert len(parent.children) == 2
        assert parent.children[0].story_id == "US-002"
        assert parent.children[1].story_id == "US-003"


class TestLoadTokenCounts:
    """Test token count loading from results.tsv."""

    def test_load_empty_tsv(self) -> None:
        """Handle non-existent results.tsv."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.tsv"
            counts = _load_token_counts(path)
            assert counts == {}

    def test_load_token_counts_cache_read(self) -> None:
        """Load cache_read_tokens."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.tsv"
            with open(path, "w") as f:
                f.write("story_id\tcache_read_tokens\tcache_creation_tokens\n")
                f.write("US-001\t1000\t500\n")
                f.write("US-002\t2000\t1000\n")
            counts = _load_token_counts(path)
            assert counts["US-001"] == 1000
            assert counts["US-002"] == 2000

    def test_load_token_counts_fallback_creation(self) -> None:
        """Fallback to cache_creation_tokens if read is zero."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.tsv"
            with open(path, "w") as f:
                f.write("story_id\tcache_read_tokens\tcache_creation_tokens\n")
                f.write("US-001\t0\t500\n")
                f.write("US-002\t1000\t0\n")
            counts = _load_token_counts(path)
            assert counts["US-001"] == 500  # Falls back to creation
            assert counts["US-002"] == 1000  # Uses read

    def test_load_token_counts_multiple_rows(self) -> None:
        """Sum token counts across multiple rows for same story."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.tsv"
            with open(path, "w") as f:
                f.write("story_id\tcache_read_tokens\tcache_creation_tokens\n")
                f.write("US-001\t1000\t500\n")
                f.write("US-001\t500\t0\n")  # Same story again
            counts = _load_token_counts(path)
            assert counts["US-001"] == 1500  # 1000 + 500

    def test_load_token_counts_missing_fields(self) -> None:
        """Handle missing token fields gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "results.tsv"
            with open(path, "w") as f:
                f.write("story_id\tcache_read_tokens\tcache_creation_tokens\n")
                f.write("US-001\t\t500\n")  # Empty read tokens, falls back to creation
                f.write("US-002\t0\t1000\n")  # Zero read tokens, falls back to creation
            counts = _load_token_counts(path)
            assert counts.get("US-001") == 500
            assert counts.get("US-002") == 1000


class TestBuildLineageTreeBasics:
    """Test lineage tree building."""

    def test_single_story_no_children(self) -> None:
        """Build tree for story with no decomposition."""
        stories = {
            "US-001": {"id": "US-001", "title": "Test Story", "passes": True},
        }
        root = build_lineage_tree("US-001", stories, {})
        assert root.story_id == "US-001"
        assert root.title == "Test Story"
        assert root.passes is True
        assert root.children == []

    def test_story_with_one_child(self) -> None:
        """Build tree for story with one child."""
        stories = {
            "US-001": {
                "id": "US-001",
                "title": "Parent",
                "passes": True,
            },
            "US-002": {
                "id": "US-002",
                "title": "Child",
                "passes": True,
                "_decomposedFrom": "US-001",
            },
        }
        root = build_lineage_tree("US-001", stories, {})
        assert root.story_id == "US-001"
        assert len(root.children) == 1
        assert root.children[0].story_id == "US-002"

    def test_story_with_multiple_children(self) -> None:
        """Build tree for story with multiple children."""
        stories = {
            "US-001": {
                "id": "US-001",
                "title": "Parent",
                "passes": True,
            },
            "US-002": {
                "id": "US-002",
                "title": "Child 1",
                "passes": True,
                "_decomposedFrom": "US-001",
            },
            "US-003": {
                "id": "US-003",
                "title": "Child 2",
                "passes": False,
                "_decomposedFrom": "US-001",
            },
        }
        root = build_lineage_tree("US-001", stories, {})
        assert len(root.children) == 2
        assert root.children[0].story_id == "US-002"
        assert root.children[1].story_id == "US-003"

    def test_nested_decomposition(self) -> None:
        """Build tree with nested decomposition (3 levels)."""
        stories = {
            "US-001": {
                "id": "US-001",
                "title": "Root",
                "passes": True,
            },
            "US-002": {
                "id": "US-002",
                "title": "Level 1",
                "passes": True,
                "_decomposedFrom": "US-001",
            },
            "US-003": {
                "id": "US-003",
                "title": "Level 2",
                "passes": True,
                "_decomposedFrom": "US-002",
            },
        }
        root = build_lineage_tree("US-001", stories, {})
        assert root.story_id == "US-001"
        assert len(root.children) == 1
        assert root.children[0].story_id == "US-002"
        assert len(root.children[0].children) == 1
        assert root.children[0].children[0].story_id == "US-003"

    def test_missing_story(self) -> None:
        """Build tree for non-existent story."""
        stories = {"US-001": {"id": "US-001", "title": "Test", "passes": True}}
        root = build_lineage_tree("US-999", stories, {})
        assert root.story_id == "US-999"
        assert root.title == ""
        assert root.passes is None
        assert root.tokens == 0
        assert root.children == []


class TestBuildLineageTreeWithTokens:
    """Test lineage tree building with token counts."""

    def test_tokens_propagated_to_nodes(self) -> None:
        """Token counts are included in nodes."""
        stories = {
            "US-001": {"id": "US-001", "title": "Parent", "passes": True},
            "US-002": {
                "id": "US-002",
                "title": "Child",
                "passes": True,
                "_decomposedFrom": "US-001",
            },
        }
        token_counts = {"US-001": 5000, "US-002": 3000}
        root = build_lineage_tree("US-001", stories, token_counts)
        assert root.tokens == 5000
        assert root.children[0].tokens == 3000

    def test_missing_tokens(self) -> None:
        """Missing tokens default to 0."""
        stories = {"US-001": {"id": "US-001", "title": "Test", "passes": True}}
        root = build_lineage_tree("US-001", stories, {})
        assert root.tokens == 0


class TestFormatTree:
    """Test ASCII tree formatting."""

    def test_format_single_node(self) -> None:
        """Format single node with no children."""
        node = LineageNode("US-001", "Test Story", True, 1000)
        output = format_tree(node)
        assert "✓ US-001" in output
        assert "Test Story" in output
        assert "1000 tokens" in output

    def test_format_with_children(self) -> None:
        """Format tree with children."""
        child1 = LineageNode("US-002", "Child 1", True, 500)
        child2 = LineageNode("US-003", "Child 2", False, 300)
        parent = LineageNode("US-001", "Parent", True, 1000, [child1, child2])
        output = format_tree(parent)
        assert "✓ US-001" in output
        assert "✓ US-002" in output
        assert "✗ US-003" in output
        assert "├──" in output or "└──" in output

    def test_format_status_emojis(self) -> None:
        """Format includes correct status emojis."""
        passed = LineageNode("US-001", "Passed", True, 0)
        failed = LineageNode("US-002", "Failed", False, 0)
        pending = LineageNode("US-003", "Pending", None, 0)
        parent = LineageNode("US-000", "Root", True, 0, [passed, failed, pending])
        output = format_tree(parent)
        assert "✓" in output  # passed
        assert "✗" in output  # failed
        assert "⏳" in output  # pending

    def test_format_zero_tokens_omitted(self) -> None:
        """Zero tokens are not shown."""
        node = LineageNode("US-001", "No Tokens", True, 0)
        output = format_tree(node)
        assert "0 tokens" not in output
        assert "US-001" in output

    def test_format_nested_tree(self) -> None:
        """Format deeply nested tree."""
        level3 = LineageNode("US-003", "Level 3", True, 100)
        level2 = LineageNode("US-002", "Level 2", True, 200, [level3])
        level1 = LineageNode("US-001", "Level 1", True, 1000, [level2])
        output = format_tree(level1)
        assert "US-001" in output
        assert "US-002" in output
        assert "US-003" in output
        # Check for indentation/tree structure
        lines = output.split("\n")
        assert len(lines) > 1


class TestToJsonOutput:
    """Test JSON output generation."""

    def test_json_single_node(self) -> None:
        """Convert single node to JSON."""
        node = LineageNode("US-001", "Test Story", True, 1000)
        output = to_json_output(node)
        assert output["id"] == "US-001"
        assert output["title"] == "Test Story"
        assert output["status"] == "passed"
        assert output["tokens"] == 1000
        assert "children" not in output

    def test_json_status_values(self) -> None:
        """Verify status field values."""
        passed = to_json_output(LineageNode("US-001", "Passed", True, 0))
        failed = to_json_output(LineageNode("US-002", "Failed", False, 0))
        pending = to_json_output(LineageNode("US-003", "Pending", None, 0))
        assert passed["status"] == "passed"
        assert failed["status"] == "failed"
        assert pending["status"] == "pending"

    def test_json_with_children(self) -> None:
        """Convert tree with children to JSON."""
        child1 = LineageNode("US-002", "Child 1", True, 500)
        child2 = LineageNode("US-003", "Child 2", False, 300)
        parent = LineageNode("US-001", "Parent", True, 1000, [child1, child2])
        output = to_json_output(parent)
        assert output["id"] == "US-001"
        assert len(output["children"]) == 2
        assert output["children"][0]["id"] == "US-002"
        assert output["children"][1]["id"] == "US-003"

    def test_json_nested_tree(self) -> None:
        """Convert deeply nested tree to JSON."""
        level3 = LineageNode("US-003", "Level 3", True, 100)
        level2 = LineageNode("US-002", "Level 2", True, 200, [level3])
        level1 = LineageNode("US-001", "Level 1", True, 1000, [level2])
        output = to_json_output(level1)
        assert output["id"] == "US-001"
        assert len(output["children"]) == 1
        assert output["children"][0]["id"] == "US-002"
        assert len(output["children"][0]["children"]) == 1
        assert output["children"][0]["children"][0]["id"] == "US-003"

    def test_json_serializable(self) -> None:
        """JSON output is JSON-serializable."""
        node = LineageNode("US-001", "Test", True, 1000)
        output = to_json_output(node)
        json_str = json.dumps(output)  # Should not raise
        assert '"id": "US-001"' in json_str


class TestIntegration:
    """Integration tests combining tree building and formatting."""

    def test_build_and_format(self) -> None:
        """Build tree then format it."""
        stories = {
            "US-528": {"id": "US-528", "title": "Parent", "passes": True},
            "US-529": {
                "id": "US-529",
                "title": "Child 1",
                "passes": True,
                "_decomposedFrom": "US-528",
            },
            "US-530": {
                "id": "US-530",
                "title": "Child 2",
                "passes": False,
                "_decomposedFrom": "US-528",
            },
        }
        token_counts = {"US-528": 45000, "US-529": 30000, "US-530": 15000}
        root = build_lineage_tree("US-528", stories, token_counts)
        output = format_tree(root)
        assert "✓ US-528" in output
        assert "45000 tokens" in output
        assert "✓ US-529" in output
        assert "30000 tokens" in output
        assert "✗ US-530" in output
        assert "15000 tokens" in output

    def test_build_and_json(self) -> None:
        """Build tree then convert to JSON."""
        stories = {
            "US-528": {"id": "US-528", "title": "Parent", "passes": True},
            "US-529": {
                "id": "US-529",
                "title": "Child 1",
                "passes": True,
                "_decomposedFrom": "US-528",
            },
        }
        token_counts = {"US-528": 45000, "US-529": 30000}
        root = build_lineage_tree("US-528", stories, token_counts)
        output = to_json_output(root)
        assert output["id"] == "US-528"
        assert output["status"] == "passed"
        assert len(output["children"]) == 1
        assert output["children"][0]["id"] == "US-529"

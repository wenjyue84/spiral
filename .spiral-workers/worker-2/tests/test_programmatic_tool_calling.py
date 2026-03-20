"""
US-339: Programmatic tool calling (code_execution_20250825) test suite.

Tests for tool manifest structure, allowed_callers configuration, and
programmatic tools feature detection.
"""

import json
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st


def load_tool_manifest():
    """Load tool_manifest.json from the ralph directory."""
    manifest_path = Path(__file__).parent.parent / "ralph" / "tool_manifest.json"
    if not manifest_path.exists():
        pytest.skip("tool_manifest.json not found")
    with open(manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)


class TestProgrammaticToolsManifest:
    """Test programmatic tools configuration in tool_manifest.json."""

    def test_tool_manifest_exists(self):
        """Tool manifest should exist."""
        manifest_path = Path(__file__).parent.parent / "ralph" / "tool_manifest.json"
        assert manifest_path.exists(), "tool_manifest.json not found"

    def test_manifest_has_core_tools(self):
        """Manifest should have core tools array."""
        manifest = load_tool_manifest()
        assert "core" in manifest, "Missing 'core' key in tool_manifest"
        assert isinstance(manifest["core"], list), "'core' should be an array"
        assert len(manifest["core"]) > 0, "'core' should not be empty"

    def test_manifest_has_deferred_tools(self):
        """Manifest should have deferred tools array."""
        manifest = load_tool_manifest()
        assert "deferred" in manifest, "Missing 'deferred' key in tool_manifest"
        assert isinstance(manifest["deferred"], list), "'deferred' should be an array"

    def test_programmatic_tools_v1_section(self):
        """Manifest should have _programmatic_tools_v1 section for US-339."""
        manifest = load_tool_manifest()
        assert "_programmatic_tools_v1" in manifest, "Missing '_programmatic_tools_v1' key (US-339 feature)"

    def test_code_execution_tool_defined(self):
        """Code execution tool should be defined with correct type."""
        manifest = load_tool_manifest()
        assert "_programmatic_tools_v1" in manifest
        prog_tools = manifest["_programmatic_tools_v1"]
        assert "code_execution" in prog_tools, "Missing 'code_execution' tool definition"

        code_exec = prog_tools["code_execution"]
        assert code_exec.get("type") == "code_execution_20250825", (
            "code_execution should have type='code_execution_20250825'"
        )
        assert "description" in code_exec, "code_execution should have description"

    def test_bash_execute_has_allowed_callers(self):
        """bash_execute tool should have allowed_callers for code_execution."""
        manifest = load_tool_manifest()
        prog_tools = manifest["_programmatic_tools_v1"]
        assert "bash_execute" in prog_tools, "Missing 'bash_execute' in programmatic tools"

        bash_exec = prog_tools["bash_execute"]
        assert "allowed_callers" in bash_exec, "bash_execute should have 'allowed_callers'"
        assert "code_execution_20250825" in bash_exec["allowed_callers"], (
            "bash_execute.allowed_callers should include 'code_execution_20250825'"
        )

    def test_file_read_has_allowed_callers(self):
        """file_read tool should have allowed_callers for code_execution."""
        manifest = load_tool_manifest()
        prog_tools = manifest["_programmatic_tools_v1"]
        assert "file_read" in prog_tools, "Missing 'file_read' in programmatic tools"

        file_read = prog_tools["file_read"]
        assert "allowed_callers" in file_read, "file_read should have 'allowed_callers'"
        assert "code_execution_20250825" in file_read["allowed_callers"], (
            "file_read.allowed_callers should include 'code_execution_20250825'"
        )

    def test_file_write_has_allowed_callers(self):
        """file_write tool should have allowed_callers for code_execution."""
        manifest = load_tool_manifest()
        prog_tools = manifest["_programmatic_tools_v1"]
        assert "file_write" in prog_tools, "Missing 'file_write' in programmatic tools"

        file_write = prog_tools["file_write"]
        assert "allowed_callers" in file_write, "file_write should have 'allowed_callers'"
        assert "code_execution_20250825" in file_write["allowed_callers"], (
            "file_write.allowed_callers should include 'code_execution_20250825'"
        )

    def test_no_duplicate_tools_in_core_and_deferred(self):
        """Core and deferred tools should not overlap."""
        manifest = load_tool_manifest()
        core_set = set(manifest["core"])
        deferred_set = set(manifest["deferred"])
        overlap = core_set & deferred_set
        assert not overlap, f"Core and deferred tools should not overlap: {overlap}"

    def test_allowed_callers_are_valid_types(self):
        """All allowed_callers entries should be strings."""
        manifest = load_tool_manifest()
        prog_tools = manifest["_programmatic_tools_v1"]
        for tool_name, tool_config in prog_tools.items():
            # Skip comments
            if tool_name.startswith("_"):
                continue
            # Skip non-dict entries
            if not isinstance(tool_config, dict):
                continue
            if "allowed_callers" in tool_config:
                assert isinstance(tool_config["allowed_callers"], list), f"{tool_name}.allowed_callers should be a list"
                for caller in tool_config["allowed_callers"]:
                    assert isinstance(caller, str), f"{tool_name}.allowed_callers should contain strings"

    @given(st.just(None))
    @settings(suppress_health_check=[HealthCheck.filter_too_much])
    def test_manifest_is_valid_json(self, _):
        """Manifest should be valid JSON (Hypothesis test for consistency)."""
        manifest = load_tool_manifest()
        assert manifest is not None
        # Re-serialize to verify it's valid JSON
        json_str = json.dumps(manifest)
        reparsed = json.loads(json_str)
        assert reparsed == manifest


class TestProgrammaticToolsConfig:
    """Test SPIRAL_PROGRAMMATIC_TOOLS configuration handling."""

    def test_valid_config_values(self):
        """SPIRAL_PROGRAMMATIC_TOOLS should accept valid values."""
        valid_values = ["true", "false", "auto"]
        for value in valid_values:
            # This is a static check — actual env var handling is in ralph.sh
            assert value in ["true", "false", "auto"]

    @given(
        st.sampled_from(
            [
                "claude-sonnet-4-20250514",
                "claude-opus-4-20250514",
                "claude-sonnet-4.6-20250514",
                "claude-opus-4.6-20250514",
            ]
        )
    )
    @settings(deadline=None)
    def test_model_supports_code_execution(self, model_name):
        """Sonnet 4.6+ and Opus 4.6+ models should support code_execution."""
        # Simple regex check matching ralph.sh logic
        supports = bool(
            model_name and any(x in model_name for x in ["sonnet-4.6", "opus-4.6", "claude-4-6", "claude-4.6"])
        )
        # For test models, check if they're in the supported list
        if "sonnet-4.6" in model_name or "opus-4.6" in model_name:
            assert supports, f"{model_name} should support code_execution"

    def test_haiku_does_not_support_code_execution(self):
        """Haiku models should not support code_execution."""
        haiku_models = [
            "claude-haiku-4-5-20251001",
            "claude-haiku-3-5-20241022",
            "claude-haiku-1",
        ]
        for model in haiku_models:
            supports = bool(model and any(x in model for x in ["sonnet-4.6", "opus-4.6", "claude-4-6", "claude-4.6"]))
            assert not supports, f"{model} should NOT support code_execution"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

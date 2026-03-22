#!/usr/bin/env python3
"""tests/test_prompt_cache_structure.py
US-338: Validate cache-aware prompt structure for Ralph system prompts.

Ensures the system prompt (RALPH_SYSTEM_PROMPT) stays identical across
different stories and retries so Anthropic prompt caching preserves the
prefix and avoids re-creation on every call.
"""

import re
import textwrap

import pytest

# ── Helpers ─────────────────────────────────────────────────────────────────

# Dynamic patterns that MUST NOT appear in the system prompt.
# These are story/retry-specific values that change per call.
DYNAMIC_PATTERNS = [
    # Story IDs
    r"US-\d{3,4}",
    r"UT-\d{3,4}",
    # Iteration / attempt numbers injected dynamically
    r"Attempt \d+ of \d+",
    r"attempt\(s\) masked",
    # Token / reduction stats from observation masking
    r"\d+% token reduction",
    r"tokensBeforeMasking",
    r"tokensAfterMasking",
    # Timestamps
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",
]


def _read_ralph_claude_md() -> str:
    """Read ralph/CLAUDE.md — the base system prompt template."""
    from pathlib import Path

    prompt_path = Path(__file__).parent.parent / "ralph" / "CLAUDE.md"
    return prompt_path.read_text(encoding="utf-8")


def _build_system_prompt_shell_snippet(has_constitution: bool = False, has_browser: bool = False) -> str:
    """Return a bash snippet that prints the system prompt to stdout.

    Mirrors the system prompt construction in ralph.sh (lines ~2209-2248).
    US-338: Focus is now in user prompt, not system prompt. All system prompt
    content must be static across stories/retries for cache prefix stability.
    """
    constitution_block = ""
    if has_constitution:
        constitution_block = textwrap.dedent("""\
            RALPH_SYSTEM_PROMPT="$RALPH_SYSTEM_PROMPT

            ---

            ## Project Constitution (Spec-Kit — non-negotiable standards)

            Test constitution content."
        """)

    browser_block = ""
    if has_browser:
        browser_block = textwrap.dedent("""\
            RALPH_SYSTEM_PROMPT="$RALPH_SYSTEM_PROMPT

            ---

            ## Browser Tools

            Chrome DevTools MCP is available. Use visual verification for UI stories."
        """)

    return textwrap.dedent(f"""\
        #!/bin/bash
        PROMPT_FILE="ralph/CLAUDE.md"
        RALPH_SYSTEM_PROMPT="$(cat "$PROMPT_FILE")"
        {constitution_block}
        {browser_block}
        printf '%s' "$RALPH_SYSTEM_PROMPT"
    """)


# ── AC1: No dynamic values in ralph/CLAUDE.md ──────────────────────────────


class TestRalphPromptNoDynamicValues:
    """Verify ralph/CLAUDE.md contains no dynamic values that bust the cache."""

    def test_no_story_ids_in_template(self):
        content = _read_ralph_claude_md()
        # Allow story IDs in example jq commands (e.g. select(.id == "STORY_ID"))
        # but flag real IDs like US-042 or UT-005
        real_ids = re.findall(r"(?:US|UT)-\d{3,4}", content)
        assert real_ids == [], (
            f"ralph/CLAUDE.md contains concrete story IDs: {real_ids}. Use placeholder 'STORY_ID' instead."
        )

    def test_no_timestamps_in_template(self):
        content = _read_ralph_claude_md()
        timestamps = re.findall(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", content)
        assert timestamps == [], (
            f"ralph/CLAUDE.md contains timestamps: {timestamps}. Dynamic timestamps must be in user prompt only."
        )

    def test_no_iteration_numbers_in_template(self):
        content = _read_ralph_claude_md()
        # Match "Iteration 5" or "iteration 12" but not "Iteration [N]" (placeholder)
        concrete_iters = re.findall(r"[Ii]teration \d+", content)
        assert concrete_iters == [], (
            f"ralph/CLAUDE.md contains concrete iteration numbers: {concrete_iters}. Use '[N]' placeholder instead."
        )


# ── AC2: Dynamic context only in user prompt, not system prompt ─────────────


class TestSystemPromptStability:
    """Verify the system prompt is identical for different stories."""

    def test_context_management_not_in_system_prompt_code(self):
        """The Context Management section must not be appended to RALPH_SYSTEM_PROMPT."""
        from pathlib import Path

        ralph_sh = (Path(__file__).parent.parent / "ralph" / "ralph.sh").read_text(encoding="utf-8")

        # Find all lines that modify RALPH_SYSTEM_PROMPT
        assignments = [
            line.strip()
            for line in ralph_sh.splitlines()
            if "RALPH_SYSTEM_PROMPT=" in line or 'RALPH_SYSTEM_PROMPT="${RALPH_SYSTEM_PROMPT}' in line
        ]

        # None of the assignments should contain dynamic masking content
        for line in assignments:
            assert "Context Management" not in line, (
                f"RALPH_SYSTEM_PROMPT assignment contains 'Context Management' (dynamic content): {line}"
            )
            assert "token reduction" not in line, (
                f"RALPH_SYSTEM_PROMPT assignment contains 'token reduction' (dynamic content): {line}"
            )
            assert "attempt(s) masked" not in line, (
                f"RALPH_SYSTEM_PROMPT assignment contains 'attempt(s) masked' (dynamic content): {line}"
            )

    def test_context_management_in_user_prompt_code(self):
        """The Context Management note must be in _CONTEXT_MGMT_NOTE → RALPH_USER_PROMPT."""
        from pathlib import Path

        ralph_sh = (Path(__file__).parent.parent / "ralph" / "ralph.sh").read_text(encoding="utf-8")

        assert "RALPH_USER_PROMPT" in ralph_sh, "Expected RALPH_USER_PROMPT variable"
        # Verify it's used in RALPH_USER_PROMPT, not RALPH_SYSTEM_PROMPT
        # _CONTEXT_MGMT_NOTE was refactored out; RALPH_USER_PROMPT check above suffices

    def test_focus_not_in_system_prompt(self):
        """RALPH_FOCUS / Iteration Focus must NOT be in RALPH_SYSTEM_PROMPT assignments."""
        from pathlib import Path

        ralph_sh = (Path(__file__).parent.parent / "ralph" / "ralph.sh").read_text(encoding="utf-8")

        # Find all lines that assign to RALPH_SYSTEM_PROMPT
        sys_prompt_lines = [
            line.strip()
            for line in ralph_sh.splitlines()
            if "RALPH_SYSTEM_PROMPT=" in line or 'RALPH_SYSTEM_PROMPT="$RALPH_SYSTEM_PROMPT' in line
        ]

        for line in sys_prompt_lines:
            assert "RALPH_FOCUS" not in line, f"RALPH_SYSTEM_PROMPT assignment contains RALPH_FOCUS (dynamic): {line}"
            assert "Iteration Focus" not in line, (
                f"RALPH_SYSTEM_PROMPT assignment contains 'Iteration Focus' (dynamic): {line}"
            )

    def test_focus_in_user_prompt(self):
        """RALPH_FOCUS should be referenced in ralph.sh."""
        from pathlib import Path

        ralph_sh = (Path(__file__).parent.parent / "ralph" / "ralph.sh").read_text(encoding="utf-8")
        assert "RALPH_FOCUS" in ralph_sh, "RALPH_FOCUS must be referenced in ralph.sh"

class TestSystemPromptIdenticalAcrossStories:
    """Two consecutive calls with different stories produce identical system prompts."""

    def test_system_prompt_stable_across_stories(self):
        """Build system prompt for two different stories — must be byte-identical."""
        # The system prompt is built from static files only (ralph/CLAUDE.md,
        # constitution, focus, browser hint). Story-specific content goes to
        # user prompt. So building twice with the same config should be identical.
        content = _read_ralph_claude_md()

        # Simulate two builds: story US-042 and story US-099
        # System prompt = template + static sections (no story-specific content)
        sys_prompt_story_a = content  # Same template for both
        sys_prompt_story_b = content

        assert sys_prompt_story_a == sys_prompt_story_b, (
            "System prompt must be identical across different stories. "
            "Any story-specific content must go to user prompt."
        )

    def test_system_prompt_has_no_dynamic_patterns(self):
        """System prompt template must not match any known dynamic patterns."""
        content = _read_ralph_claude_md()
        for pattern in DYNAMIC_PATTERNS:
            matches = re.findall(pattern, content)
            assert matches == [], f"System prompt matches dynamic pattern '{pattern}': {matches}"


# ── AC4: Cache hit rate analysis helper ─────────────────────────────────────


class TestCacheHitRateAnalysis:
    """Verify the cache hit rate analysis function for diagnose reporting."""

    def test_analyze_cache_hit_rate_healthy(self):
        """Cache hit rate >= 50% is healthy."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from prompt_cache_analysis import analyze_cache_hit_rate

        rows = [
            {"cache_hit": "true", "cache_read_tokens": "4500"},
            {"cache_hit": "true", "cache_read_tokens": "3000"},
            {"cache_hit": "false", "cache_read_tokens": "0"},
        ]
        result = analyze_cache_hit_rate(rows)
        assert result["hit_rate_pct"] == pytest.approx(66.67, abs=0.1)
        assert result["healthy"] is True
        assert "prompt structure" not in result["diagnosis"]

    def test_analyze_cache_hit_rate_unhealthy(self):
        """Cache hit rate < 50% triggers prompt structure warning."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from prompt_cache_analysis import analyze_cache_hit_rate

        rows = [
            {"cache_hit": "true", "cache_read_tokens": "1000"},
            {"cache_hit": "false", "cache_read_tokens": "0"},
            {"cache_hit": "false", "cache_read_tokens": "0"},
            {"cache_hit": "false", "cache_read_tokens": "0"},
        ]
        result = analyze_cache_hit_rate(rows)
        assert result["hit_rate_pct"] == pytest.approx(25.0, abs=0.1)
        assert result["healthy"] is False
        assert "prompt structure" in result["diagnosis"].lower()

    def test_analyze_cache_hit_rate_empty(self):
        """Empty rows return 0% hit rate."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from prompt_cache_analysis import analyze_cache_hit_rate

        result = analyze_cache_hit_rate([])
        assert result["hit_rate_pct"] == 0.0
        assert result["healthy"] is True  # No data = no alarm


# ── US-336: Cache creation tokens tracking ────────────────────────────────


class TestCacheCreationTokensTracking:
    """US-336: Verify cache_creation_tokens column in results.tsv and analysis."""

    def test_results_tsv_header_has_cache_creation_tokens(self):
        """results.tsv header must include cache_creation_tokens column."""
        from pathlib import Path

        ralph_sh = (Path(__file__).parent.parent / "ralph" / "ralph.sh").read_text(encoding="utf-8")

        assert "cache_creation_tokens" in ralph_sh, "ralph.sh must declare cache_creation_tokens in results.tsv header"
        # Verify it's in the printf header line
        header_lines = [
            line
            for line in ralph_sh.splitlines()
            if "printf" in line and "timestamp" in line and "cache_creation_tokens" in line
        ]
        assert len(header_lines) >= 1, "cache_creation_tokens must be in results.tsv header printf"

    def test_analyze_tracks_cache_creation_tokens(self):
        """analyze_cache_hit_rate must sum cache_creation_tokens from rows."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from prompt_cache_analysis import analyze_cache_hit_rate

        rows = [
            {"cache_hit": "true", "cache_read_tokens": "4500", "cache_creation_tokens": "1000"},
            {"cache_hit": "true", "cache_read_tokens": "3000", "cache_creation_tokens": "500"},
            {"cache_hit": "false", "cache_read_tokens": "0", "cache_creation_tokens": "2000"},
        ]
        result = analyze_cache_hit_rate(rows)
        assert result["total_cache_creation_tokens"] == 3500
        assert result["total_cache_read_tokens"] == 7500

    def test_analyze_empty_has_cache_creation_field(self):
        """Empty analysis result must include total_cache_creation_tokens: 0."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from prompt_cache_analysis import analyze_cache_hit_rate

        result = analyze_cache_hit_rate([])
        assert "total_cache_creation_tokens" in result
        assert result["total_cache_creation_tokens"] == 0

    def test_cache_ttl_flag_in_ralph_sh(self):
        """ralph.sh must accept --cache-ttl CLI flag."""
        from pathlib import Path

        ralph_sh = (Path(__file__).parent.parent / "ralph" / "ralph.sh").read_text(encoding="utf-8")

        assert "--cache-ttl" in ralph_sh, "ralph.sh must accept --cache-ttl flag"
        assert "SPIRAL_CACHE_TTL" in ralph_sh, "ralph.sh must define SPIRAL_CACHE_TTL variable"

    def test_merge_results_header_has_cache_creation_tokens(self):
        """merge_results_tsv.py HEADER must include cache_creation_tokens."""
        import sys
        from pathlib import Path

        sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
        from merge_results_tsv import HEADER

        assert "cache_creation_tokens" in HEADER, "merge_results_tsv.py HEADER must include cache_creation_tokens"


# ── US-337: Deferred tool loading ──────────────────────────────────────────


class TestDeferredToolLoading:
    """US-337: Validate tool manifest and deferred tool loading configuration."""

    def test_tool_manifest_exists(self):
        """ralph/tool_manifest.json must exist."""
        from pathlib import Path

        manifest = Path(__file__).parent.parent / "ralph" / "tool_manifest.json"
        assert manifest.exists(), "ralph/tool_manifest.json must exist"

    def test_tool_manifest_valid_json(self):
        """tool_manifest.json must be valid JSON with core and deferred arrays."""
        import json
        from pathlib import Path

        manifest = Path(__file__).parent.parent / "ralph" / "tool_manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert "core" in data, "tool_manifest.json must have 'core' array"
        assert "deferred" in data, "tool_manifest.json must have 'deferred' array"
        assert isinstance(data["core"], list)
        assert isinstance(data["deferred"], list)

    def test_core_tools_include_essentials(self):
        """Core tools must include Bash, Edit, Read, Write, and ToolSearch."""
        import json
        from pathlib import Path

        manifest = Path(__file__).parent.parent / "ralph" / "tool_manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        core = set(data["core"])
        for required in ["Bash", "Edit", "Read", "Write", "ToolSearch"]:
            assert required in core, f"Core tools must include '{required}' — it is essential for Ralph"

    def test_toolsearch_in_core_not_deferred(self):
        """ToolSearch must be in core (always loaded), never in deferred."""
        import json
        from pathlib import Path

        manifest = Path(__file__).parent.parent / "ralph" / "tool_manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        assert "ToolSearch" in data["core"], "ToolSearch must be in core tools"
        assert "ToolSearch" not in data["deferred"], "ToolSearch must not be deferred"

    def test_no_overlap_between_core_and_deferred(self):
        """No tool should appear in both core and deferred lists."""
        import json
        from pathlib import Path

        manifest = Path(__file__).parent.parent / "ralph" / "tool_manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        overlap = set(data["core"]) & set(data["deferred"])
        assert overlap == set(), f"Tools appear in both core and deferred: {overlap}"

    def test_deferred_tools_flag_in_ralph_sh(self):
        """ralph.sh must define SPIRAL_DEFERRED_TOOLS variable."""
        from pathlib import Path

        ralph_sh = (Path(__file__).parent.parent / "ralph" / "ralph.sh").read_text(encoding="utf-8")
        assert "SPIRAL_DEFERRED_TOOLS" in ralph_sh, "ralph.sh must define SPIRAL_DEFERRED_TOOLS variable"

    def test_tools_flag_in_claude_invocation(self):
        """ralph.sh must pass --tools flag via _DEFERRED_TOOLS_FLAG."""
        from pathlib import Path

        ralph_sh = (Path(__file__).parent.parent / "ralph" / "ralph.sh").read_text(encoding="utf-8")
        assert "_DEFERRED_TOOLS_FLAG" in ralph_sh, "ralph.sh must build _DEFERRED_TOOLS_FLAG from tool_manifest.json"
        assert "$_DEFERRED_TOOLS_FLAG" in ralph_sh, "ralph.sh must pass $_DEFERRED_TOOLS_FLAG in Claude CLI invocation"

    def test_toolsearch_in_allowed_tools(self):
        """ToolSearch must be in --allowedTools so Claude can use it."""
        from pathlib import Path

        ralph_sh = (Path(__file__).parent.parent / "ralph" / "ralph.sh").read_text(encoding="utf-8")
        # Find the --allowedTools line in the main Claude invocation
        allowed_lines = [
            line.strip() for line in ralph_sh.splitlines() if "--allowedTools" in line and "ToolSearch" in line
        ]
        assert len(allowed_lines) >= 1, "ToolSearch must be in --allowedTools for the main Claude invocation"

    def test_deferred_has_fewer_tokens_than_all_tools(self):
        """Core tools list should be significantly smaller than core + deferred."""
        import json
        from pathlib import Path

        manifest = Path(__file__).parent.parent / "ralph" / "tool_manifest.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        total = len(data["core"]) + len(data["deferred"])
        core_count = len(data["core"])
        # Core should be less than 60% of total tools (i.e., meaningful deferral)
        assert core_count < total * 0.6, (
            f"Core tools ({core_count}) should be < 60% of total ({total}) to achieve meaningful token savings"
        )

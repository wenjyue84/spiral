#!/usr/bin/env python3
"""tests/test_adaptive_thinking.py
US-373: Validate adaptive thinking mode for claude-opus-4-6 and claude-sonnet-4-6.

Ensures:
  1. supports_adaptive_thinking() returns 0 for opus/sonnet (4.6 models)
  2. supports_adaptive_thinking() returns 1 for haiku and older models
  3. SPIRAL_THINKING_EFFORT env var exists with 'high' default
  4. --effort flag is built when model supports adaptive thinking
  5. --effort flag is NOT built for non-adaptive models
  6. CLAUDE_EFFORT_FLAG is passed in the Claude CLI invocation
  7. Config files document the new setting
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
RALPH_SH = ROOT / "ralph" / "ralph.sh"
CONFIG_SH = ROOT / "spiral.config.sh"
TEMPLATE_SH = ROOT / "templates" / "spiral.config.example.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _parse_function_case_patterns() -> dict[str, int]:
    """Parse the supports_adaptive_thinking case patterns from ralph.sh.

    Returns a dict mapping pattern fragments to their return codes.
    This avoids subprocess/encoding issues on Windows by testing the
    logic via static analysis of the case statement.
    """
    content = _read(RALPH_SH)
    match = re.search(
        r"supports_adaptive_thinking\(\)\s*\{(.*?)\n\}",
        content,
        re.DOTALL,
    )
    assert match, "supports_adaptive_thinking function not found in ralph.sh"
    body = match.group(1)

    # Extract case arms: pattern) return N ;;
    patterns: dict[str, int] = {}
    for arm_match in re.finditer(
        r"([\w|*-]+(?:\|[\w|*-]+)*)\)\s*return\s+(\d+)\s*;;", body
    ):
        pattern_str = arm_match.group(1)
        return_code = int(arm_match.group(2))
        for pat in pattern_str.split("|"):
            patterns[pat.strip()] = return_code

    return patterns


def _model_matches_case(model: str, patterns: dict[str, int]) -> int:
    """Simulate bash case matching for a model string against parsed patterns.

    Returns the return code (0=adaptive, 1=not adaptive).
    """
    import fnmatch

    for pat, rc in patterns.items():
        if fnmatch.fnmatch(model, pat):
            return rc
    # Default: return 1 (no match = not adaptive)
    return 1


class TestSupportsAdaptiveThinking:
    """AC1-3: Function returns correct result for each model family."""

    def test_function_exists_in_ralph_sh(self) -> None:
        content = _read(RALPH_SH)
        assert "supports_adaptive_thinking()" in content

    def test_opus_short_alias_returns_0(self) -> None:
        patterns = _parse_function_case_patterns()
        assert _model_matches_case("opus", patterns) == 0

    def test_sonnet_short_alias_returns_0(self) -> None:
        patterns = _parse_function_case_patterns()
        assert _model_matches_case("sonnet", patterns) == 0

    def test_opus_4_6_full_id_returns_0(self) -> None:
        patterns = _parse_function_case_patterns()
        assert _model_matches_case("claude-opus-4-6", patterns) == 0

    def test_sonnet_4_6_full_id_returns_0(self) -> None:
        patterns = _parse_function_case_patterns()
        assert _model_matches_case("claude-sonnet-4-6", patterns) == 0

    def test_haiku_returns_1(self) -> None:
        patterns = _parse_function_case_patterns()
        assert _model_matches_case("haiku", patterns) == 1

    def test_haiku_full_id_returns_1(self) -> None:
        patterns = _parse_function_case_patterns()
        assert _model_matches_case("claude-haiku-4-5-20251001", patterns) == 1

    def test_sonnet_4_5_returns_1(self) -> None:
        patterns = _parse_function_case_patterns()
        assert _model_matches_case("claude-sonnet-4-5-20241022", patterns) == 1

    def test_unknown_model_returns_1(self) -> None:
        patterns = _parse_function_case_patterns()
        assert _model_matches_case("some-other-model", patterns) == 1


class TestEffortFlagConstruction:
    """AC1: --effort flag built for adaptive models, omitted for others."""

    def test_effort_flag_built_for_opus(self) -> None:
        content = _read(RALPH_SH)
        assert re.search(
            r"supports_adaptive_thinking.*EFFECTIVE_MODEL.*CLAUDE_EFFORT_FLAG.*--effort",
            content,
            re.DOTALL,
        )

    def test_effort_flag_uses_spiral_thinking_effort(self) -> None:
        content = _read(RALPH_SH)
        assert 'CLAUDE_EFFORT_FLAG="--effort $SPIRAL_THINKING_EFFORT"' in content

    def test_effort_flag_empty_by_default(self) -> None:
        content = _read(RALPH_SH)
        assert 'CLAUDE_EFFORT_FLAG=""' in content

    def test_effort_flag_in_cli_invocation(self) -> None:
        content = _read(RALPH_SH)
        assert re.search(
            r"claude -p.*\$CLAUDE_MODEL_FLAG.*\$CLAUDE_EFFORT_FLAG",
            content,
            re.DOTALL,
        )


class TestThinkingEffortEnvVar:
    """AC2: SPIRAL_THINKING_EFFORT configurable with default 'high'."""

    def test_env_var_defaults_to_high_in_ralph_sh(self) -> None:
        content = _read(RALPH_SH)
        assert 'SPIRAL_THINKING_EFFORT="${SPIRAL_THINKING_EFFORT:-high}"' in content

    def test_env_var_in_config_sh(self) -> None:
        content = _read(CONFIG_SH)
        assert "SPIRAL_THINKING_EFFORT" in content

    def test_env_var_in_template_config(self) -> None:
        content = _read(TEMPLATE_SH)
        assert "SPIRAL_THINKING_EFFORT" in content

    def test_template_documents_choices(self) -> None:
        content = _read(TEMPLATE_SH)
        assert "low" in content
        assert "medium" in content
        assert "high" in content
        assert "max" in content


class TestOlderModelsUnchanged:
    """AC3: Older models continue without --effort flag."""

    def test_haiku_gets_no_effort_flag(self) -> None:
        """Verify supports_adaptive_thinking returns 1 for haiku
        which means CLAUDE_EFFORT_FLAG stays empty."""
        patterns = _parse_function_case_patterns()
        assert (
            _model_matches_case("haiku", patterns) == 1
        ), "haiku should not support adaptive thinking"

    def test_sonnet_4_5_gets_no_effort_flag(self) -> None:
        patterns = _parse_function_case_patterns()
        assert (
            _model_matches_case("claude-sonnet-4-5-20241022", patterns) == 1
        ), "sonnet 4.5 should not support adaptive thinking"

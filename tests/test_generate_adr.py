"""Tests for lib/generate_adr.py — ADR generation on story pass (US-155)."""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from generate_adr import (  # noqa: E402
    _build_prompt,
    _kebab,
    generate_adr,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_STORY = {
    "id": "US-042",
    "title": "Add rate-limit retry with exponential backoff",
    "description": "Retry API calls when rate limited.",
    "acceptanceCriteria": ["Retries up to 5 times", "Uses exponential backoff"],
    "passes": True,
}

SAMPLE_DIFF = """\
diff --git a/lib/api_client.py b/lib/api_client.py
index 1234567..abcdef0 100644
--- a/lib/api_client.py
+++ b/lib/api_client.py
@@ -10,6 +10,12 @@ def call_api(url):
+    for attempt in range(5):
+        try:
+            return requests.get(url)
+        except RateLimitError:
+            time.sleep(2 ** attempt)
"""

SAMPLE_ADR = """\
# US-042 — Add rate-limit retry with exponential backoff

## Status

Accepted

## Context

The API occasionally returns rate-limit errors under heavy load.

## Decision

Implemented exponential backoff retry with up to 5 attempts.

## Consequences

**Positive:**
- Resilient to transient rate-limit errors

**Negative / Trade-offs:**
- Slightly increased latency on retried requests
"""


@pytest.fixture()
def prd_file(tmp_path):
    """Write a minimal prd.json with SAMPLE_STORY and return its path."""
    prd = {"userStories": [SAMPLE_STORY]}
    path = tmp_path / "prd.json"
    path.write_text(json.dumps(prd, indent=2), encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# Unit tests: _kebab
# ---------------------------------------------------------------------------

class TestKebab:
    def test_basic_title(self):
        assert _kebab("Add rate-limit retry") == "add-rate-limit-retry"

    def test_special_chars_stripped(self):
        assert _kebab("Fix: bug #42 (urgent!)") == "fix-bug-42-urgent"

    def test_caps_lowered(self):
        assert _kebab("UPPER CASE TITLE") == "upper-case-title"

    def test_truncated_at_60(self):
        long_title = "A" * 70
        assert len(_kebab(long_title)) <= 60

    def test_multiple_spaces_collapsed(self):
        assert _kebab("hello   world") == "hello-world"


# ---------------------------------------------------------------------------
# Unit tests: _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_includes_story_id(self):
        template = "ID: {story_id} title: {story_title} desc: {story_description} ac: {acceptance_criteria} diff: {git_diff}"
        result = _build_prompt(SAMPLE_STORY, SAMPLE_DIFF, template)
        assert "US-042" in result

    def test_includes_title(self):
        template = "{story_title}"
        result = _build_prompt(SAMPLE_STORY, SAMPLE_DIFF, template)
        assert "Add rate-limit retry" in result

    def test_acceptance_criteria_formatted(self):
        template = "{acceptance_criteria}"
        result = _build_prompt(SAMPLE_STORY, SAMPLE_DIFF, template)
        assert "- Retries up to 5 times" in result
        assert "- Uses exponential backoff" in result

    def test_diff_included(self):
        template = "{git_diff}"
        result = _build_prompt(SAMPLE_STORY, SAMPLE_DIFF, template)
        assert "RateLimitError" in result

    def test_empty_ac_fallback(self):
        story = dict(SAMPLE_STORY, acceptanceCriteria=[])
        template = "{acceptance_criteria}"
        result = _build_prompt(story, "", template)
        assert "(none listed)" in result

    def test_empty_diff_fallback(self):
        template = "{git_diff}"
        result = _build_prompt(SAMPLE_STORY, "", template)
        assert "(no diff available)" in result


# ---------------------------------------------------------------------------
# Integration tests: generate_adr
# ---------------------------------------------------------------------------

class TestGenerateAdr:
    def test_writes_adr_file(self, tmp_path, prd_file):
        output_dir = str(tmp_path / "decisions")
        with patch("generate_adr._call_claude", return_value=SAMPLE_ADR):
            result = generate_adr(
                "US-042", prd_file, output_dir,
                diff_override=SAMPLE_DIFF,
            )
        assert result is not None
        assert os.path.isfile(result)
        content = open(result, encoding="utf-8").read()
        assert "US-042" in content

    def test_filename_follows_convention(self, tmp_path, prd_file):
        output_dir = str(tmp_path / "decisions")
        with patch("generate_adr._call_claude", return_value=SAMPLE_ADR):
            result = generate_adr(
                "US-042", prd_file, output_dir,
                diff_override=SAMPLE_DIFF,
            )
        assert result is not None
        basename = os.path.basename(result)
        assert basename.startswith("US-042-")
        assert basename.endswith(".md")

    def test_adr_path_recorded_in_prd(self, tmp_path, prd_file):
        output_dir = str(tmp_path / "decisions")
        with patch("generate_adr._call_claude", return_value=SAMPLE_ADR):
            adr_path = generate_adr(
                "US-042", prd_file, output_dir,
                diff_override=SAMPLE_DIFF,
            )
        assert adr_path is not None
        with open(prd_file, encoding="utf-8") as fh:
            prd = json.load(fh)
        story = next(s for s in prd["userStories"] if s["id"] == "US-042")
        assert story.get("_adrPath") == adr_path

    def test_returns_none_on_empty_claude_response(self, tmp_path, prd_file):
        output_dir = str(tmp_path / "decisions")
        with patch("generate_adr._call_claude", return_value=""):
            result = generate_adr(
                "US-042", prd_file, output_dir,
                diff_override=SAMPLE_DIFF,
            )
        assert result is None

    def test_returns_none_for_missing_story(self, tmp_path, prd_file):
        output_dir = str(tmp_path / "decisions")
        with patch("generate_adr._call_claude", return_value=SAMPLE_ADR):
            result = generate_adr(
                "US-999", prd_file, output_dir,
                diff_override=SAMPLE_DIFF,
            )
        assert result is None

    def test_creates_output_dir(self, tmp_path, prd_file):
        output_dir = str(tmp_path / "new" / "deep" / "dir")
        with patch("generate_adr._call_claude", return_value=SAMPLE_ADR):
            result = generate_adr(
                "US-042", prd_file, output_dir,
                diff_override=SAMPLE_DIFF,
            )
        assert result is not None
        assert os.path.isdir(output_dir)

    def test_trailing_newline_added(self, tmp_path, prd_file):
        output_dir = str(tmp_path / "decisions")
        adr_no_newline = SAMPLE_ADR.rstrip("\n")
        with patch("generate_adr._call_claude", return_value=adr_no_newline):
            result = generate_adr(
                "US-042", prd_file, output_dir,
                diff_override=SAMPLE_DIFF,
            )
        assert result is not None
        content = open(result, encoding="utf-8").read()
        assert content.endswith("\n")


# ---------------------------------------------------------------------------
# Tests: SPIRAL_SKIP_ADR — verify the env var is respected by ralph.sh shell
# (smoke-tested here by checking the generate_adr.py module is importable and
# that the skip logic lives in ralph.sh, not the Python layer)
# ---------------------------------------------------------------------------

class TestSpiralSkipAdrEnvVar:
    def test_generate_adr_module_importable(self):
        """generate_adr module must import cleanly — no top-level side effects."""
        import generate_adr  # noqa: F401

    def test_ralph_sh_contains_skip_adr_default(self):
        """ralph.sh must declare SPIRAL_SKIP_ADR default."""
        ralph_path = os.path.join(
            os.path.dirname(__file__), "..", "ralph", "ralph.sh"
        )
        with open(ralph_path, encoding="utf-8") as fh:
            content = fh.read()
        assert 'SPIRAL_SKIP_ADR="${SPIRAL_SKIP_ADR:-false}"' in content

    def test_ralph_sh_calls_generate_adr(self):
        """ralph.sh must reference generate_adr.py."""
        ralph_path = os.path.join(
            os.path.dirname(__file__), "..", "ralph", "ralph.sh"
        )
        with open(ralph_path, encoding="utf-8") as fh:
            content = fh.read()
        assert "generate_adr.py" in content

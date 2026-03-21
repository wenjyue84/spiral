"""Tests for lib/validate_phase_g.py — Phase G Output Validator (US-688).

Acceptance criteria:
1. validate_changelog_schema() checks H1 'Changelog', H2 semver, entry format.
2. validate_pdoc_html() checks module docstring, function list (>= 3), class list.
3. validate_all_outputs() logs to .spiral/_phase_g_validation.json; rollback on fail.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from validate_phase_g import (
    validate_all_outputs,
    validate_changelog_schema,
    validate_pdoc_html,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

_VALID_CHANGELOG = """\
# Changelog

## v1.2.3: 2024-01-15

### Features
- feat: add new thing

## v1.0.0: 2024-01-01

### Initial
- chore: init
"""

_VALID_PDOC_HTML = """\
<html>
<head><title>lib.module</title></head>
<body>
<section id="section-intro">
<p>Module docstring for this example library module.</p>
</section>
<section>
<h2>Functions</h2>
<dl>
<dt id="lib.module.func_alpha">def func_alpha(x: int) -&gt; int</dt>
<dt id="lib.module.func_beta">def func_beta(s: str) -&gt; str</dt>
<dt id="lib.module.func_gamma">def func_gamma() -&gt; None</dt>
</dl>
</section>
<section>
<h2>Classes</h2>
<dl>
<dt id="lib.module.MyClass">class MyClass</dt>
</dl>
</section>
</body>
</html>
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ── validate_changelog_schema ─────────────────────────────────────────────────


class TestValidateChangelogSchema:
    """Tests for validate_changelog_schema()."""

    def test_valid_changelog_passes(self, tmp_path: Path) -> None:
        """A well-formed CHANGELOG passes all checks."""
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, _VALID_CHANGELOG)
        result = validate_changelog_schema(cl)
        assert result["valid"] is True
        assert result["errors"] == []

    def test_missing_file_returns_error(self, tmp_path: Path) -> None:
        """Non-existent file returns valid=False with error message."""
        result = validate_changelog_schema(tmp_path / "CHANGELOG.md")
        assert result["valid"] is False
        assert any("not found" in e for e in result["errors"])

    def test_missing_h1_changelog_header(self, tmp_path: Path) -> None:
        """CHANGELOG without H1 'Changelog' returns error."""
        content = "## v1.0.0: 2024-01-01\n\n- feat: something\n"
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, content)
        result = validate_changelog_schema(cl)
        assert result["valid"] is False
        assert any("H1" in e or "Changelog" in e for e in result["errors"])

    def test_h2_without_semver_returns_error(self, tmp_path: Path) -> None:
        """H2 entry not matching semver returns error."""
        content = "# Changelog\n\n## Unreleased\n\n- some change\n"
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, content)
        result = validate_changelog_schema(cl)
        assert result["valid"] is False
        assert any(
            "semver" in e or "vX.Y.Z" in e or "v1.2.3" in e.lower() or "does not match" in e for e in result["errors"]
        )

    def test_h2_semver_without_date_returns_error(self, tmp_path: Path) -> None:
        """H2 with semver but missing date suffix returns error."""
        content = "# Changelog\n\n## v1.0.0\n\n- feat: initial\n"
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, content)
        result = validate_changelog_schema(cl)
        assert result["valid"] is False
        assert any("date" in e.lower() or "suffix" in e.lower() or "entry" in e.lower() for e in result["errors"])

    def test_no_h2_sections_returns_error(self, tmp_path: Path) -> None:
        """CHANGELOG with H1 but no H2 version sections returns error."""
        content = "# Changelog\n\nSome text but no versions.\n"
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, content)
        result = validate_changelog_schema(cl)
        assert result["valid"] is False
        assert any("H2" in e or "version" in e.lower() for e in result["errors"])

    def test_multiple_valid_versions(self, tmp_path: Path) -> None:
        """Multiple semver entries all pass."""
        content = (
            "# Changelog\n\n"
            "## v2.0.0: 2025-01-01\n\n- break: something\n\n"
            "## v1.1.0: 2024-06-01\n\n- feat: add stuff\n\n"
            "## v1.0.0: 2024-01-01\n\n- chore: initial\n"
        )
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, content)
        result = validate_changelog_schema(cl)
        assert result["valid"] is True


# ── validate_pdoc_html ────────────────────────────────────────────────────────


class TestValidatePdocHtml:
    """Tests for validate_pdoc_html()."""

    def test_valid_pdoc_html_passes(self, tmp_path: Path) -> None:
        """Valid pdoc HTML with all required sections passes."""
        _write(tmp_path / "module.html", _VALID_PDOC_HTML)
        result = validate_pdoc_html(tmp_path)
        assert result["valid"] is True, result["errors"]
        assert result["errors"] == []

    def test_nonexistent_directory_returns_error(self, tmp_path: Path) -> None:
        """Missing pdoc directory returns valid=False."""
        result = validate_pdoc_html(tmp_path / "nonexistent")
        assert result["valid"] is False
        assert any("not found" in e for e in result["errors"])

    def test_empty_directory_returns_error(self, tmp_path: Path) -> None:
        """Directory with no HTML files returns valid=False."""
        result = validate_pdoc_html(tmp_path)
        assert result["valid"] is False
        assert any("HTML" in e or "html" in e for e in result["errors"])

    def test_missing_html_tag_returns_error(self, tmp_path: Path) -> None:
        """HTML file without <html> tag returns error."""
        content = "<body><p>No html wrapper</p></body>"
        _write(tmp_path / "module.html", content)
        result = validate_pdoc_html(tmp_path)
        assert result["valid"] is False
        assert any("html" in e.lower() for e in result["errors"])

    def test_missing_module_docstring_returns_error(self, tmp_path: Path) -> None:
        """HTML without module docstring section returns error."""
        content = (
            "<html><head></head><body>"
            "<dl>"
            '<dt id="m.f1">def f1()</dt>'
            '<dt id="m.f2">def f2()</dt>'
            '<dt id="m.f3">def f3()</dt>'
            '<dt id="m.C">class MyClass</dt>'
            "</dl></body></html>"
        )
        _write(tmp_path / "module.html", content)
        result = validate_pdoc_html(tmp_path)
        assert result["valid"] is False
        assert any("docstring" in e.lower() for e in result["errors"])

    def test_too_few_functions_returns_error(self, tmp_path: Path) -> None:
        """HTML with fewer than 3 functions returns error."""
        content = (
            "<html><body>"
            '<section id="section-intro"><p>Module doc.</p></section>'
            "<dl>"
            '<dt id="m.f1">def f1()</dt>'
            '<dt id="m.f2">def f2()</dt>'
            '<dt id="m.C">class MyClass</dt>'
            "</dl>"
            "</body></html>"
        )
        _write(tmp_path / "module.html", content)
        result = validate_pdoc_html(tmp_path)
        assert result["valid"] is False
        assert any(">= 3" in e or "expected" in e.lower() for e in result["errors"])

    def test_missing_class_list_returns_error(self, tmp_path: Path) -> None:
        """HTML without any class definition returns error."""
        content = (
            "<html><body>"
            '<section id="section-intro"><p>Module doc.</p></section>'
            "<dl>"
            '<dt id="m.f1">def f1()</dt>'
            '<dt id="m.f2">def f2()</dt>'
            '<dt id="m.f3">def f3()</dt>'
            "</dl>"
            "</body></html>"
        )
        _write(tmp_path / "module.html", content)
        result = validate_pdoc_html(tmp_path)
        assert result["valid"] is False
        assert any("class" in e.lower() for e in result["errors"])

    def test_combined_html_from_multiple_files(self, tmp_path: Path) -> None:
        """Functions spread across multiple HTML files are counted together."""
        html_a = (
            "<html><body>"
            '<section id="section-intro"><p>Module A.</p></section>'
            "<dl>"
            '<dt id="a.f1">def f1()</dt>'
            '<dt id="a.f2">def f2()</dt>'
            "</dl></body></html>"
        )
        html_b = '<html><body><dl><dt id="b.f3">def f3()</dt><dt id="b.C">class MyClass</dt></dl></body></html>'
        _write(tmp_path / "module_a.html", html_a)
        _write(tmp_path / "module_b.html", html_b)
        result = validate_pdoc_html(tmp_path)
        assert result["valid"] is True, result["errors"]


# ── validate_all_outputs ──────────────────────────────────────────────────────


class TestValidateAllOutputs:
    """Tests for validate_all_outputs()."""

    def test_returns_true_when_both_valid(self, tmp_path: Path) -> None:
        """Returns True when changelog and pdoc both pass."""
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, _VALID_CHANGELOG)
        pdoc = tmp_path / "docs"
        _write(pdoc / "module.html", _VALID_PDOC_HTML)
        scratch = tmp_path / ".spiral"

        result = validate_all_outputs(cl, pdoc, scratch_dir=scratch)
        assert result is True

    def test_returns_false_when_changelog_invalid(self, tmp_path: Path) -> None:
        """Returns False when changelog schema is invalid."""
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "No header here\n\n## Unreleased\n")
        scratch = tmp_path / ".spiral"

        result = validate_all_outputs(cl, scratch_dir=scratch)
        assert result is False

    def test_writes_validation_log_on_failure(self, tmp_path: Path) -> None:
        """Logs failures to .spiral/_phase_g_validation.json."""
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, "bad content")
        scratch = tmp_path / ".spiral"

        validate_all_outputs(cl, scratch_dir=scratch)

        log_path = scratch / "_phase_g_validation.json"
        assert log_path.exists(), "Validation log must be written on failure"
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert data["overall_valid"] is False
        assert "changelog" in data
        assert "pdoc" in data
        assert "timestamp" in data

    def test_writes_validation_log_on_success(self, tmp_path: Path) -> None:
        """Writes validation log even when all checks pass."""
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, _VALID_CHANGELOG)
        scratch = tmp_path / ".spiral"

        validate_all_outputs(cl, scratch_dir=scratch)

        log_path = scratch / "_phase_g_validation.json"
        assert log_path.exists()
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert data["overall_valid"] is True

    def test_skips_pdoc_when_dir_missing(self, tmp_path: Path) -> None:
        """If pdoc_dir doesn't exist, pdoc validation is skipped (not an error)."""
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, _VALID_CHANGELOG)
        scratch = tmp_path / ".spiral"

        result = validate_all_outputs(cl, tmp_path / "nonexistent_pdoc", scratch_dir=scratch)
        assert result is True

        log_path = scratch / "_phase_g_validation.json"
        data = json.loads(log_path.read_text(encoding="utf-8"))
        assert data["pdoc"].get("skipped") is True

    def test_skips_pdoc_when_not_provided(self, tmp_path: Path) -> None:
        """If pdoc_dir is None, pdoc validation is skipped."""
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, _VALID_CHANGELOG)
        scratch = tmp_path / ".spiral"

        result = validate_all_outputs(cl, None, scratch_dir=scratch)
        assert result is True

    def test_log_contains_all_required_keys(self, tmp_path: Path) -> None:
        """Validation log JSON has required schema keys."""
        cl = tmp_path / "CHANGELOG.md"
        _write(cl, _VALID_CHANGELOG)
        scratch = tmp_path / ".spiral"

        validate_all_outputs(cl, scratch_dir=scratch)

        data = json.loads((scratch / "_phase_g_validation.json").read_text(encoding="utf-8"))
        for key in ("timestamp", "overall_valid", "changelog", "pdoc"):
            assert key in data, f"Missing key: {key}"
        for section in ("changelog", "pdoc"):
            assert "valid" in data[section]
            assert "errors" in data[section]

    def test_rollback_signal_false_on_changelog_mismatch(self, tmp_path: Path) -> None:
        """False return signals caller should rollback on schema mismatch."""
        cl = tmp_path / "CHANGELOG.md"
        # CHANGELOG with H1 but all H2s missing semver → schema mismatch
        _write(cl, "# Changelog\n\n## Unreleased\n\n- some change\n")
        scratch = tmp_path / ".spiral"

        ok = validate_all_outputs(cl, scratch_dir=scratch)
        assert ok is False, "Must return False to trigger caller rollback"

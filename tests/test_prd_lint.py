"""Tests for lib/prd_lint.py — acceptance-criteria lint check (US-209)."""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from prd_lint import prd_lint, main  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prd(*stories: dict) -> dict:
    return {"projectName": "Test", "userStories": list(stories)}


def _story(id_: str, title: str = "Untitled", ac=("Works",), skipped=False) -> dict:
    s: dict = {"id": id_, "title": title, "passes": False}
    if ac is not None:
        s["acceptanceCriteria"] = list(ac)
    if skipped:
        s["_skipped"] = True
    return s


def _write_prd(tmp_path, prd: dict) -> str:
    p = os.path.join(str(tmp_path), "prd.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(prd, fh, indent=2)
    return p


# ---------------------------------------------------------------------------
# Unit tests: prd_lint()
# ---------------------------------------------------------------------------

class TestPrdLintFunction:
    def test_no_violations_for_full_criteria(self):
        prd = _prd(_story("US-001", ac=["Must work", "Must pass tests"]))
        assert prd_lint(prd) == []

    def test_missing_key_is_violation(self):
        story = {"id": "US-002", "title": "No AC", "passes": False}
        # acceptanceCriteria key is absent entirely
        prd = _prd(story)
        violations = prd_lint(prd)
        assert len(violations) == 1
        assert violations[0]["id"] == "US-002"

    def test_null_ac_is_violation(self):
        story = {"id": "US-003", "title": "Null AC", "acceptanceCriteria": None, "passes": False}
        violations = prd_lint(_prd(story))
        assert len(violations) == 1
        assert violations[0]["id"] == "US-003"

    def test_empty_list_ac_is_violation(self):
        story = {"id": "US-004", "title": "Empty AC", "acceptanceCriteria": [], "passes": False}
        violations = prd_lint(_prd(story))
        assert len(violations) == 1
        assert violations[0]["id"] == "US-004"

    def test_skipped_stories_excluded(self):
        story = {"id": "US-005", "title": "Skipped", "acceptanceCriteria": [], "_skipped": True, "passes": False}
        violations = prd_lint(_prd(story))
        assert violations == []

    def test_multiple_violations(self):
        prd = _prd(
            _story("US-010", ac=["OK"]),           # fine
            _story("US-011", ac=[]),                # violation
            {"id": "US-012", "title": "No key", "passes": False},  # violation
        )
        violations = prd_lint(prd)
        ids = [v["id"] for v in violations]
        assert "US-011" in ids
        assert "US-012" in ids
        assert "US-010" not in ids

    def test_empty_prd_has_no_violations(self):
        assert prd_lint({"userStories": []}) == []

    def test_violation_includes_title(self):
        prd = _prd(_story("US-020", title="My Feature", ac=[]))
        violations = prd_lint(prd)
        assert violations[0]["title"] == "My Feature"


# ---------------------------------------------------------------------------
# Integration tests: main() CLI
# ---------------------------------------------------------------------------

class TestPrdLintMain:
    def test_clean_prd_exits_zero(self, tmp_path):
        path = _write_prd(tmp_path, _prd(_story("US-100", ac=["Criterion"])))
        rc = main.__wrapped__(path) if hasattr(main, "__wrapped__") else _run_main(path)
        assert rc == 0

    def test_violation_exits_zero_without_strict(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SPIRAL_STRICT_AC", raising=False)
        path = _write_prd(tmp_path, _prd(_story("US-101", ac=[])))
        rc = _run_main(path)
        assert rc == 0

    def test_violation_exits_one_with_strict(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPIRAL_STRICT_AC", "true")
        path = _write_prd(tmp_path, _prd(_story("US-102", ac=[])))
        rc = _run_main(path)
        assert rc == 1

    def test_strict_clean_prd_still_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SPIRAL_STRICT_AC", "true")
        path = _write_prd(tmp_path, _prd(_story("US-103", ac=["Done"])))
        rc = _run_main(path)
        assert rc == 0

    def test_events_written_to_jsonl(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SPIRAL_STRICT_AC", raising=False)
        path = _write_prd(tmp_path, _prd(_story("US-110", ac=[])))
        events_file = os.path.join(str(tmp_path), "spiral_events.jsonl")
        rc = _run_main(path, events_file=events_file)
        assert rc == 0
        assert os.path.exists(events_file)
        with open(events_file, encoding="utf-8") as fh:
            lines = [json.loads(line) for line in fh if line.strip()]
        assert len(lines) == 1
        assert lines[0]["event_type"] == "prd_lint_warning"
        assert lines[0]["story_id"] == "US-110"

    def test_warn_message_format(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("SPIRAL_STRICT_AC", raising=False)
        path = _write_prd(tmp_path, _prd(_story("US-120", title="My Story", ac=[])))
        _run_main(path)
        captured = capsys.readouterr()
        assert "WARN [prd-lint] Story US-120 'My Story' has no acceptanceCriteria" in captured.out

    def test_skipped_stories_not_in_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.delenv("SPIRAL_STRICT_AC", raising=False)
        story = {"id": "US-130", "title": "Skipped", "acceptanceCriteria": [], "_skipped": True, "passes": False}
        path = _write_prd(tmp_path, _prd(story))
        _run_main(path)
        captured = capsys.readouterr()
        assert "US-130" not in captured.out


# ---------------------------------------------------------------------------
# Helper to invoke main() via sys.argv patching
# ---------------------------------------------------------------------------

def _run_main(prd_path: str, events_file: str = "") -> int:
    import prd_lint as _mod
    argv_backup = sys.argv[:]
    sys.argv = ["prd_lint.py", prd_path]
    if events_file:
        sys.argv += ["--events-file", events_file]
    try:
        return _mod.main()
    finally:
        sys.argv = argv_backup

"""Tests for lib/check_prd_encoding.py — UTF-8 and control character validation."""
import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from check_prd_encoding import check_encoding, sanitize_prd  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(tmp_path, data) -> str:
    p = os.path.join(tmp_path, "prd.json")
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return p


def _write_bytes(tmp_path, raw: bytes) -> str:
    p = os.path.join(tmp_path, "prd.json")
    with open(p, "wb") as fh:
        fh.write(raw)
    return p


def _minimal_prd() -> dict:
    return {
        "projectName": "Test",
        "userStories": [
            {
                "id": "US-001",
                "title": "Clean story",
                "description": "No issues here",
                "acceptanceCriteria": ["Works correctly"],
                "passes": False,
            }
        ],
    }


# ---------------------------------------------------------------------------
# check_encoding: valid files
# ---------------------------------------------------------------------------

class TestCheckEncodingValid:
    def test_clean_file_returns_empty_list(self, tmp_path):
        path = _write_json(str(tmp_path), _minimal_prd())
        issues = check_encoding(path)
        assert issues == []

    def test_unicode_text_allowed(self, tmp_path):
        prd = _minimal_prd()
        prd["userStories"][0]["description"] = "Café — résumé — naïve"
        path = _write_json(str(tmp_path), prd)
        issues = check_encoding(path)
        assert issues == []

    def test_tab_and_newline_allowed(self, tmp_path):
        prd = _minimal_prd()
        prd["userStories"][0]["description"] = "line1\nline2\ttabbed"
        path = _write_json(str(tmp_path), prd)
        issues = check_encoding(path)
        assert issues == []


# ---------------------------------------------------------------------------
# check_encoding: invalid files
# ---------------------------------------------------------------------------

class TestCheckEncodingInvalid:
    def test_null_byte_in_description_detected(self, tmp_path):
        prd = _minimal_prd()
        prd["userStories"][0]["description"] = "bad\x00value"
        path = _write_json(str(tmp_path), prd)
        issues = check_encoding(path)
        assert len(issues) >= 1
        assert issues[0]["char"] == "0x00"
        assert "description" in issues[0]["path"]

    def test_control_char_0x01_detected(self, tmp_path):
        prd = _minimal_prd()
        prd["userStories"][0]["title"] = "title\x01bad"
        path = _write_json(str(tmp_path), prd)
        issues = check_encoding(path)
        assert any(i["char"] == "0x01" for i in issues)

    def test_control_char_in_acceptance_criteria_detected(self, tmp_path):
        prd = _minimal_prd()
        prd["userStories"][0]["acceptanceCriteria"] = ["ok", "bad\x0bitem"]
        path = _write_json(str(tmp_path), prd)
        issues = check_encoding(path)
        assert len(issues) >= 1
        assert issues[0]["char"] == "0x0b"

    def test_multiple_offenders_all_reported(self, tmp_path):
        prd = _minimal_prd()
        prd["userStories"][0]["description"] = "\x01two\x02bad"
        path = _write_json(str(tmp_path), prd)
        issues = check_encoding(path)
        assert len(issues) == 2

    def test_issue_dict_has_required_keys(self, tmp_path):
        prd = _minimal_prd()
        prd["userStories"][0]["description"] = "x\x0cx"
        path = _write_json(str(tmp_path), prd)
        issues = check_encoding(path)
        assert len(issues) == 1
        assert {"path", "char", "pos"} == set(issues[0].keys())

    def test_non_utf8_bytes_raise_value_error(self, tmp_path):
        raw = b'{"projectName": "test", "userStories": []}\xff\xfe'
        path = _write_bytes(str(tmp_path), raw)
        with pytest.raises(ValueError, match="not valid UTF-8"):
            check_encoding(path)

    def test_missing_file_raises_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            check_encoding(os.path.join(str(tmp_path), "nonexistent.json"))

    def test_invalid_json_raises_value_error(self, tmp_path):
        path = _write_bytes(str(tmp_path), b"{ not json }")
        with pytest.raises(ValueError, match="JSON parse error"):
            check_encoding(path)


# ---------------------------------------------------------------------------
# sanitize_prd
# ---------------------------------------------------------------------------

class TestSanitizePrd:
    def test_strips_null_byte_from_description(self, tmp_path):
        prd = _minimal_prd()
        prd["userStories"][0]["description"] = "clean\x00corrupted"
        path = _write_json(str(tmp_path), prd)
        changed = sanitize_prd(path)
        assert changed is True
        with open(path, encoding="utf-8") as fh:
            cleaned = json.load(fh)
        assert cleaned["userStories"][0]["description"] == "cleancorrupted"

    def test_no_change_on_clean_file(self, tmp_path):
        path = _write_json(str(tmp_path), _minimal_prd())
        changed = sanitize_prd(path)
        assert changed is False

    def test_sanitize_preserves_valid_unicode(self, tmp_path):
        prd = _minimal_prd()
        prd["userStories"][0]["description"] = "Café\x00café"
        path = _write_json(str(tmp_path), prd)
        sanitize_prd(path)
        with open(path, encoding="utf-8") as fh:
            cleaned = json.load(fh)
        assert cleaned["userStories"][0]["description"] == "Cafécafé"

    def test_sanitize_rewrites_valid_json(self, tmp_path):
        prd = _minimal_prd()
        prd["userStories"][0]["description"] = "\x01bad"
        path = _write_json(str(tmp_path), prd)
        sanitize_prd(path)
        with open(path, encoding="utf-8") as fh:
            result = json.load(fh)
        # File is valid JSON and control char is gone
        assert "\x01" not in result["userStories"][0]["description"]

    def test_sanitize_file_passes_check_encoding_after(self, tmp_path):
        prd = _minimal_prd()
        prd["userStories"][0]["description"] = "\x00\x01\x0e"
        path = _write_json(str(tmp_path), prd)
        sanitize_prd(path)
        issues = check_encoding(path)
        assert issues == []

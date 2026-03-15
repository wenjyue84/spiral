"""Tests for lib/spiral_io.py — atomic write, JSONL, safe read, UTF-8 config."""
import json
import os
import sys
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from spiral_io import (
    append_jsonl,
    atomic_write_json,
    configure_utf8_stdout,
    safe_read_json,
    safe_read_jsonl,
)


# ── atomic_write_json ─────────────────────────────────────────────────────────


def test_atomic_write_json_creates_file(tmp_path):
    path = str(tmp_path / "out.json")
    data = {"hello": "world", "num": 42}
    atomic_write_json(path, data)

    with open(path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data


def test_atomic_write_json_overwrites(tmp_path):
    path = str(tmp_path / "out.json")
    atomic_write_json(path, {"v": 1})
    atomic_write_json(path, {"v": 2})

    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"v": 2}


def test_atomic_write_json_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "a" / "b" / "out.json")
    atomic_write_json(path, {"nested": True})

    with open(path, encoding="utf-8") as f:
        assert json.load(f)["nested"] is True


def test_atomic_write_json_backup(tmp_path):
    path = str(tmp_path / "out.json")
    atomic_write_json(path, {"v": 1})
    atomic_write_json(path, {"v": 2}, backup=True)

    with open(path + ".bak", encoding="utf-8") as f:
        assert json.load(f) == {"v": 1}
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"v": 2}


def test_atomic_write_json_no_partial_on_error(tmp_path):
    path = str(tmp_path / "out.json")
    atomic_write_json(path, {"original": True})

    class Unserializable:
        pass

    with pytest.raises(TypeError):
        atomic_write_json(path, {"bad": Unserializable()})

    # Original file should be intact
    with open(path, encoding="utf-8") as f:
        assert json.load(f) == {"original": True}

    # No leftover .tmp files
    tmp_files = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    assert tmp_files == []


def test_atomic_write_json_trailing_newline(tmp_path):
    path = str(tmp_path / "out.json")
    atomic_write_json(path, {"a": 1})
    with open(path, encoding="utf-8") as f:
        content = f.read()
    assert content.endswith("\n")


def test_atomic_write_json_unicode(tmp_path):
    path = str(tmp_path / "out.json")
    atomic_write_json(path, {"emoji": "\U0001f600", "cjk": "\u4e16\u754c"})
    with open(path, encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded["emoji"] == "\U0001f600"
    assert loaded["cjk"] == "\u4e16\u754c"


# ── append_jsonl ──────────────────────────────────────────────────────────────


def test_append_jsonl_creates_and_appends(tmp_path):
    path = str(tmp_path / "log.jsonl")
    append_jsonl(path, {"a": 1})
    append_jsonl(path, {"b": 2})

    with open(path, encoding="utf-8") as f:
        lines = f.read().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0]) == {"a": 1}
    assert json.loads(lines[1]) == {"b": 2}


def test_append_jsonl_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "sub" / "dir" / "log.jsonl")
    append_jsonl(path, {"x": 1})
    assert os.path.isfile(path)


# ── safe_read_json ────────────────────────────────────────────────────────────


def test_safe_read_json_valid(tmp_path):
    path = str(tmp_path / "data.json")
    with open(path, "w") as f:
        json.dump({"k": "v"}, f)
    assert safe_read_json(path) == {"k": "v"}


def test_safe_read_json_missing():
    assert safe_read_json("/nonexistent/path.json") is None
    assert safe_read_json("/nonexistent/path.json", default=[]) == []


def test_safe_read_json_corrupt(tmp_path):
    path = str(tmp_path / "bad.json")
    with open(path, "w") as f:
        f.write("{broken")
    assert safe_read_json(path) is None
    assert safe_read_json(path, default={}) == {}


# ── safe_read_jsonl ───────────────────────────────────────────────────────────


def test_safe_read_jsonl_valid(tmp_path):
    path = str(tmp_path / "data.jsonl")
    with open(path, "w") as f:
        f.write('{"a": 1}\n{"b": 2}\n')
    records = safe_read_jsonl(path)
    assert records == [{"a": 1}, {"b": 2}]


def test_safe_read_jsonl_missing():
    assert safe_read_jsonl("/nonexistent/path.jsonl") == []


def test_safe_read_jsonl_skips_bad_lines(tmp_path, capsys):
    path = str(tmp_path / "mixed.jsonl")
    with open(path, "w") as f:
        f.write('{"ok": true}\nBAD LINE\n{"also": "ok"}\n')
    records = safe_read_jsonl(path)
    assert len(records) == 2
    assert records[0] == {"ok": True}
    assert records[1] == {"also": "ok"}
    # Warning was printed to stderr
    captured = capsys.readouterr()
    assert "corrupt JSONL line 2" in captured.err


def test_safe_read_jsonl_blank_lines(tmp_path):
    path = str(tmp_path / "blanks.jsonl")
    with open(path, "w") as f:
        f.write('{"a": 1}\n\n\n{"b": 2}\n')
    records = safe_read_jsonl(path)
    assert len(records) == 2


# ── configure_utf8_stdout ─────────────────────────────────────────────────────


def test_configure_utf8_stdout_runs_without_error():
    # Should not raise even if streams don't support reconfigure
    configure_utf8_stdout()

"""tests/test_skills_cli.py — Tests for `spiral skills` subcommand (US-1265)."""

from __future__ import annotations

import io
import tarfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lib.skills_cli import (
    install_skill,
    list_skills,
    parse_plugin_toml,
    validate_plugin_schema,
)

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_plugin_toml(content: str, tmp_path: Path) -> Path:
    p = tmp_path / "plugin.toml"
    p.write_text(content, encoding="utf-8")
    return p


def _make_fake_tarball(plugin_toml_content: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = plugin_toml_content.encode()
        info = tarfile.TarInfo(name="my-plugin/plugin.toml")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf.read()


# ── parse_plugin_toml ────────────────────────────────────────────────────────


def test_parse_plugin_toml_reads_plugin_section(tmp_path: Path) -> None:
    toml_path = _make_plugin_toml(
        '[plugin]\nname = "my-plugin"\nversion = "1.0.0"\nhooks = ["post-story"]\n',
        tmp_path,
    )
    plugin = parse_plugin_toml(toml_path)
    assert plugin["name"] == "my-plugin"
    assert plugin["version"] == "1.0.0"
    assert plugin["hooks"] == ["post-story"]


def test_parse_plugin_toml_returns_empty_for_missing_section(tmp_path: Path) -> None:
    toml_path = _make_plugin_toml("[other]\nkey = 1\n", tmp_path)
    plugin = parse_plugin_toml(toml_path)
    assert plugin == {}


# ── validate_plugin_schema ───────────────────────────────────────────────────


def test_validate_schema_valid() -> None:
    plugin = {"name": "p", "version": "1.0.0", "hooks": ["post-story"]}
    assert validate_plugin_schema(plugin) == []


def test_validate_schema_missing_name() -> None:
    plugin = {"version": "1.0.0", "hooks": ["post-story"]}
    errs = validate_plugin_schema(plugin)
    assert any("name" in e for e in errs)


def test_validate_schema_missing_hooks() -> None:
    plugin = {"name": "p", "version": "1.0.0"}
    errs = validate_plugin_schema(plugin)
    assert any("hooks" in e for e in errs)


# ── list_skills ──────────────────────────────────────────────────────────────


def test_list_skills_round_trips_notify_slack() -> None:
    """spiral skills list round-trips metadata from notify-slack."""
    plugins_dir = Path("plugins")
    if not (plugins_dir / "notify-slack" / "plugin.toml").exists():
        pytest.skip("notify-slack plugin not present")

    import io as _io
    import sys

    captured = _io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    ret = list_skills(plugins_dir)
    sys.stdout = old_stdout

    output = captured.getvalue()
    assert ret == 0
    assert "notify-slack" in output


def test_list_skills_round_trips_notify_whatsapp() -> None:
    """spiral skills list round-trips metadata from notify-whatsapp."""
    plugins_dir = Path("plugins")
    if not (plugins_dir / "notify-whatsapp" / "plugin.toml").exists():
        pytest.skip("notify-whatsapp plugin not present")

    import io as _io
    import sys

    captured = _io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    ret = list_skills(plugins_dir)
    sys.stdout = old_stdout

    output = captured.getvalue()
    assert ret == 0
    assert "notify-whatsapp" in output


def test_list_skills_missing_dir(tmp_path: Path) -> None:
    ret = list_skills(tmp_path / "no-such-dir")
    assert ret == 1


def test_list_skills_empty_dir(tmp_path: Path) -> None:
    import io as _io
    import sys

    captured = _io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = captured
    ret = list_skills(tmp_path)
    sys.stdout = old_stdout

    assert ret == 0
    assert "No plugins" in captured.getvalue()


# ── install_skill ─────────────────────────────────────────────────────────────


def test_install_skill_rejects_non_tarball(tmp_path: Path) -> None:
    url = "http://example.com/bad.tar.gz"
    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"this is not a tarball"
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_resp

        ret = install_skill(url, tmp_path)
    assert ret == 1


def test_install_skill_rejects_missing_plugin_toml(tmp_path: Path) -> None:
    # Tarball with no plugin.toml
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        data = b"#!/bin/bash\necho hello\n"
        info = tarfile.TarInfo(name="my-plugin/run.sh")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    tarball_bytes = buf.getvalue()

    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.read.return_value = tarball_bytes
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_resp

        ret = install_skill("http://example.com/plugin.tar.gz", tmp_path)
    assert ret == 1


def test_install_skill_rejects_schema_invalid_plugin(tmp_path: Path) -> None:
    # plugin.toml missing required 'hooks'
    bad_toml = '[plugin]\nname = "bad-plugin"\nversion = "0.1.0"\n'
    tarball_bytes = _make_fake_tarball(bad_toml)

    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.read.return_value = tarball_bytes
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_resp

        ret = install_skill("http://example.com/plugin.tar.gz", tmp_path)
    assert ret == 1


def test_install_skill_succeeds_valid_plugin(tmp_path: Path) -> None:
    good_toml = (
        '[plugin]\nname = "test-plugin"\nversion = "1.0.0"\n'
        'hooks = ["post-story"]\ndescription = "test"\ntags = ["test"]\n'
    )
    tarball_bytes = _make_fake_tarball(good_toml)

    with patch("urllib.request.urlopen") as mock_open:
        mock_resp = MagicMock()
        mock_resp.read.return_value = tarball_bytes
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_open.return_value = mock_resp

        ret = install_skill("http://example.com/plugin.tar.gz", tmp_path)
    assert ret == 0
    assert (tmp_path / "test-plugin" / "plugin.toml").exists()

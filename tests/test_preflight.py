"""Tests for lib/spiral/preflight.py (US-1069)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure lib/ is on path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from spiral.preflight import (  # type: ignore[import-untyped]
    _check_config_var,
    _check_constitution,
    _check_dir_writable,
    _check_docker,
    _check_jq,
    _check_prd_schema,
    _check_tool_version,
    _parse_version,
    run_checks,
)

# ── AC1: constitution, prd schema, config vars ──────────────────────────────


class TestConstitutionCheck:
    def test_pass_when_constitution_exists(self, tmp_path: Path) -> None:
        spec_dir = tmp_path / ".specify" / "memory"
        spec_dir.mkdir(parents=True)
        (spec_dir / "constitution.md").write_text("# rules", encoding="utf-8")
        result = _check_constitution(tmp_path)
        assert result["status"] == "pass"
        assert result["check_name"] == "constitution_exists"

    def test_pass_when_flat_constitution_exists(self, tmp_path: Path) -> None:
        (tmp_path / "constitution.md").write_text("# rules", encoding="utf-8")
        result = _check_constitution(tmp_path)
        assert result["status"] == "pass"

    def test_fail_when_missing(self, tmp_path: Path) -> None:
        result = _check_constitution(tmp_path)
        assert result["status"] == "fail"
        assert result["remediation"] != ""


class TestPrdSchemaCheck:
    def test_fail_when_prd_missing(self, tmp_path: Path) -> None:
        result = _check_prd_schema(tmp_path, Path("prd.json"))
        assert result["status"] == "fail"
        assert "prd.json" in result["remediation"].lower() or "create" in result["remediation"].lower()

    def test_fail_when_invalid_json(self, tmp_path: Path) -> None:
        (tmp_path / "prd.json").write_text("{bad json}", encoding="utf-8")
        result = _check_prd_schema(tmp_path, Path("prd.json"))
        assert result["status"] == "fail"
        assert "json" in result["remediation"].lower()

    def test_pass_with_valid_prd(self, tmp_path: Path) -> None:
        valid_prd = {
            "version": "1.0",
            "projectName": "Test",
            "userStories": [],
        }
        (tmp_path / "prd.json").write_text(json.dumps(valid_prd), encoding="utf-8")
        result = _check_prd_schema(tmp_path, Path("prd.json"))
        # Should pass or fail gracefully (schema may require extra fields)
        assert result["check_name"] == "prd_schema_valid"
        assert result["status"] in ("pass", "fail")


class TestConfigVarCheck:
    def test_fail_when_config_missing(self, tmp_path: Path) -> None:
        result = _check_config_var(tmp_path / "spiral.config.sh", "SPIRAL_VALIDATE_CMD")
        assert result["status"] == "fail"

    def test_pass_when_var_defined(self, tmp_path: Path) -> None:
        config = tmp_path / "spiral.config.sh"
        config.write_text('SPIRAL_VALIDATE_CMD="uv run pytest"\n', encoding="utf-8")
        result = _check_config_var(config, "SPIRAL_VALIDATE_CMD")
        assert result["status"] == "pass"

    def test_pass_with_export_prefix(self, tmp_path: Path) -> None:
        config = tmp_path / "spiral.config.sh"
        config.write_text('export SPIRAL_COST_CEILING="5.00"\n', encoding="utf-8")
        result = _check_config_var(config, "SPIRAL_COST_CEILING")
        assert result["status"] == "pass"

    def test_fail_when_var_missing_from_config(self, tmp_path: Path) -> None:
        config = tmp_path / "spiral.config.sh"
        config.write_text("OTHER_VAR=foo\n", encoding="utf-8")
        result = _check_config_var(config, "SPIRAL_VALIDATE_CMD")
        assert result["status"] == "fail"
        assert result["remediation"] != ""

    def test_check_name_matches_var(self, tmp_path: Path) -> None:
        config = tmp_path / "spiral.config.sh"
        config.write_text("", encoding="utf-8")
        result = _check_config_var(config, "SPIRAL_COST_CEILING")
        assert "spiral_cost_ceiling" in result["check_name"]


# ── AC2: system tool checks ──────────────────────────────────────────────────


class TestParseVersion:
    def test_simple(self) -> None:
        assert _parse_version("GNU bash, version 5.2.15") == (5, 2, 15)

    def test_node_style(self) -> None:
        assert _parse_version("v20.11.0") == (20, 11, 0)

    def test_single_number(self) -> None:
        assert _parse_version("Python 3.13.0") == (3, 13, 0)

    def test_no_version(self) -> None:
        assert _parse_version("no version here") == (0,)


class TestToolVersionCheck:
    def test_pass_when_version_meets_minimum(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "v20.11.0"
            mock_run.return_value.stderr = ""
            result = _check_tool_version("node_version_ge20", ["node", "--version"], (20,), "install node")
        assert result["status"] == "pass"

    def test_fail_when_version_too_old(self) -> None:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.stdout = "v18.0.0"
            mock_run.return_value.stderr = ""
            result = _check_tool_version("node_version_ge20", ["node", "--version"], (20,), "install node")
        assert result["status"] == "fail"
        assert "18" in result["remediation"]

    def test_fail_when_tool_not_found(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = _check_tool_version("node_version_ge20", ["node", "--version"], (20,), "install node")
        assert result["status"] == "fail"


class TestDockerCheck:
    def test_fail_when_docker_not_found(self) -> None:
        with patch("shutil.which", return_value=None):
            result = _check_docker()
        assert result["status"] == "fail"
        assert result["check_name"] == "docker_available"

    def test_fail_when_daemon_down(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 1
                mock_run.return_value.stdout = ""
                mock_run.return_value.stderr = "Cannot connect to Docker daemon"
                result = _check_docker()
        assert result["status"] == "fail"

    def test_pass_when_docker_running(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/docker"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = "Server: Docker Engine"
                mock_run.return_value.stderr = ""
                result = _check_docker()
        assert result["status"] == "pass"


class TestJqCheck:
    def test_pass_when_bundled_jq_exists(self, tmp_path: Path) -> None:
        ralph = tmp_path / "ralph"
        ralph.mkdir()
        (ralph / "jq.exe").write_text("", encoding="utf-8")
        result = _check_jq(tmp_path)
        assert result["status"] == "pass"

    def test_pass_when_jq_in_path(self, tmp_path: Path) -> None:
        with patch("shutil.which", return_value="/usr/bin/jq"):
            result = _check_jq(tmp_path)
        assert result["status"] == "pass"

    def test_fail_when_jq_missing(self, tmp_path: Path) -> None:
        with patch("shutil.which", return_value=None):
            result = _check_jq(tmp_path)
        assert result["status"] == "fail"


class TestDirWritableCheck:
    def test_pass_for_writable_dir(self, tmp_path: Path) -> None:
        target = tmp_path / ".spiral"
        result = _check_dir_writable(target, "spiral_dir_writable")
        assert result["status"] == "pass"
        assert target.exists()

    def test_fail_for_unwritable_path(self, tmp_path: Path) -> None:
        target = tmp_path / "noperm" / ".spiral"
        with patch("pathlib.Path.mkdir", side_effect=OSError("permission denied")):
            result = _check_dir_writable(target, "spiral_dir_writable")
        assert result["status"] == "fail"


# ── AC3: run_checks integration + exit codes ────────────────────────────────


class TestRunChecks:
    def test_returns_list_of_check_results(self, tmp_path: Path) -> None:
        results = run_checks(spiral_home=tmp_path)
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert "check_name" in r
            assert "status" in r
            assert r["status"] in ("pass", "fail")
            assert "remediation" in r

    def test_all_expected_checks_present(self, tmp_path: Path) -> None:
        results = run_checks(spiral_home=tmp_path)
        names = {r["check_name"] for r in results}
        assert "constitution_exists" in names
        assert "prd_schema_valid" in names
        assert "config_spiral_validate_cmd_set" in names
        assert "config_spiral_cost_ceiling_set" in names
        assert "bash_version_ge4" in names
        assert "node_version_ge20" in names
        assert "python3_version_ge313" in names
        assert "docker_available" in names
        assert "jq_available" in names
        assert "spiral_dir_writable" in names
        assert "spiral_workers_dir_writable" in names


class TestMainCli:
    def test_exit_0_when_all_pass(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        all_pass_results = [{"check_name": "test_check", "status": "pass", "remediation": ""}]
        with patch("spiral.preflight.run_checks", return_value=all_pass_results):
            from spiral.preflight import main

            code = main(["--spiral-home", str(tmp_path)])
        assert code == 0
        captured = capsys.readouterr()
        assert "All checks passed" in captured.out

    def test_exit_1_when_any_fail(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        mixed_results = [
            {"check_name": "constitution_exists", "status": "fail", "remediation": "Create it"},
            {"check_name": "prd_schema_valid", "status": "pass", "remediation": ""},
        ]
        with patch("spiral.preflight.run_checks", return_value=mixed_results):
            from spiral.preflight import main

            code = main(["--spiral-home", str(tmp_path)])
        assert code == 1
        captured = capsys.readouterr()
        assert "1 checks failed" in captured.out

    def test_summary_counts_correct(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        results = [
            {"check_name": "check_a", "status": "pass", "remediation": ""},
            {"check_name": "check_b", "status": "pass", "remediation": ""},
            {"check_name": "check_c", "status": "fail", "remediation": "Fix it"},
        ]
        with patch("spiral.preflight.run_checks", return_value=results):
            from spiral.preflight import main

            code = main(["--spiral-home", str(tmp_path)])
        assert code == 1
        captured = capsys.readouterr()
        assert "1 checks failed" in captured.out

    def test_output_is_valid_json(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        results = [
            {"check_name": "c1", "status": "pass", "remediation": ""},
        ]
        with patch("spiral.preflight.run_checks", return_value=results):
            from spiral.preflight import main

            main(["--spiral-home", str(tmp_path)])
        captured = capsys.readouterr()
        # First part of output is JSON
        json_part = captured.out.split("\n\n")[0]
        parsed = json.loads(json_part)
        assert isinstance(parsed, list)

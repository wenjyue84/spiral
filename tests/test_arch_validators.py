"""Tests for lib/arch_validators.py (US-1084).

Covers:
- MaxFileSize: basic violation, no violation, env var parsing, edge cases
- NoCircularImports: cycle detection, no cycle, non-Python files
- LayerAccess: layer violation, no violation, unconfigured
- load_validators: factory from comma-separated string
- AC3 integration: 5MB file with MAX_FILE_SIZE=1MB -> MaxFileSize violation
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from arch_validators import (
    CodeDiff,
    DiffFile,
    LayerAccess,
    MaxFileSize,
    NoCircularImports,
    load_validators,
)

MB = 1 << 20  # 1 MiB


def _make_diff(*files: DiffFile) -> CodeDiff:
    return CodeDiff(files=list(files), repo_root="/tmp/test-repo")


# ── MaxFileSize ───────────────────────────────────────────────────────────────


class TestMaxFileSize:
    def test_no_violation_under_limit(self) -> None:
        v = MaxFileSize(max_bytes=5 * MB)
        diff = _make_diff(DiffFile("lib/small.py", size_bytes=100))
        assert v.validate(diff) == []

    def test_violation_over_limit(self) -> None:
        v = MaxFileSize(max_bytes=MB)
        diff = _make_diff(DiffFile("lib/huge.bin", size_bytes=5 * MB))
        violations = v.validate(diff)
        assert len(violations) == 1
        assert violations[0].violation_type == "MaxFileSize"
        assert violations[0].file_path == "lib/huge.bin"

    def test_exactly_at_limit_is_allowed(self) -> None:
        v = MaxFileSize(max_bytes=MB)
        diff = _make_diff(DiffFile("data.bin", size_bytes=MB))
        assert v.validate(diff) == []

    def test_no_limit_when_max_bytes_none(self) -> None:
        v = MaxFileSize(max_bytes=None)
        diff = _make_diff(DiffFile("giant.bin", size_bytes=500 * MB))
        assert v.validate(diff) == []

    def test_env_var_mb(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_FILE_SIZE", "1MB")
        v = MaxFileSize()
        diff = _make_diff(DiffFile("big.bin", size_bytes=5 * MB))
        violations = v.validate(diff)
        assert len(violations) == 1
        assert violations[0].violation_type == "MaxFileSize"

    def test_env_var_not_set_no_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("MAX_FILE_SIZE", raising=False)
        v = MaxFileSize()
        diff = _make_diff(DiffFile("big.bin", size_bytes=500 * MB))
        assert v.validate(diff) == []

    def test_multiple_violations(self) -> None:
        v = MaxFileSize(max_bytes=MB)
        diff = _make_diff(
            DiffFile("a.bin", size_bytes=2 * MB),
            DiffFile("b.bin", size_bytes=3 * MB),
            DiffFile("c.py", size_bytes=100),
        )
        violations = v.validate(diff)
        assert len(violations) == 2

    def test_violation_message_contains_size(self) -> None:
        v = MaxFileSize(max_bytes=MB)
        diff = _make_diff(DiffFile("big.bin", size_bytes=5 * MB))
        msg = v.validate(diff)[0].message
        assert "5,242,880" in msg or "5242880" in msg


# ── AC3: Integration test ─────────────────────────────────────────────────────


class TestAC3MaxFileSizeIntegration:
    """AC3: story adds 5MB file when MAX_FILE_SIZE=1MB -> arch_validation_failed=true."""

    def test_5mb_file_direct_validator(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAX_FILE_SIZE", "1MB")
        v = MaxFileSize()
        diff = _make_diff(DiffFile("assets/5mb-export.bin", size_bytes=5 * MB))
        violations = v.validate(diff)
        assert len(violations) == 1
        assert violations[0].violation_type == "MaxFileSize"
        assert violations[0].validator == "MaxFileSize"

    def test_runner_arch_validation_failed_flag(self, tmp_path: Path) -> None:
        """AC3 via runner subprocess: outputs arch_validation_failed=true, returncode=1."""
        repo = tmp_path / "repo"
        repo.mkdir()
        # First commit: small placeholder so HEAD~1 exists
        (repo / "readme.txt").write_text("init\n")

        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(repo),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(repo),
            capture_output=True,
        )
        subprocess.run(
            ["git", "add", "."], cwd=str(repo), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(repo),
            capture_output=True,
            check=True,
        )
        # Second commit: add the 5MB file — this is what HEAD~1 diff shows
        (repo / "big.bin").write_bytes(b"x" * (5 * MB))
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add big file"], cwd=str(repo), capture_output=True, check=True
        )

        runner_path = Path(__file__).parent.parent / "lib" / "run_arch_validators.py"
        env = {
            **os.environ,
            "SPIRAL_ARCH_VALIDATORS": "MaxFileSize",
            "MAX_FILE_SIZE": "1MB",
        }
        result = subprocess.run(
            [sys.executable, str(runner_path)],
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=env,
        )
        assert result.stdout.strip(), f"No output from runner. stderr: {result.stderr}"
        output = json.loads(result.stdout.strip())
        assert output["arch_validation_failed"] is True
        assert any(
            v["violation_type"] == "MaxFileSize" for v in output["violations"]
        ), f"Expected MaxFileSize violation in {output['violations']}"
        assert result.returncode == 1

    def test_runner_no_violation_passes(self, tmp_path: Path) -> None:
        """Runner returns arch_validation_failed=false when files are small."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "small.py").write_text("x = 1\n")

        subprocess.run(["git", "init"], cwd=str(repo), capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "t@t.com"],
            cwd=str(repo),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "T"], cwd=str(repo), capture_output=True
        )
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=str(repo), capture_output=True
        )
        (repo / "another.py").write_text("y = 2\n")
        subprocess.run(["git", "add", "."], cwd=str(repo), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "second"], cwd=str(repo), capture_output=True
        )

        runner_path = Path(__file__).parent.parent / "lib" / "run_arch_validators.py"
        env = {
            **os.environ,
            "SPIRAL_ARCH_VALIDATORS": "MaxFileSize",
            "MAX_FILE_SIZE": "1MB",
        }
        result = subprocess.run(
            [sys.executable, str(runner_path)],
            capture_output=True,
            text=True,
            cwd=str(repo),
            env=env,
        )
        output = json.loads(result.stdout.strip())
        assert output["arch_validation_failed"] is False
        assert result.returncode == 0


# ── NoCircularImports ─────────────────────────────────────────────────────────


class TestNoCircularImports:
    def test_no_cycle_linear(self) -> None:
        v = NoCircularImports()
        diff = _make_diff(
            DiffFile("lib/a.py", size_bytes=10, content="import lib.b\n"),
            DiffFile("lib/b.py", size_bytes=10, content="import os\n"),
        )
        assert v.validate(diff) == []

    def test_simple_two_node_cycle(self) -> None:
        v = NoCircularImports()
        # Use absolute dotted imports matching the module names (lib.a, lib.b)
        diff = _make_diff(
            DiffFile("lib/a.py", size_bytes=10, content="import lib.b\n"),
            DiffFile("lib/b.py", size_bytes=10, content="import lib.a\n"),
        )
        violations = v.validate(diff)
        assert len(violations) >= 1
        assert all(viol.violation_type == "NoCircularImports" for viol in violations)

    def test_single_file_no_violation(self) -> None:
        v = NoCircularImports()
        diff = _make_diff(DiffFile("lib/a.py", size_bytes=10, content="import os\n"))
        assert v.validate(diff) == []

    def test_no_python_files(self) -> None:
        v = NoCircularImports()
        diff = _make_diff(DiffFile("image.png", size_bytes=1000))
        assert v.validate(diff) == []

    def test_no_cycle_among_three(self) -> None:
        v = NoCircularImports()
        diff = _make_diff(
            DiffFile("a.py", size_bytes=10, content="import b\n"),
            DiffFile("b.py", size_bytes=10, content="import c\n"),
            DiffFile("c.py", size_bytes=10, content="import os\n"),
        )
        assert v.validate(diff) == []


# ── LayerAccess ───────────────────────────────────────────────────────────────


class TestLayerAccess:
    def test_no_violation_higher_imports_lower(self) -> None:
        # api (rank 0) importing service (rank 1) is allowed
        v = LayerAccess(layers=["api", "service", "model"])
        diff = _make_diff(
            DiffFile(
                "api/handler.py",
                size_bytes=100,
                content="from service import user_svc\n",
            )
        )
        assert v.validate(diff) == []

    def test_violation_lower_imports_higher(self) -> None:
        # model (rank 2) importing api (rank 0) is forbidden
        v = LayerAccess(layers=["api", "service", "model"])
        diff = _make_diff(
            DiffFile(
                "model/user.py",
                size_bytes=100,
                content="from api import handler\n",
            )
        )
        violations = v.validate(diff)
        assert len(violations) == 1
        assert violations[0].violation_type == "LayerAccess"

    def test_no_layers_configured(self) -> None:
        v = LayerAccess(layers=[])
        diff = _make_diff(DiffFile("any/file.py", size_bytes=100, content="import os\n"))
        assert v.validate(diff) == []

    def test_file_not_in_any_layer_skipped(self) -> None:
        v = LayerAccess(layers=["api", "service"])
        diff = _make_diff(
            DiffFile("lib/utils.py", size_bytes=100, content="from api import x\n")
        )
        # 'lib' is not a known layer — no violations raised
        assert v.validate(diff) == []


# ── load_validators ───────────────────────────────────────────────────────────


class TestLoadValidators:
    def test_load_max_file_size(self) -> None:
        validators = load_validators("MaxFileSize")
        assert len(validators) == 1
        assert isinstance(validators[0], MaxFileSize)

    def test_load_multiple(self) -> None:
        validators = load_validators("MaxFileSize,NoCircularImports,LayerAccess")
        assert len(validators) == 3

    def test_empty_string(self) -> None:
        assert load_validators("") == []

    def test_unknown_validator_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown validator"):
            load_validators("NonExistent")

    def test_whitespace_trimmed(self) -> None:
        validators = load_validators(" MaxFileSize , NoCircularImports ")
        assert len(validators) == 2

    def test_base_class_is_abstract(self) -> None:
        from arch_validators import ArchValidator

        # Cannot instantiate abstract class directly
        with pytest.raises(TypeError):
            ArchValidator()  # type: ignore[abstract]

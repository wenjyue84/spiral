#!/usr/bin/env python3
"""
test_export_progress.py — Tests for lib/export_progress.py

Tests: test_export_json, test_export_zip
"""

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.export_progress import export_json, export_zip


def _make_project(tmp: Path) -> None:
    """Populate a minimal project directory for testing."""
    prd = {
        "schemaVersion": "1.0",
        "userStories": [
            {"id": "US-001", "title": "Story A", "passes": True},
            {"id": "US-002", "title": "Story B", "passes": False},
        ],
    }
    (tmp / "prd.json").write_text(json.dumps(prd), encoding="utf-8")

    tsv_rows = (
        "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus\tduration_sec\tmodel\tretry_num\tcost_usd\n"
        "2026-04-01T10:00:00Z\t1\t1\tUS-001\tStory A\tkeep\t120\thaiku\t0\t0.005\n"
        "2026-04-01T11:00:00Z\t1\t1\tUS-002\tStory B\trevert\t60\tsonnet\t0\t0.002\n"
    )
    (tmp / "results.tsv").write_text(tsv_rows, encoding="utf-8")
    (tmp / "learning.md").write_text("# Learning\n\nSome notes.", encoding="utf-8")
    (tmp / "retry-counts.json").write_text(json.dumps({"US-002": 1}), encoding="utf-8")

    spiral_dir = tmp / ".spiral"
    spiral_dir.mkdir(exist_ok=True)
    (spiral_dir / "loop_quality.jsonl").write_text(
        json.dumps({"iteration": 1, "pass_rate": 0.5}) + "\n", encoding="utf-8"
    )


def test_export_json() -> None:
    """export_json produces valid JSON with correct schema and checksum."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        _make_project(project)
        out = project / "out.json"

        result = export_json(project, out, iteration=1)

        assert result == out
        assert out.exists()

        data = json.loads(out.read_text(encoding="utf-8"))

        # Schema check
        assert "prd" in data
        assert "results" in data
        assert "learning" in data
        assert "loopQuality" in data
        assert "metadata" in data

        meta = data["metadata"]
        assert "iteration" in meta
        assert "timestamp" in meta
        assert "passCount" in meta
        assert "failCount" in meta
        assert "totalCost" in meta
        assert "checksum" in meta

        # Content check
        assert meta["iteration"] == 1
        assert meta["passCount"] == 1
        assert meta["failCount"] == 1
        assert len(meta["checksum"]) == 64  # sha256 hex

        assert isinstance(data["results"], list)
        assert len(data["results"]) == 2
        assert data["learning"] == "# Learning\n\nSome notes."
        assert len(data["loopQuality"]) == 1

        # Filename timestamp check
        assert "T" in meta["timestamp"] and "Z" in meta["timestamp"]


def test_export_json_timestamped_filename() -> None:
    """export_json default filename is timestamped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        _make_project(project)

        # Call main() without --output so it uses default name
        import importlib

        import lib.export_progress as ep

        importlib.reload(ep)  # ensure clean state

        timestamp_before = ep.datetime.now(ep.timezone.utc).strftime("%Y-%m-%dT%H")
        out = ep.export_json(project, project / f"spiral-export-{timestamp_before[:10]}.json")
        assert out.exists()
        assert "spiral-export" in out.name or out.suffix == ".json"


def test_export_zip() -> None:
    """export_zip produces a ZIP with expected files and README."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        _make_project(project)
        out = project / "export.zip"

        result = export_zip(project, out, iteration=2)

        assert result == out
        assert out.exists()

        with zipfile.ZipFile(out, "r") as zf:
            names = zf.namelist()

        assert "prd.json" in names
        assert "results.tsv" in names
        assert "learning.md" in names
        assert "retry-counts.json" in names
        assert "README.md" in names

        with zipfile.ZipFile(out, "r") as zf:
            readme = zf.read("README.md").decode("utf-8")

        assert "sha256" in readme.lower() or "checksum" in readme.lower() or "SHA256" in readme
        assert "iteration" in readme.lower() or "Iteration" in readme


def test_export_json_missing_optional_files() -> None:
    """export_json handles missing learning.md and loop_quality.jsonl gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        prd = {"schemaVersion": "1.0", "userStories": []}
        (project / "prd.json").write_text(json.dumps(prd), encoding="utf-8")
        (project / "results.tsv").write_text("timestamp\tstory_id\tstatus\n", encoding="utf-8")
        # No learning.md, no .spiral/loop_quality.jsonl

        out = project / "out.json"
        export_json(project, out)

        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["learning"] == ""
        assert data["loopQuality"] == []
        assert data["metadata"]["passCount"] == 0
        assert data["metadata"]["failCount"] == 0

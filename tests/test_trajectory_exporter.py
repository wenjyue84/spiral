"""tests/test_trajectory_exporter.py — Tests for lib/trajectory_exporter.py"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path

import pytest

from lib.trajectory_exporter import (
    REQUIRED_FIELDS,
    TrajectoryExporter,
    validate_record,
)

TSV_HEADER = (
    "timestamp\tspiral_iter\tralph_iter\tstory_id\tstory_title\tstatus"
    "\tduration_sec\tmodel\tretry_num\tcommit_sha\trun_id\tcache_hit"
    "\tcache_read_tokens\tcache_creation_tokens\treview_tokens"
    "\twall_seconds\tuser_cpu_s\tsys_cpu_s\tpeak_rss_kb\tbatch_id\n"
)

TSV_ROW_KEEP = (
    "2026-04-27T10:00:00Z\t1\t1\tUS-1000\tTest story A\tkeep"
    "\t300\tsonnet\t0\tabc123\trun1\tfalse"
    "\t5000\t2000\t0\t0\t0\t0\t0\t\n"
)

TSV_ROW_REJECT = (
    "2026-04-27T11:00:00Z\t1\t2\tUS-1001\tTest story B\treject\t200\thaiku\t1\t\trun1\tfalse\t0\t0\t0\t0\t0\t0\t0\t\n"
)


@pytest.fixture()
def results_tsv(tmp_path: Path) -> Path:
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER + TSV_ROW_KEEP + TSV_ROW_REJECT, encoding="utf-8")
    return tsv


def test_to_jsonl_returns_records(results_tsv: Path, tmp_path: Path) -> None:
    exporter = TrajectoryExporter(results_tsv, project_root=tmp_path)
    records = exporter.to_jsonl()
    assert len(records) == 2
    assert records[0]["story_id"] == "US-1000"
    assert records[1]["story_id"] == "US-1001"


def test_to_jsonl_filter(results_tsv: Path, tmp_path: Path) -> None:
    exporter = TrajectoryExporter(results_tsv, project_root=tmp_path)
    records = exporter.to_jsonl(filter_dict={"model": "sonnet"})
    assert len(records) == 1
    assert records[0]["story_id"] == "US-1000"


def test_record_fields_present(results_tsv: Path, tmp_path: Path) -> None:
    exporter = TrajectoryExporter(results_tsv, project_root=tmp_path)
    for record in exporter.to_jsonl():
        for field in REQUIRED_FIELDS:
            assert field in record, f"Missing field: {field}"


def test_record_success_true_for_keep(results_tsv: Path, tmp_path: Path) -> None:
    exporter = TrajectoryExporter(results_tsv, project_root=tmp_path)
    records = exporter.to_jsonl()
    assert records[0]["success"] is True
    assert records[0]["error_type"] is None


def test_record_success_false_for_reject(results_tsv: Path, tmp_path: Path) -> None:
    exporter = TrajectoryExporter(results_tsv, project_root=tmp_path)
    records = exporter.to_jsonl()
    assert records[1]["success"] is False
    assert records[1]["error_type"] == "reject"


def test_tokens_summed_from_cache_columns(results_tsv: Path, tmp_path: Path) -> None:
    exporter = TrajectoryExporter(results_tsv, project_root=tmp_path)
    records = exporter.to_jsonl()
    assert records[0]["tokens_used"] == 7000  # 5000 + 2000


def test_retry_count_from_retry_num(results_tsv: Path, tmp_path: Path) -> None:
    exporter = TrajectoryExporter(results_tsv, project_root=tmp_path)
    records = exporter.to_jsonl()
    assert records[0]["retry_count"] == 0
    assert records[1]["retry_count"] == 1


def test_decomposition_strategy(results_tsv: Path, tmp_path: Path) -> None:
    exporter = TrajectoryExporter(results_tsv, project_root=tmp_path)
    records = exporter.to_jsonl()
    assert records[0]["decomposition_strategy"] == "sequential"
    assert records[1]["decomposition_strategy"] == "retry"


def test_export_creates_gz_file(results_tsv: Path, tmp_path: Path) -> None:
    exporter = TrajectoryExporter(results_tsv, project_root=tmp_path)
    out = exporter.export()
    assert out.exists()
    assert out.suffix == ".gz"
    assert "export-" in out.name


def test_export_gz_is_valid_jsonl(results_tsv: Path, tmp_path: Path) -> None:
    exporter = TrajectoryExporter(results_tsv, project_root=tmp_path)
    out = exporter.export()
    with gzip.open(out, "rt", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 2
    for line in lines:
        obj = json.loads(line)
        assert isinstance(obj, dict)


def test_export_with_filter(results_tsv: Path, tmp_path: Path) -> None:
    exporter = TrajectoryExporter(results_tsv, project_root=tmp_path)
    out = exporter.export(filter_dict={"model": "haiku"})
    with gzip.open(out, "rt", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["model_tier"] == "haiku"


def test_empty_tsv_produces_empty_export(tmp_path: Path) -> None:
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER, encoding="utf-8")
    exporter = TrajectoryExporter(tsv, project_root=tmp_path)
    out = exporter.export()
    with gzip.open(out, "rt", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]
    assert lines == []


def test_missing_tsv_produces_empty_export(tmp_path: Path) -> None:
    tsv = tmp_path / "nonexistent.tsv"
    exporter = TrajectoryExporter(tsv, project_root=tmp_path)
    records = exporter.to_jsonl()
    assert records == []


def test_validate_record_pass() -> None:
    record = {
        "story_id": "US-1",
        "prompt": "p",
        "decomposition_strategy": "sequential",
        "response": "r",
        "tokens_used": 100,
        "success": True,
        "error_type": None,
        "model_tier": "sonnet",
        "retry_count": 0,
    }
    assert validate_record(record) == []


def test_validate_record_missing_field() -> None:
    record = {"story_id": "US-1"}
    errors = validate_record(record)
    assert len(errors) > 0
    assert any("prompt" in e for e in errors)


def test_trajectory_jsonl_schema_validation(tmp_path: Path) -> None:
    """AC4: All records in exported JSONL pass schema validation (100% field presence).

    Also writes to .spiral/trajectory/ so the Phase V zcat check can verify the file.
    """
    tsv = tmp_path / "results.tsv"
    tsv.write_text(TSV_HEADER + TSV_ROW_KEEP + TSV_ROW_REJECT, encoding="utf-8")

    # Export to real .spiral/trajectory/ so Phase V zcat command works
    project_root = Path(os.getcwd())
    spiral_traj_dir = project_root / ".spiral" / "trajectory"
    spiral_traj_dir.mkdir(parents=True, exist_ok=True)

    exporter = TrajectoryExporter(tsv, project_root=project_root)
    out = exporter.export()
    assert out.exists(), f"Export file not found: {out}"

    # Validate every record has all required fields
    with gzip.open(out, "rt", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    assert len(lines) > 0, "Export produced no records"
    for line in lines:
        record = json.loads(line)
        errors = validate_record(record)
        assert errors == [], f"Record {record.get('story_id')} failed schema: {errors}"
        # Validate types
        assert isinstance(record["tokens_used"], int)
        assert isinstance(record["success"], bool)
        assert isinstance(record["retry_count"], int)

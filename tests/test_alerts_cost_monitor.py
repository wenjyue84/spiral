#!/usr/bin/env python3
"""test_alerts_cost_monitor.py — Tests for cost monitoring and threshold detection."""

import os
from pathlib import Path
from typing import Generator

import pytest

from lib.alerts.cost_monitor import check_cost_thresholds, get_ceiling, read_current_cost


@pytest.fixture
def tmp_spiral_dir(tmp_path: Path) -> Generator[Path, None, None]:
    """Create temporary .spiral directory with mock results.tsv."""
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir()
    yield spiral_dir


@pytest.fixture
def monkeypatch_spiral_path(tmp_spiral_dir: Path, monkeypatch) -> None:
    """Monkeypatch pathlib.Path to use temporary spiral directory."""
    original_cwd = os.getcwd()
    os.chdir(tmp_spiral_dir.parent)
    yield
    os.chdir(original_cwd)


def test_get_ceiling_from_env(monkeypatch) -> None:
    """Test reading cost ceiling from environment."""
    monkeypatch.setenv("SPIRAL_COST_CEILING", "100.0")
    assert get_ceiling() == 100.0


def test_get_ceiling_default_zero_when_unset(monkeypatch) -> None:
    """Test default ceiling is 0 (no limit) when unset."""
    monkeypatch.delenv("SPIRAL_COST_CEILING", raising=False)
    assert get_ceiling() == 0.0


def test_get_ceiling_invalid_value_returns_zero(monkeypatch) -> None:
    """Test invalid ceiling value returns 0."""
    monkeypatch.setenv("SPIRAL_COST_CEILING", "invalid")
    assert get_ceiling() == 0.0


def test_read_current_cost_empty_results(tmp_spiral_dir: Path, monkeypatch) -> None:
    """Test reading cost from non-existent results.tsv returns 0."""
    monkeypatch.chdir(tmp_spiral_dir.parent)
    assert read_current_cost() == 0.0


def test_read_current_cost_from_results_tsv(tmp_spiral_dir: Path, monkeypatch) -> None:
    """Test reading cumulative cost from results.tsv."""
    monkeypatch.chdir(tmp_spiral_dir.parent)

    # Create mock results.tsv
    results_file = tmp_spiral_dir / "results.tsv"
    results_file.write_text(
        "story_id\testimated_cost_usd\tstatus\nUS-1\t5.0\tpassed\nUS-2\t3.5\tpassed\nUS-3\t2.1\tpassed\n"
    )

    total = read_current_cost()
    assert total == pytest.approx(10.6, rel=0.01)


def test_read_current_cost_with_fallback_column(tmp_spiral_dir: Path, monkeypatch) -> None:
    """Test reading cost using fallback 'cost' column if 'estimated_cost_usd' missing."""
    monkeypatch.chdir(tmp_spiral_dir.parent)

    results_file = tmp_spiral_dir / "results.tsv"
    results_file.write_text("story_id\tcost\tstatus\nUS-1\t7.5\tpassed\nUS-2\t2.5\tpassed\n")

    total = read_current_cost()
    assert total == pytest.approx(10.0, rel=0.01)


def test_read_current_cost_skips_invalid_rows(tmp_spiral_dir: Path, monkeypatch) -> None:
    """Test that rows with invalid costs are skipped."""
    monkeypatch.chdir(tmp_spiral_dir.parent)

    results_file = tmp_spiral_dir / "results.tsv"
    results_file.write_text(
        "story_id\testimated_cost_usd\tstatus\nUS-1\t5.0\tpassed\nUS-2\tinvalid\tpassed\nUS-3\t3.0\tpassed\n"
    )

    total = read_current_cost()
    assert total == pytest.approx(8.0, rel=0.01)


def test_check_cost_no_ceiling_no_alert(monkeypatch) -> None:
    """Test no alert when ceiling is 0 (disabled)."""
    monkeypatch.setenv("SPIRAL_COST_CEILING", "0")
    should_alert, severity = check_cost_thresholds()
    assert should_alert is False
    assert severity == ""


def test_check_cost_warning_at_80_percent(tmp_spiral_dir: Path, monkeypatch) -> None:
    """Test warning alert at 80% cost usage."""
    monkeypatch.chdir(tmp_spiral_dir.parent)
    monkeypatch.setenv("SPIRAL_COST_CEILING", "100.0")

    # Create results with $80 spent
    results_file = tmp_spiral_dir / "results.tsv"
    results_file.write_text("story_id\testimated_cost_usd\tstatus\nUS-1\t80.0\tpassed\n")

    should_alert, severity = check_cost_thresholds()
    assert should_alert is True
    assert severity == "warning"


def test_check_cost_critical_at_95_percent(tmp_spiral_dir: Path, monkeypatch) -> None:
    """Test critical alert at 95% cost usage."""
    monkeypatch.chdir(tmp_spiral_dir.parent)
    monkeypatch.setenv("SPIRAL_COST_CEILING", "100.0")

    # Create results with $95 spent
    results_file = tmp_spiral_dir / "results.tsv"
    results_file.write_text("story_id\testimated_cost_usd\tstatus\nUS-1\t95.0\tpassed\n")

    should_alert, severity = check_cost_thresholds()
    assert should_alert is True
    assert severity == "critical"


def test_check_cost_no_alert_below_80(tmp_spiral_dir: Path, monkeypatch) -> None:
    """Test no alert when usage is below 80%."""
    monkeypatch.chdir(tmp_spiral_dir.parent)
    monkeypatch.setenv("SPIRAL_COST_CEILING", "100.0")

    # Create results with $50 spent (50%)
    results_file = tmp_spiral_dir / "results.tsv"
    results_file.write_text("story_id\testimated_cost_usd\tstatus\nUS-1\t50.0\tpassed\n")

    should_alert, severity = check_cost_thresholds()
    assert should_alert is False
    assert severity == ""


def test_check_cost_critical_takes_precedence(tmp_spiral_dir: Path, monkeypatch) -> None:
    """Test critical is returned over warning when usage >= 95%."""
    monkeypatch.chdir(tmp_spiral_dir.parent)
    monkeypatch.setenv("SPIRAL_COST_CEILING", "100.0")

    # Create results with $96 spent (96% > 95%)
    results_file = tmp_spiral_dir / "results.tsv"
    results_file.write_text("story_id\testimated_cost_usd\tstatus\nUS-1\t96.0\tpassed\n")

    should_alert, severity = check_cost_thresholds()
    assert should_alert is True
    assert severity == "critical"

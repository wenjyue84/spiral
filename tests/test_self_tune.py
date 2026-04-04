"""Tests for lib/self_tune.py — Phase ST: Self-Tune engine."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from lib.results_tsv import ResultsRecord, write_results_tsv
from lib.self_tune import (
    SelfTuner,
    TuningAdjustment,
    main,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_record(
    spiral_iter: int = 1,
    status: str = "pass",
    model: str = "sonnet",
    duration_sec: str = "120",
    retry_num: str = "0",
    failure_root_cause: str = "",
    error_category: str = "",
    conflict_files: str = "",
    conflict_file_count: str = "0",
    peak_rss_kb: str = "0",
) -> ResultsRecord:
    return ResultsRecord(
        timestamp="2026-04-04T10:00:00Z",
        spiral_iter=str(spiral_iter),
        ralph_iter="1",
        story_id=f"US-{100 + spiral_iter}",
        story_title="Test story",
        status=status,
        duration_sec=duration_sec,
        model=model,
        retry_num=retry_num,
        commit_sha="abc123",
        run_id="run-1",
        failure_root_cause=failure_root_cause,
        error_category=error_category,
        conflict_files=conflict_files,
        conflict_file_count=conflict_file_count,
        peak_rss_kb=peak_rss_kb,
    )


def _write_tsv(records: list[ResultsRecord], path: Path) -> None:
    write_results_tsv(str(path), records)


def _make_tuner(
    records: list[ResultsRecord],
    current_iter: int = 3,
    history: list[dict] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> SelfTuner:
    """Create a SelfTuner with synthetic data."""
    tmp = Path(tempfile.mkdtemp())
    tsv_path = tmp / "results.tsv"
    history_path = tmp / "tuning_history.jsonl"

    _write_tsv(records, tsv_path)

    if history:
        with history_path.open("w") as f:
            for entry in history:
                f.write(json.dumps(entry) + "\n")

    if env_overrides:
        for k, v in env_overrides.items():
            os.environ[k] = v

    tuner = SelfTuner(
        results_tsv_path=str(tsv_path),
        tuning_history_path=str(history_path),
        current_iteration=current_iter,
    )
    tuner.load()
    return tuner


# ── Test: Metric loading ────────────────────────────────────────────────────


class TestMetricLoading:
    def test_empty_results(self) -> None:
        tuner = _make_tuner([], current_iter=1)
        m = tuner._metrics_for_iter(1)
        assert m.total_attempts == 0
        assert m.velocity == 0.0

    def test_basic_aggregation(self) -> None:
        records = [
            _make_record(spiral_iter=1, status="pass", duration_sec="100"),
            _make_record(spiral_iter=1, status="reject", duration_sec="200", failure_root_cause="timeout"),
            _make_record(spiral_iter=1, status="pass", duration_sec="150"),
        ]
        tuner = _make_tuner(records, current_iter=1)
        m = tuner._metrics_for_iter(1)
        assert m.total_attempts == 3
        assert m.passed == 2
        assert m.failed == 1
        assert m.timeout_count == 1
        assert m.velocity == 2.0
        assert m.avg_duration_sec == pytest.approx(150.0)

    def test_model_tracking(self) -> None:
        records = [
            _make_record(spiral_iter=1, model="haiku", status="reject"),
            _make_record(spiral_iter=1, model="haiku", status="pass"),
            _make_record(spiral_iter=1, model="sonnet", status="pass"),
            _make_record(spiral_iter=1, model="opus", status="pass"),
        ]
        tuner = _make_tuner(records, current_iter=1)
        m = tuner._metrics_for_iter(1)
        assert m.haiku_attempts == 2
        assert m.haiku_passes == 1
        assert m.sonnet_attempts == 1
        assert m.sonnet_passes == 1
        assert m.opus_attempts == 1
        assert m.opus_passes == 1


# ── Test: Rule 1 — Timeout scaling ──────────────────────────────────────────


class TestTimeoutScaling:
    def test_increase_on_high_timeout_rate(self) -> None:
        records = []
        for i in [1, 2]:
            # 4 out of 10 stories timeout = 40% > 30%
            for _ in range(4):
                records.append(_make_record(spiral_iter=i, status="error", failure_root_cause="timeout"))
            for _ in range(6):
                records.append(_make_record(spiral_iter=i, status="pass"))

        tuner = _make_tuner(
            records,
            current_iter=2,
            env_overrides={
                "SPIRAL_IMPL_TIMEOUT": "2400",
            },
        )
        adjs = tuner._rule_timeout_scaling(tuner._recent_metrics(3))
        assert len(adjs) > 0
        impl_adj = next((a for a in adjs if a.setting == "SPIRAL_IMPL_TIMEOUT"), None)
        assert impl_adj is not None
        assert int(impl_adj.new_value) == 3000  # 2400 * 1.25

    def test_no_change_on_moderate_rate(self) -> None:
        records = []
        for i in [1, 2]:
            records.append(_make_record(spiral_iter=i, status="error", failure_root_cause="timeout"))
            for _ in range(9):
                records.append(_make_record(spiral_iter=i, status="pass"))

        tuner = _make_tuner(records, current_iter=2)
        adjs = tuner._rule_timeout_scaling(tuner._recent_metrics(3))
        assert len(adjs) == 0


# ── Test: Rule 2 — Diff limit scaling ───────────────────────────────────────


class TestDiffLimitScaling:
    def test_increase_on_oversized_diff(self) -> None:
        records = []
        for i in [1, 2]:
            # 3 out of 8 failures = 37.5% > 20%
            for _ in range(3):
                records.append(
                    _make_record(
                        spiral_iter=i,
                        status="reject",
                        failure_root_cause="oversized_diff",
                    )
                )
            for _ in range(5):
                records.append(_make_record(spiral_iter=i, status="reject", failure_root_cause="type_error"))

        tuner = _make_tuner(
            records,
            current_iter=2,
            env_overrides={
                "SPIRAL_MAX_DIFF_LINES": "800",
            },
        )
        adj = tuner._rule_diff_limit(tuner._recent_metrics(3))
        assert adj is not None
        assert adj.setting == "SPIRAL_MAX_DIFF_LINES"
        assert int(adj.new_value) == 1000

    def test_decrease_after_3_clean_iters(self) -> None:
        records = []
        for i in [1, 2, 3]:
            records.append(_make_record(spiral_iter=i, status="reject", failure_root_cause="type_error"))
            records.append(_make_record(spiral_iter=i, status="pass"))

        tuner = _make_tuner(
            records,
            current_iter=3,
            env_overrides={
                "SPIRAL_MAX_DIFF_LINES": "900",
            },
        )
        adj = tuner._rule_diff_limit(tuner._recent_metrics(3))
        assert adj is not None
        assert int(adj.new_value) == 800

    def test_floor_at_400(self) -> None:
        records = [_make_record(spiral_iter=i, status="pass") for i in [1, 2, 3]]
        tuner = _make_tuner(
            records,
            current_iter=3,
            env_overrides={
                "SPIRAL_MAX_DIFF_LINES": "400",
            },
        )
        adj = tuner._rule_diff_limit(tuner._recent_metrics(3))
        assert adj is None  # already at floor


# ── Test: Rule 3 — Model floor escalation ───────────────────────────────────


class TestModelFloor:
    def test_skip_haiku_on_low_success(self) -> None:
        records = []
        for i in [1, 2, 3]:
            records.append(_make_record(spiral_iter=i, model="haiku", status="reject"))
            records.append(_make_record(spiral_iter=i, model="haiku", status="reject"))
            records.append(_make_record(spiral_iter=i, model="sonnet", status="pass"))

        tuner = _make_tuner(
            records,
            current_iter=3,
            env_overrides={
                "SPIRAL_ESCALATION_RETRY_SONNET": "1",
            },
        )
        adjs = tuner._rule_model_floor(tuner._recent_metrics(3))
        sonnet_adj = next((a for a in adjs if a.setting == "SPIRAL_ESCALATION_RETRY_SONNET"), None)
        assert sonnet_adj is not None
        assert sonnet_adj.new_value == "0"

    def test_no_change_on_good_haiku_rate(self) -> None:
        records = []
        for i in [1, 2, 3]:
            records.append(_make_record(spiral_iter=i, model="haiku", status="pass"))
            records.append(_make_record(spiral_iter=i, model="haiku", status="pass"))

        tuner = _make_tuner(
            records,
            current_iter=3,
            env_overrides={
                "SPIRAL_ESCALATION_RETRY_SONNET": "1",
            },
        )
        adjs = tuner._rule_model_floor(tuner._recent_metrics(3))
        assert len(adjs) == 0


# ── Test: Rule 4 — Worker count ─────────────────────────────────────────────


class TestWorkerCount:
    def test_reduce_on_conflicts(self) -> None:
        records = []
        for i in [1, 2]:
            # 3 out of 10 have conflicts = 30% > 15%
            for _ in range(3):
                records.append(_make_record(spiral_iter=i, status="pass", conflict_file_count="2"))
            for _ in range(7):
                records.append(_make_record(spiral_iter=i, status="pass"))

        tuner = _make_tuner(
            records,
            current_iter=2,
            env_overrides={
                "SPIRAL_RALPH_WORKERS": "3",
            },
        )
        adj = tuner._rule_worker_count(tuner._recent_metrics(3))
        assert adj is not None
        assert int(adj.new_value) == 2

    def test_increase_when_stable(self) -> None:
        records = [_make_record(spiral_iter=i, status="pass") for i in [1, 2, 3]]
        tuner = _make_tuner(
            records,
            current_iter=3,
            env_overrides={
                "SPIRAL_RALPH_WORKERS": "1",
            },
        )
        adj = tuner._rule_worker_count(tuner._recent_metrics(3))
        assert adj is not None
        assert int(adj.new_value) == 2


# ── Test: Rule 5 — Batch size ───────────────────────────────────────────────


class TestBatchSize:
    def test_decrease_on_low_velocity(self) -> None:
        records = [
            _make_record(spiral_iter=1, status="reject"),
            _make_record(spiral_iter=2, status="reject"),
        ]
        tuner = _make_tuner(
            records,
            current_iter=2,
            env_overrides={
                "SPIRAL_STORY_BATCH_SIZE": "10",
            },
        )
        adj = tuner._rule_batch_size(tuner._recent_metrics(3))
        assert adj is not None
        assert int(adj.new_value) == 8

    def test_increase_on_high_velocity(self) -> None:
        records = [_make_record(spiral_iter=2, status="pass") for _ in range(5)]
        records.append(_make_record(spiral_iter=1, status="pass"))
        tuner = _make_tuner(
            records,
            current_iter=2,
            env_overrides={
                "SPIRAL_STORY_BATCH_SIZE": "10",
            },
        )
        adj = tuner._rule_batch_size(tuner._recent_metrics(3))
        assert adj is not None
        assert int(adj.new_value) == 12


# ── Test: Rule 6 — Decompose threshold ──────────────────────────────────────


class TestDecomposeThreshold:
    def test_lower_on_high_max_retry(self) -> None:
        records = []
        for i in [1, 2]:
            # 5 out of 10 at retry 3+ = 50% > 40%
            for _ in range(5):
                records.append(_make_record(spiral_iter=i, status="reject", retry_num="3"))
            for _ in range(5):
                records.append(_make_record(spiral_iter=i, status="pass", retry_num="0"))

        tuner = _make_tuner(
            records,
            current_iter=2,
            env_overrides={
                "SPIRAL_DECOMPOSE_THRESHOLD": "3",
            },
        )
        adj = tuner._rule_decompose_threshold(tuner._recent_metrics(3))
        assert adj is not None
        assert int(adj.new_value) == 2


# ── Test: Cooldown ──────────────────────────────────────────────────────────


class TestCooldown:
    def test_skips_recently_adjusted(self) -> None:
        records = []
        for i in [1, 2]:
            for _ in range(5):
                records.append(
                    _make_record(
                        spiral_iter=i,
                        status="reject",
                        failure_root_cause="oversized_diff",
                    )
                )

        history = [
            {
                "timestamp": "2026-04-04T10:00:00Z",
                "iteration": 1,
                "adjustments": [{"setting": "SPIRAL_MAX_DIFF_LINES", "old_value": "600", "new_value": "800"}],
            }
        ]

        tuner = _make_tuner(
            records,
            current_iter=2,
            history=history,
            env_overrides={
                "SPIRAL_MAX_DIFF_LINES": "800",
            },
        )
        adj = tuner._rule_diff_limit(tuner._recent_metrics(3))
        assert adj is None  # cooldown blocks it

    def test_allows_after_cooldown(self) -> None:
        records = []
        for i in [1, 2, 3, 4]:
            for _ in range(5):
                records.append(
                    _make_record(
                        spiral_iter=i,
                        status="reject",
                        failure_root_cause="oversized_diff",
                    )
                )

        history = [
            {
                "timestamp": "2026-04-04T10:00:00Z",
                "iteration": 1,
                "adjustments": [{"setting": "SPIRAL_MAX_DIFF_LINES", "old_value": "600", "new_value": "800"}],
            }
        ]

        tuner = _make_tuner(
            records,
            current_iter=4,
            history=history,
            env_overrides={
                "SPIRAL_MAX_DIFF_LINES": "800",
            },
        )
        adj = tuner._rule_diff_limit(tuner._recent_metrics(3))
        assert adj is not None  # cooldown expired


# ── Test: Persistence ───────────────────────────────────────────────────────


class TestPersistence:
    def test_persist_appends_to_file(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        history_path = tmp / "tuning_history.jsonl"

        tuner = SelfTuner(
            results_tsv_path="",
            tuning_history_path=str(history_path),
            current_iteration=5,
        )
        tuner.persist(
            [
                TuningAdjustment("SPIRAL_MAX_DIFF_LINES", "800", "1000", "diff_limit_scaling", "test reason"),
            ]
        )

        lines = history_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["iteration"] == 5
        assert len(entry["adjustments"]) == 1
        assert entry["adjustments"][0]["setting"] == "SPIRAL_MAX_DIFF_LINES"


# ── Test: CLI main ──────────────────────────────────────────────────────────


class TestCLI:
    def test_missing_results_returns_empty(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(
                [
                    str(tmp / "nonexistent.tsv"),
                    str(tmp / "tuning.jsonl"),
                    str(tmp),
                    "1",
                ]
            )
        assert rc == 0
        output = json.loads(buf.getvalue())
        assert output["adjustments"] == []
        assert output["exports"] == {}

    def test_full_pipeline(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        tsv_path = tmp / "results.tsv"

        # Generate data that triggers diff limit increase
        records = []
        for i in [1, 2]:
            for _ in range(4):
                records.append(
                    _make_record(
                        spiral_iter=i,
                        status="reject",
                        failure_root_cause="oversized_diff",
                    )
                )
            for _ in range(6):
                records.append(_make_record(spiral_iter=i, status="reject", failure_root_cause="type_error"))
        _write_tsv(records, tsv_path)

        os.environ["SPIRAL_MAX_DIFF_LINES"] = "800"

        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(
                [
                    str(tsv_path),
                    str(tmp / "tuning.jsonl"),
                    str(tmp),
                    "2",
                ]
            )
        assert rc == 0
        output = json.loads(buf.getvalue())
        assert "SPIRAL_MAX_DIFF_LINES" in output["exports"]
        assert output["exports"]["SPIRAL_MAX_DIFF_LINES"] == "1000"


# ── Test: Bounds enforcement ────────────────────────────────────────────────


class TestBounds:
    def test_diff_limit_capped_at_1500(self) -> None:
        records = []
        for i in [1, 2]:
            for _ in range(8):
                records.append(_make_record(spiral_iter=i, status="reject", failure_root_cause="oversized_diff"))

        tuner = _make_tuner(
            records,
            current_iter=2,
            env_overrides={
                "SPIRAL_MAX_DIFF_LINES": "1400",
            },
        )
        adj = tuner._rule_diff_limit(tuner._recent_metrics(3))
        assert adj is not None
        assert int(adj.new_value) <= 1500

    def test_workers_floor_at_1(self) -> None:
        records = []
        for i in [1, 2]:
            for _ in range(5):
                records.append(_make_record(spiral_iter=i, status="pass", conflict_file_count="3"))

        tuner = _make_tuner(
            records,
            current_iter=2,
            env_overrides={
                "SPIRAL_RALPH_WORKERS": "1",
            },
        )
        adj = tuner._rule_worker_count(tuner._recent_metrics(3))
        assert adj is None  # can't go below 1

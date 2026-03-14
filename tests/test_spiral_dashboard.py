"""Tests for spiral_dashboard.py — velocity chart (US-034)."""
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from spiral_dashboard import (  # noqa: E402
    compute_iteration_velocity,
    _render_velocity_svg,
    _render_activity_feed,
    load_progress,
    render_html,
    compute_overview,
    compute_velocity,
    compute_status_breakdown,
    compute_model_performance,
    compute_retry_analysis,
    compute_bottlenecks,
    compute_decomposition,
    generate_insights,
    detect_orphaned_worktrees,
    compute_stale_stories,
    compute_story_attempts,
    compute_token_forecast,
)


# ── compute_iteration_velocity ───────────────────────────────────────────────

class TestComputeIterationVelocity:
    def test_empty_results_returns_empty_dict(self):
        assert compute_iteration_velocity([]) == {}

    def test_counts_only_kept_stories(self):
        results = [
            {"spiral_iter": 1, "status": "keep"},
            {"spiral_iter": 1, "status": "skip"},
            {"spiral_iter": 2, "status": "keep"},
            {"spiral_iter": 2, "status": "keep"},
        ]
        vel = compute_iteration_velocity(results)
        assert vel == {1: 1, 2: 2}

    def test_ignores_non_keep_statuses(self):
        results = [
            {"spiral_iter": 1, "status": "fail"},
            {"spiral_iter": 1, "status": "retry"},
        ]
        assert compute_iteration_velocity(results) == {}

    def test_coerces_string_iter_to_int(self):
        results = [{"spiral_iter": "3", "status": "keep"}]
        vel = compute_iteration_velocity(results)
        assert vel == {3: 1}

    def test_missing_spiral_iter_goes_to_zero(self):
        results = [{"status": "keep"}]
        vel = compute_iteration_velocity(results)
        assert vel == {0: 1}

    def test_multiple_iterations(self):
        results = [
            {"spiral_iter": 1, "status": "keep"},
            {"spiral_iter": 1, "status": "keep"},
            {"spiral_iter": 1, "status": "keep"},
            {"spiral_iter": 2, "status": "keep"},
            {"spiral_iter": 3, "status": "keep"},
            {"spiral_iter": 3, "status": "keep"},
        ]
        vel = compute_iteration_velocity(results)
        assert vel == {1: 3, 2: 1, 3: 2}


# ── _render_velocity_svg ─────────────────────────────────────────────────────

class TestRenderVelocitySvg:
    def test_empty_dict_returns_no_data_message(self):
        html = _render_velocity_svg({})
        assert "no-data" in html
        assert "<svg" not in html

    def test_returns_svg_element_with_data(self):
        html = _render_velocity_svg({1: 3, 2: 5})
        assert "<svg" in html
        assert "</svg>" in html

    def test_contains_rect_elements_for_bars(self):
        html = _render_velocity_svg({1: 2, 2: 4})
        assert "<rect" in html

    def test_iteration_labels_present(self):
        html = _render_velocity_svg({1: 2, 3: 4})
        assert "i1" in html
        assert "i3" in html

    def test_count_labels_present_for_nonzero_bars(self):
        html = _render_velocity_svg({1: 7})
        assert ">7<" in html

    def test_zero_count_bar_no_count_label(self):
        # A bar with zero stories should still render but without a count label
        html = _render_velocity_svg({1: 0})
        # Should have rect (zero height) but no count text "0"
        assert "<rect" in html
        # The count label ">0<" should NOT be emitted (condition: count > 0)
        assert ">0<" not in html

    def test_single_iteration(self):
        html = _render_velocity_svg({5: 3})
        assert "<svg" in html
        assert "i5" in html

    def test_no_external_js(self):
        html = _render_velocity_svg({1: 1, 2: 2})
        assert "<script" not in html


# ── render_html velocity section ─────────────────────────────────────────────

def _make_minimal_render_args():
    """Return minimal arguments to call render_html without errors."""
    prd = {"userStories": [{"id": "US-001", "passes": True}]}
    results = [{"spiral_iter": 1, "status": "keep", "duration_sec": 60,
                "retry_num": 0, "ralph_iter": 1, "model": "sonnet"}]
    retries = {}
    overview = compute_overview(prd, results)
    velocity = compute_velocity(results)
    if not velocity:
        velocity = [{"iter": 0, "kept": 0, "total": 0, "duration_hours": 0.001, "velocity": 0}]
    status = compute_status_breakdown(prd, results)
    model_perf = compute_model_performance(results)
    retry_analysis = compute_retry_analysis(results)
    bottle = compute_bottlenecks(results, retries, prd)
    decomposition = compute_decomposition(prd)
    insights = generate_insights(overview, model_perf, retry_analysis, bottle)
    return overview, velocity, status, model_perf, retry_analysis, bottle, decomposition, insights


class TestRenderHtmlVelocitySection:
    def test_section_heading_present(self):
        args = _make_minimal_render_args()
        html = render_html(*args, iteration_velocity={1: 2, 2: 3})
        assert "Velocity by Iteration" in html

    def test_svg_present_when_data_provided(self):
        args = _make_minimal_render_args()
        html = render_html(*args, iteration_velocity={1: 2})
        assert "<svg" in html

    def test_empty_state_when_no_iteration_data(self):
        args = _make_minimal_render_args()
        html = render_html(*args, iteration_velocity={})
        assert "Velocity by Iteration" in html
        assert "no-data" in html

    def test_none_iteration_velocity_renders_empty_state(self):
        args = _make_minimal_render_args()
        html = render_html(*args, iteration_velocity=None)
        assert "Velocity by Iteration" in html
        assert "no-data" in html

    def test_omitted_iteration_velocity_renders_empty_state(self):
        """Calling render_html without iteration_velocity kwarg should still work."""
        args = _make_minimal_render_args()
        html = render_html(*args)
        assert "Velocity by Iteration" in html


# ── load_progress ────────────────────────────────────────────────────────────

class TestLoadProgress:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_progress(str(tmp_path / "nonexistent.txt")) == []

    def test_empty_file_returns_empty(self, tmp_path):
        p = tmp_path / "progress.txt"
        p.write_text("", encoding="utf-8")
        assert load_progress(str(p)) == []

    def test_no_iteration_headers_returns_empty(self, tmp_path):
        p = tmp_path / "progress.txt"
        p.write_text("## Codebase Patterns\n- some pattern\n", encoding="utf-8")
        assert load_progress(str(p)) == []

    def test_parses_iteration_sections(self, tmp_path):
        p = tmp_path / "progress.txt"
        p.write_text(
            "## Codebase Patterns\n- foo\n\n"
            "## Iteration 1 - Story: US-001\n\n### What\n- stuff\n\n"
            "## Iteration 2 - Story: US-002\n\n### What\n- more stuff\n",
            encoding="utf-8",
        )
        sections = load_progress(str(p))
        assert len(sections) == 2
        assert sections[0].startswith("## Iteration 1")
        assert sections[1].startswith("## Iteration 2")

    def test_respects_max_entries(self, tmp_path):
        p = tmp_path / "progress.txt"
        content = "\n".join(f"## Iteration {i} - Story: US-{i:03d}\nbody {i}\n" for i in range(1, 15))
        p.write_text(content, encoding="utf-8")
        sections = load_progress(str(p), max_entries=3)
        assert len(sections) == 3
        assert sections[0].startswith("## Iteration 12")


# ── _render_activity_feed ────────────────────────────────────────────────────

class TestRenderActivityFeed:
    def test_empty_sections_returns_empty_string(self):
        assert _render_activity_feed([]) == ""

    def test_renders_details_element(self):
        html = _render_activity_feed(["## Iteration 1 - Story: US-001\nsome body"])
        assert "<details>" in html
        assert "</details>" in html

    def test_summary_shows_count(self):
        html = _render_activity_feed([
            "## Iteration 1 - Story: US-001\nbody1",
            "## Iteration 2 - Story: US-002\nbody2",
        ])
        assert "last 2 entries" in html

    def test_title_and_body_rendered(self):
        html = _render_activity_feed(["## Iteration 5 - Story: US-042\nImportant details"])
        assert "Iteration 5 - Story: US-042" in html
        assert "Important details" in html

    def test_html_escaping(self):
        html = _render_activity_feed(["## Iteration 1 - <script>alert('xss')</script>\nbody"])
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ── render_html activity section ─────────────────────────────────────────────

class TestRenderHtmlActivitySection:
    def test_activity_section_present_when_sections_provided(self):
        args = _make_minimal_render_args()
        html = render_html(*args, activity_sections=["## Iteration 1 - Story: US-001\nbody"])
        assert "Recent Activity" in html
        assert "<details>" in html

    def test_activity_section_absent_when_no_sections(self):
        args = _make_minimal_render_args()
        html = render_html(*args, activity_sections=[])
        assert "Recent Activity" not in html

    def test_activity_section_absent_when_none(self):
        args = _make_minimal_render_args()
        html = render_html(*args, activity_sections=None)
        assert "Recent Activity" not in html

    def test_activity_section_absent_when_omitted(self):
        args = _make_minimal_render_args()
        html = render_html(*args)
        assert "Recent Activity" not in html


# ── compute_overview ─────────────────────────────────────────────────────────

class TestComputeOverview:
    def test_empty_inputs_produce_zero_counts(self):
        """Empty prd and results → zeroed overview with no crash."""
        overview = compute_overview({"userStories": []}, [])
        assert overview["total"] == 0
        assert overview["passed"] == 0
        assert overview["pending"] == 0
        assert overview["decomposed"] == 0
        assert overview["skipped"] == 0
        assert overview["completion_pct"] == 0
        assert overview["total_attempts"] == 0
        assert overview["elapsed"] == "N/A"
        assert overview["iterations"] == 0
        assert overview["est_cost"] == 0

    def test_partial_inputs_correct_counts(self):
        """Mix of passed, pending, decomposed, skipped stories."""
        prd = {"userStories": [
            {"id": "S-1", "passes": True},
            {"id": "S-2", "passes": True},
            {"id": "S-3", "passes": False},
            {"id": "S-4", "passes": False, "_decomposed": True, "_decomposedInto": ["S-4a"]},
            {"id": "S-4a", "passes": True, "_decomposedFrom": "S-4"},
            {"id": "S-5", "passes": False, "_skipped": True},
        ]}
        results = [
            {"spiral_iter": 1, "status": "keep", "duration_sec": 120, "model": "sonnet"},
            {"spiral_iter": 1, "status": "fail", "duration_sec": 60, "model": "haiku"},
        ]
        overview = compute_overview(prd, results)
        assert overview["total"] == 6
        assert overview["passed"] == 3  # S-1, S-2, S-4a
        assert overview["pending"] == 1  # S-3
        assert overview["decomposed"] == 1  # S-4
        assert overview["skipped"] == 1  # S-5
        assert overview["sub_stories"] == 1  # S-4a
        # effective_total = 6 - 1 decomposed = 5; completion = 3/5 = 60%
        assert overview["completion_pct"] == pytest.approx(60.0)
        assert overview["total_attempts"] == 2

    def test_all_passed_gives_100_pct(self):
        prd = {"userStories": [
            {"id": "S-1", "passes": True},
            {"id": "S-2", "passes": True},
        ]}
        overview = compute_overview(prd, [])
        assert overview["completion_pct"] == pytest.approx(100.0)

    def test_elapsed_with_valid_iso_timestamps(self):
        """Valid ISO timestamps produce human-readable duration string."""
        prd = {"userStories": []}
        results = [
            {"timestamp": "2026-03-13T10:00:00Z", "spiral_iter": 1, "duration_sec": 0},
            {"timestamp": "2026-03-13T12:30:00Z", "spiral_iter": 1, "duration_sec": 0},
        ]
        overview = compute_overview(prd, results)
        assert overview["elapsed"] == "2h 30m"

    def test_elapsed_under_one_hour(self):
        prd = {"userStories": []}
        results = [
            {"timestamp": "2026-03-13T10:00:00Z", "spiral_iter": 1, "duration_sec": 0},
            {"timestamp": "2026-03-13T10:45:00Z", "spiral_iter": 1, "duration_sec": 0},
        ]
        overview = compute_overview(prd, results)
        assert overview["elapsed"] == "45m"

    def test_elapsed_single_timestamp(self):
        """Only one timestamp → N/A (need at least two)."""
        prd = {"userStories": []}
        results = [{"timestamp": "2026-03-13T10:00:00Z", "spiral_iter": 1, "duration_sec": 0}]
        overview = compute_overview(prd, results)
        assert overview["elapsed"] == "N/A"

    def test_est_cost_calculation(self):
        prd = {"userStories": []}
        results = [
            {"spiral_iter": 1, "duration_sec": 3600, "model": "sonnet"},  # 1hr * $0.24
            {"spiral_iter": 1, "duration_sec": 3600, "model": "haiku"},   # 1hr * $0.04
        ]
        overview = compute_overview(prd, results)
        assert overview["est_cost"] == pytest.approx(0.28)

    def test_iterations_picks_max(self):
        prd = {"userStories": []}
        results = [
            {"spiral_iter": 1, "duration_sec": 0},
            {"spiral_iter": 5, "duration_sec": 0},
            {"spiral_iter": 3, "duration_sec": 0},
        ]
        overview = compute_overview(prd, results)
        assert overview["iterations"] == 5


# ── compute_velocity ─────────────────────────────────────────────────────────

class TestComputeVelocity:
    def test_empty_results_returns_empty(self):
        assert compute_velocity([]) == []

    def test_single_iteration(self):
        results = [
            {"spiral_iter": 1, "status": "keep", "duration_sec": 300},
            {"spiral_iter": 1, "status": "fail", "duration_sec": 200},
        ]
        vel = compute_velocity(results)
        assert len(vel) == 1
        assert vel[0]["iter"] == 1
        assert vel[0]["kept"] == 1
        assert vel[0]["total"] == 2
        assert vel[0]["duration_hours"] == pytest.approx(500 / 3600)

    def test_multiple_iterations_correct_velocity(self):
        results = [
            {"spiral_iter": 1, "status": "keep", "duration_sec": 1800},
            {"spiral_iter": 1, "status": "keep", "duration_sec": 1800},
            {"spiral_iter": 2, "status": "keep", "duration_sec": 3600},
            {"spiral_iter": 2, "status": "fail", "duration_sec": 600},
        ]
        vel = compute_velocity(results)
        assert len(vel) == 2
        # iter 1: 2 kept, 3600s total → 1hr → velocity = 2/hr
        assert vel[0]["kept"] == 2
        assert vel[0]["velocity"] == pytest.approx(2.0)
        # iter 2: 1 kept, 4200s total → 1.167hr → velocity ≈ 0.857
        assert vel[1]["kept"] == 1
        assert vel[1]["velocity"] == pytest.approx(1 / (4200 / 3600), rel=1e-2)

    def test_sorted_by_iteration_number(self):
        results = [
            {"spiral_iter": 3, "status": "keep", "duration_sec": 100},
            {"spiral_iter": 1, "status": "keep", "duration_sec": 100},
        ]
        vel = compute_velocity(results)
        assert [v["iter"] for v in vel] == [1, 3]


# ── compute_model_performance ────────────────────────────────────────────────

class TestComputeModelPerformance:
    def test_empty_results_returns_empty(self):
        assert compute_model_performance([]) == []

    def test_mixed_models_correct_success_rates(self):
        results = [
            {"model": "sonnet", "status": "keep", "duration_sec": 120},
            {"model": "sonnet", "status": "keep", "duration_sec": 180},
            {"model": "sonnet", "status": "fail", "duration_sec": 60},
            {"model": "haiku", "status": "keep", "duration_sec": 30},
            {"model": "haiku", "status": "fail", "duration_sec": 20},
            {"model": "haiku", "status": "fail", "duration_sec": 25},
            {"model": "haiku", "status": "fail", "duration_sec": 15},
        ]
        perf = compute_model_performance(results)
        # Sorted by success_rate descending
        assert perf[0]["model"] == "sonnet"
        assert perf[0]["success_rate"] == pytest.approx(200 / 3, rel=1e-2)  # ~66.7%
        assert perf[0]["total"] == 3
        assert perf[0]["kept"] == 2
        assert perf[1]["model"] == "haiku"
        assert perf[1]["success_rate"] == pytest.approx(25.0)  # 1/4
        assert perf[1]["total"] == 4
        assert perf[1]["kept"] == 1

    def test_single_model_all_kept(self):
        results = [
            {"model": "opus", "status": "keep", "duration_sec": 300},
            {"model": "opus", "status": "keep", "duration_sec": 600},
        ]
        perf = compute_model_performance(results)
        assert len(perf) == 1
        assert perf[0]["success_rate"] == pytest.approx(100.0)
        assert perf[0]["avg_duration"] == pytest.approx(450.0)

    def test_unknown_model_collected(self):
        results = [{"status": "keep", "duration_sec": 100}]
        perf = compute_model_performance(results)
        assert perf[0]["model"] == "unknown"


# ── compute_status_breakdown ─────────────────────────────────────────────────

class TestComputeStatusBreakdown:
    def test_empty_inputs(self):
        bd = compute_status_breakdown({"userStories": []}, [])
        assert bd["stories"] == {"passed": 0, "pending": 0, "decomposed": 0, "skipped": 0}
        assert bd["attempts"] == {}

    def test_correct_story_and_attempt_breakdown(self):
        prd = {"userStories": [
            {"id": "S-1", "passes": True},
            {"id": "S-2", "passes": False},
            {"id": "S-3", "passes": False, "_decomposed": True},
            {"id": "S-4", "passes": False, "_skipped": True},
        ]}
        results = [
            {"status": "keep"},
            {"status": "keep"},
            {"status": "fail"},
            {"status": "retry"},
        ]
        bd = compute_status_breakdown(prd, results)
        assert bd["stories"]["passed"] == 1
        assert bd["stories"]["pending"] == 1
        assert bd["stories"]["decomposed"] == 1
        assert bd["stories"]["skipped"] == 1
        assert bd["attempts"]["keep"] == 2
        assert bd["attempts"]["fail"] == 1
        assert bd["attempts"]["retry"] == 1


# ── Auto-refresh meta tag (US-056) ──────────────────────────────────────────

class TestDashboardAutoRefresh:
    def test_meta_refresh_present_when_refresh_secs_positive(self):
        args = _make_minimal_render_args()
        html = render_html(*args, refresh_secs=30)
        assert '<meta http-equiv="refresh" content="30">' in html

    def test_meta_refresh_absent_when_refresh_secs_zero(self):
        args = _make_minimal_render_args()
        html = render_html(*args, refresh_secs=0)
        assert 'http-equiv="refresh"' not in html

    def test_meta_refresh_absent_when_default(self):
        """Default refresh_secs=0 → no meta tag."""
        args = _make_minimal_render_args()
        html = render_html(*args)
        assert 'http-equiv="refresh"' not in html

    def test_footer_shows_refresh_interval(self):
        args = _make_minimal_render_args()
        html = render_html(*args, refresh_secs=45)
        assert "Auto-refreshing every 45s" in html

    def test_footer_no_refresh_text_when_zero(self):
        args = _make_minimal_render_args()
        html = render_html(*args, refresh_secs=0)
        assert "Auto-refreshing" not in html

    def test_custom_refresh_interval(self):
        args = _make_minimal_render_args()
        html = render_html(*args, refresh_secs=10)
        assert '<meta http-equiv="refresh" content="10">' in html
        assert "Auto-refreshing every 10s" in html


# ── detect_orphaned_worktrees ─────────────────────────────────────────────────

import tempfile
import unittest.mock as mock


class TestDetectOrphanedWorktrees:
    def test_missing_workers_dir_returns_empty(self, tmp_path):
        result = detect_orphaned_worktrees(str(tmp_path / "no-such-dir"))
        assert result == []

    def test_empty_workers_dir_returns_empty(self, tmp_path):
        result = detect_orphaned_worktrees(str(tmp_path))
        assert result == []

    def test_worker_without_pid_file_ignored(self, tmp_path):
        (tmp_path / "worker-1").mkdir()
        result = detect_orphaned_worktrees(str(tmp_path))
        assert result == []

    def test_worker_with_invalid_pid_file_ignored(self, tmp_path):
        w = tmp_path / "worker-1"
        w.mkdir()
        (w / "worker.pid").write_text("not-a-number")
        result = detect_orphaned_worktrees(str(tmp_path))
        assert result == []

    def test_dead_pid_returns_orphan(self, tmp_path):
        w = tmp_path / "worker-1"
        w.mkdir()
        dead_pid = 99999999
        (w / "worker.pid").write_text(str(dead_pid))
        with mock.patch("os.kill", side_effect=ProcessLookupError):
            result = detect_orphaned_worktrees(str(tmp_path))
        assert len(result) == 1
        orphan = result[0]
        assert orphan["worker_dir"] == "worker-1"
        assert orphan["pid"] == dead_pid
        assert "git worktree remove" in orphan["suggested_cmd"]
        assert "worker-1" in orphan["path"]

    def test_alive_pid_not_returned(self, tmp_path):
        w = tmp_path / "worker-1"
        w.mkdir()
        (w / "worker.pid").write_text("12345")
        with mock.patch("os.kill", return_value=None):  # no exception = alive
            result = detect_orphaned_worktrees(str(tmp_path))
        assert result == []

    def test_permission_error_treated_as_alive(self, tmp_path):
        w = tmp_path / "worker-1"
        w.mkdir()
        (w / "worker.pid").write_text("12345")
        with mock.patch("os.kill", side_effect=PermissionError):
            result = detect_orphaned_worktrees(str(tmp_path))
        assert result == []

    def test_generic_oserror_treated_as_dead(self, tmp_path):
        w = tmp_path / "worker-1"
        w.mkdir()
        (w / "worker.pid").write_text("12345")
        with mock.patch("os.kill", side_effect=OSError("ESRCH")):
            result = detect_orphaned_worktrees(str(tmp_path))
        assert len(result) == 1

    def test_multiple_workers_mixed_state(self, tmp_path):
        for i in range(1, 4):
            (tmp_path / f"worker-{i}").mkdir()
            (tmp_path / f"worker-{i}" / "worker.pid").write_text(str(1000 + i))

        def fake_kill(pid, sig):
            if pid == 1001:
                raise ProcessLookupError  # dead
            if pid == 1002:
                return None  # alive
            raise PermissionError  # alive but not owned

        with mock.patch("os.kill", side_effect=fake_kill):
            result = detect_orphaned_worktrees(str(tmp_path))

        assert len(result) == 1
        assert result[0]["pid"] == 1001

    def test_orphan_suggested_cmd_contains_absolute_path(self, tmp_path):
        w = tmp_path / "worker-1"
        w.mkdir()
        (w / "worker.pid").write_text("99999")
        with mock.patch("os.kill", side_effect=ProcessLookupError):
            result = detect_orphaned_worktrees(str(tmp_path))
        cmd = result[0]["suggested_cmd"]
        assert cmd.startswith("git worktree remove ")
        assert os.path.isabs(result[0]["path"])

    def test_render_html_shows_orphaned_section(self):
        """render_html includes ORPHANED section when orphaned_worktrees provided."""
        args = _make_minimal_render_args()
        orphans = [{"worker_dir": "worker-1", "path": "/some/path/worker-1", "pid": 9999, "suggested_cmd": "git worktree remove /some/path/worker-1"}]
        html = render_html(*args, orphaned_worktrees=orphans)
        assert "ORPHANED" in html
        assert "worker-1" in html
        assert "git worktree remove" in html
        assert "9999" in html

    def test_render_html_no_orphaned_section_when_empty(self):
        args = _make_minimal_render_args()
        html = render_html(*args, orphaned_worktrees=[])
        assert "Orphaned Worktrees" not in html


# ── compute_stale_stories (US-129) ───────────────────────────────────────────

def _make_ts(days_ago: float) -> str:
    """Return ISO 8601 UTC timestamp that is *days_ago* days in the past."""
    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestComputeStaleStories:
    def test_empty_prd_returns_empty(self):
        assert compute_stale_stories({"userStories": []}, stale_days=7) == {}

    def test_story_without_last_attempted_not_stale(self):
        prd = {"userStories": [{"id": "US-001", "title": "T", "passes": False}]}
        assert compute_stale_stories(prd, stale_days=7) == {}

    def test_fresh_story_not_stale(self):
        prd = {"userStories": [
            {"id": "US-001", "title": "T", "passes": False, "last_attempted": _make_ts(1)}
        ]}
        assert compute_stale_stories(prd, stale_days=7) == {}

    def test_old_story_is_stale(self):
        prd = {"userStories": [
            {"id": "US-001", "title": "T", "passes": False, "last_attempted": _make_ts(10)}
        ]}
        result = compute_stale_stories(prd, stale_days=7)
        assert "US-001" in result
        assert result["US-001"] >= 9  # at least 9 days old

    def test_passed_story_never_stale(self):
        prd = {"userStories": [
            {"id": "US-001", "title": "T", "passes": True, "last_attempted": _make_ts(20)}
        ]}
        assert compute_stale_stories(prd, stale_days=7) == {}

    def test_decomposed_story_never_stale(self):
        prd = {"userStories": [
            {"id": "US-001", "title": "T", "passes": False, "_decomposed": True, "last_attempted": _make_ts(20)}
        ]}
        assert compute_stale_stories(prd, stale_days=7) == {}

    def test_skipped_story_never_stale(self):
        prd = {"userStories": [
            {"id": "US-001", "title": "T", "passes": False, "_skipped": True, "last_attempted": _make_ts(20)}
        ]}
        assert compute_stale_stories(prd, stale_days=7) == {}

    def test_multiple_stories_only_old_ones_flagged(self):
        prd = {"userStories": [
            {"id": "US-001", "passes": False, "last_attempted": _make_ts(2)},
            {"id": "US-002", "passes": False, "last_attempted": _make_ts(10)},
            {"id": "US-003", "passes": False, "last_attempted": _make_ts(15)},
        ]}
        result = compute_stale_stories(prd, stale_days=7)
        assert "US-001" not in result
        assert "US-002" in result
        assert "US-003" in result

    def test_invalid_timestamp_skipped(self):
        prd = {"userStories": [
            {"id": "US-001", "passes": False, "last_attempted": "not-a-date"}
        ]}
        assert compute_stale_stories(prd, stale_days=7) == {}


class TestComputeStoryAttemptsStale:
    def test_stale_days_present_in_stale_story(self):
        prd = {"userStories": [
            {"id": "US-001", "title": "T", "passes": False, "last_attempted": _make_ts(10)}
        ]}
        result = compute_story_attempts(prd, [], )
        assert "stale_days" in result["US-001"]
        assert result["US-001"]["stale_days"] >= 9

    def test_stale_days_absent_for_fresh_story(self):
        prd = {"userStories": [
            {"id": "US-001", "title": "T", "passes": False, "last_attempted": _make_ts(1)}
        ]}
        result = compute_story_attempts(prd, [])
        assert "stale_days" not in result["US-001"]

    def test_stale_badge_in_render_html(self):
        """render_html shows stale badge for a stale pending story."""
        prd = {"userStories": [
            {"id": "US-001", "title": "Old story", "passes": False, "last_attempted": _make_ts(10)}
        ]}
        story_attempts = compute_story_attempts(prd, [])
        args = _make_minimal_render_args()
        html = render_html(*args, story_attempts=story_attempts)
        assert "stale-badge" in html
        assert "stale" in html


# ── compute_token_forecast (US-151) ──────────────────────────────────────────

def _recent_ts(seconds_ago: float = 0) -> str:
    """Return ISO 8601 UTC timestamp that is *seconds_ago* seconds in the past."""
    ts = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def _make_token_rows(n: int, tokens_each: int = 10000, seconds_ago: float = 60) -> list[dict]:
    """Return *n* results rows with token data, all within the last hour."""
    return [
        {
            "timestamp": _recent_ts(seconds_ago),
            "input_tokens": tokens_each,
            "output_tokens": 0,
            "status": "keep",
        }
        for _ in range(n)
    ]


class TestComputeTokenForecast:
    def test_empty_results_returns_none(self):
        assert compute_token_forecast([]) is None

    def test_fewer_than_three_rows_returns_none(self):
        rows = _make_token_rows(2)
        assert compute_token_forecast(rows) is None

    def test_no_token_columns_returns_none(self):
        rows = [{"timestamp": _recent_ts(60), "status": "keep"} for _ in range(5)]
        assert compute_token_forecast(rows) is None

    def test_rows_older_than_one_hour_excluded(self):
        old_rows = _make_token_rows(5, tokens_each=5000, seconds_ago=3700)
        assert compute_token_forecast(old_rows) is None

    def test_three_or_more_recent_rows_returns_dict(self):
        rows = _make_token_rows(3, tokens_each=100_000)
        result = compute_token_forecast(rows, daily_limit=1_000_000)
        assert result is not None

    def test_burn_rate_is_sum_of_window_tokens(self):
        rows = _make_token_rows(4, tokens_each=50_000)
        result = compute_token_forecast(rows, daily_limit=1_000_000)
        assert result is not None
        assert result["burn_rate_per_hour"] == 4 * 50_000

    def test_hours_to_exhaustion_calculation(self):
        rows = _make_token_rows(4, tokens_each=250_000)  # 1,000,000 total
        result = compute_token_forecast(rows, daily_limit=1_000_000)
        assert result is not None
        assert result["hours_to_exhaustion"] == pytest.approx(1.0)

    def test_amber_alert_true_when_less_than_two_hours(self):
        # 600,000 tokens/hr → limit of 1,000,000 → ~1.67 hrs → amber
        rows = _make_token_rows(6, tokens_each=100_000)
        result = compute_token_forecast(rows, daily_limit=1_000_000)
        assert result is not None
        assert result["amber_alert"] is True

    def test_amber_alert_false_when_more_than_two_hours(self):
        # 100,000 tokens/hr → limit of 1,000,000 → 10 hrs → no amber
        rows = _make_token_rows(4, tokens_each=25_000)
        result = compute_token_forecast(rows, daily_limit=1_000_000)
        assert result is not None
        assert result["amber_alert"] is False

    def test_time_str_hours_and_minutes_format(self):
        # 500,000 tokens/hr → 1,000,000 limit → 2h 0m
        rows = _make_token_rows(5, tokens_each=100_000)
        result = compute_token_forecast(rows, daily_limit=1_000_000)
        assert result is not None
        assert result["time_str"].startswith("~2h")

    def test_time_str_minutes_only_when_under_one_hour(self):
        # 4 rows * 300,000 = 1,200,000 tokens/hr → 1,000,000 limit → < 1 hr
        rows = _make_token_rows(4, tokens_each=300_000)
        result = compute_token_forecast(rows, daily_limit=1_000_000)
        assert result is not None
        assert result["hours_to_exhaustion"] < 1.0
        assert result["time_str"].startswith("~")
        assert "h" not in result["time_str"]
        assert "m" in result["time_str"]

    def test_exhaustion_clock_is_hhmm_format(self):
        rows = _make_token_rows(3, tokens_each=10_000)
        result = compute_token_forecast(rows, daily_limit=1_000_000)
        assert result is not None
        import re
        assert re.match(r"^\d{2}:\d{2}$", result["exhaustion_clock"])

    def test_daily_limit_key_present_in_result(self):
        rows = _make_token_rows(3)
        result = compute_token_forecast(rows, daily_limit=500_000)
        assert result is not None
        assert result["daily_limit"] == 500_000

    def test_spiral_daily_token_limit_env_var(self, monkeypatch):
        monkeypatch.setenv("SPIRAL_DAILY_TOKEN_LIMIT", "500000")
        rows = _make_token_rows(3, tokens_each=100_000)
        result = compute_token_forecast(rows)
        assert result is not None
        assert result["daily_limit"] == 500_000

    def test_default_daily_limit_is_one_million(self, monkeypatch):
        monkeypatch.delenv("SPIRAL_DAILY_TOKEN_LIMIT", raising=False)
        rows = _make_token_rows(3, tokens_each=10_000)
        result = compute_token_forecast(rows)
        assert result is not None
        assert result["daily_limit"] == 1_000_000

    def test_rows_with_only_output_tokens_counted(self):
        rows = [
            {"timestamp": _recent_ts(60), "input_tokens": 0, "output_tokens": 10_000}
            for _ in range(3)
        ]
        result = compute_token_forecast(rows, daily_limit=1_000_000)
        assert result is not None
        assert result["burn_rate_per_hour"] == 30_000

    def test_mixed_old_and_new_only_new_counted(self):
        old = _make_token_rows(5, tokens_each=100_000, seconds_ago=7200)  # 2 hrs ago
        new = _make_token_rows(3, tokens_each=50_000, seconds_ago=30)
        result = compute_token_forecast(old + new, daily_limit=1_000_000)
        assert result is not None
        assert result["burn_rate_per_hour"] == 3 * 50_000


class TestRenderHtmlTokenForecast:
    def test_widget_hidden_when_forecast_none(self):
        args = _make_minimal_render_args()
        html = render_html(*args, token_forecast=None)
        assert "API Rate-Limit Forecast" not in html

    def test_widget_hidden_when_omitted(self):
        args = _make_minimal_render_args()
        html = render_html(*args)
        assert "API Rate-Limit Forecast" not in html

    def test_widget_shown_when_forecast_provided(self):
        args = _make_minimal_render_args()
        forecast = {
            "burn_rate_per_hour": 100_000,
            "hours_to_exhaustion": 10.0,
            "time_str": "~10h 0m",
            "exhaustion_clock": "22:00",
            "daily_limit": 1_000_000,
            "amber_alert": False,
        }
        html = render_html(*args, token_forecast=forecast)
        assert "API Rate-Limit Forecast" in html
        assert "Tokens / Hour" in html
        assert "Daily Limit In" in html

    def test_widget_shows_burn_rate(self):
        args = _make_minimal_render_args()
        forecast = {
            "burn_rate_per_hour": 250_000,
            "hours_to_exhaustion": 4.0,
            "time_str": "~4h 0m",
            "exhaustion_clock": "18:00",
            "daily_limit": 1_000_000,
            "amber_alert": False,
        }
        html = render_html(*args, token_forecast=forecast)
        assert "250,000" in html

    def test_widget_amber_alert_present_when_flag_true(self):
        args = _make_minimal_render_args()
        forecast = {
            "burn_rate_per_hour": 600_000,
            "hours_to_exhaustion": 1.67,
            "time_str": "~1h 40m",
            "exhaustion_clock": "16:30",
            "daily_limit": 1_000_000,
            "amber_alert": True,
        }
        html = render_html(*args, token_forecast=forecast)
        assert "LOW BUDGET" in html

    def test_widget_no_amber_when_flag_false(self):
        args = _make_minimal_render_args()
        forecast = {
            "burn_rate_per_hour": 50_000,
            "hours_to_exhaustion": 20.0,
            "time_str": "~20h 0m",
            "exhaustion_clock": "08:00",
            "daily_limit": 1_000_000,
            "amber_alert": False,
        }
        html = render_html(*args, token_forecast=forecast)
        assert "LOW BUDGET" not in html

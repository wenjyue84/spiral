"""Tests for spiral_dashboard.py — velocity chart (US-034)."""
import os
import sys

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

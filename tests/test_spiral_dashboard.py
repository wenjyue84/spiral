"""Tests for spiral_dashboard.py — velocity chart (US-034)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from spiral_dashboard import (  # noqa: E402
    compute_iteration_velocity,
    _render_velocity_svg,
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

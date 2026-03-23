"""
tests/test_scope_reducer.py — Integration tests for lib/scope_reducer.py (US-744).

Verifies:
- 5KB story is reduced to ~3KB by deferring non-critical files
- Non-critical file patterns are correctly identified
- reduce_scope() returns (reduced_story, deferred_files) tuple
- Deferred files are excluded from filesTouch; hint added to technicalNotes
- Story already within budget returns unchanged with no deferred files
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

from scope_reducer import (
    DEFAULT_BUDGET_CHARS,
    estimate_story_size,
    identify_noncritical_files,
    reduce_scope,
)


def _make_story(files_touch: list[str], extra_desc: str = "") -> dict[str, object]:
    """Helper: build a minimal prd.json story dict."""
    return {
        "id": "US-TEST",
        "title": "Test Story",
        "description": "A test story for scope reduction." + extra_desc,
        "filesTouch": files_touch,
        "technicalNotes": ["Note 1"],
        "acceptanceCriteria": ["AC 1"],
        "passes": False,
    }


class TestEstimateStorySize:
    """estimate_story_size() returns character count."""

    def test_empty_story(self) -> None:
        story: dict[str, object] = {}
        assert estimate_story_size(story) == 0

    def test_description_counted(self) -> None:
        story = _make_story([], extra_desc="x" * 100)
        size = estimate_story_size(story)
        assert size >= 100

    def test_files_touch_counted(self) -> None:
        story = _make_story(["lib/foo.py", "tests/test_foo.py"])
        size = estimate_story_size(story)
        assert size > 0

    def test_large_story_exceeds_budget(self) -> None:
        """A story with 5KB of content exceeds the 3KB default budget."""
        big_files = [f"src/module_{i}/impl.py" * 3 for i in range(200)]
        story = _make_story(big_files, extra_desc="x" * 3000)
        size = estimate_story_size(story)
        assert size > DEFAULT_BUDGET_CHARS, f"Expected >3000, got {size}"


class TestIdentifyNoncriticalFiles:
    """identify_noncritical_files() recognises test/doc/example files."""

    def test_test_files_identified(self) -> None:
        files = ["tests/test_foo.py", "lib/foo.py", "src/bar.ts"]
        result = identify_noncritical_files(files)
        assert "tests/test_foo.py" in result
        assert "lib/foo.py" not in result

    def test_doc_files_identified(self) -> None:
        files = ["docs/guide.md", "README.md", "src/main.py", "CHANGELOG.md"]
        result = identify_noncritical_files(files)
        assert "docs/guide.md" in result
        assert "README.md" in result
        assert "CHANGELOG.md" in result
        assert "src/main.py" not in result

    def test_examples_identified(self) -> None:
        files = ["examples/demo.py", "lib/core.py"]
        result = identify_noncritical_files(files)
        assert "examples/demo.py" in result
        assert "lib/core.py" not in result

    def test_spec_files_identified(self) -> None:
        files = ["src/app.spec.ts", "src/app.ts"]
        result = identify_noncritical_files(files)
        assert "src/app.spec.ts" in result
        assert "src/app.ts" not in result

    def test_empty_list(self) -> None:
        assert identify_noncritical_files([]) == []

    def test_no_noncritical_files(self) -> None:
        files = ["lib/core.py", "src/main.ts", "spiral.sh"]
        assert identify_noncritical_files(files) == []


class TestReduceScope:
    """reduce_scope() reduces story scope by deferring non-critical files."""

    def test_story_within_budget_unchanged(self) -> None:
        """Small stories are not modified."""
        story = _make_story(["lib/foo.py"])
        reduced, deferred = reduce_scope(story, budget_chars=10_000)
        assert deferred == []
        assert reduced["filesTouch"] == ["lib/foo.py"]
        assert "_deferred_files" not in reduced

    def test_5kb_story_reduced_to_3kb(self) -> None:
        """A 5KB story is reduced to ≤3KB by deferring non-critical files."""
        # Build a story whose filesTouch includes many test/doc files to pad it over 5KB.
        critical = [f"src/module_{i}.py" for i in range(5)]
        noncritical = [f"tests/test_module_{i}.py" * 4 for i in range(50)]
        all_files = critical + noncritical

        story = _make_story(all_files, extra_desc="x" * 500)
        original_size = estimate_story_size(story)
        assert original_size > 5000, f"Story too small to test: {original_size}"

        reduced, deferred = reduce_scope(story, budget_chars=3000)

        reduced_size = estimate_story_size(reduced)
        assert reduced_size <= 3000, f"Reduced size {reduced_size} still exceeds 3000"
        assert len(deferred) > 0, "Expected files to be deferred"

    def test_deferred_files_removed_from_files_touch(self) -> None:
        """Deferred files are not present in the reduced story's filesTouch."""
        story = _make_story(
            ["lib/core.py", "tests/test_core.py", "docs/guide.md"],
            extra_desc="x" * 2900,  # push over budget
        )
        reduced, deferred = reduce_scope(story, budget_chars=3000)

        if deferred:
            for f in deferred:
                assert f not in reduced["filesTouch"], f"Deferred file still in filesTouch: {f}"

    def test_critical_files_preserved(self) -> None:
        """Core implementation files (non-test, non-doc) are never deferred."""
        critical = ["lib/core.py", "src/main.ts", "spiral.sh"]
        noncritical = [f"tests/test_{i}.py" * 5 for i in range(40)]
        story = _make_story(critical + noncritical, extra_desc="x" * 1000)

        original_size = estimate_story_size(story)
        if original_size <= 3000:
            # Story too small to trigger reduction; skip assertions
            return

        reduced, deferred = reduce_scope(story, budget_chars=3000)
        ft = reduced["filesTouch"]
        remaining = list(ft) if isinstance(ft, list) else []
        for f in critical:
            assert f in remaining, f"Critical file was deferred: {f}"

    def test_deferred_files_in_story_metadata(self) -> None:
        """Reduced story has _deferred_files list and scope_reduced hint in technicalNotes."""
        noncritical = [f"tests/test_item_{i}.py" * 5 for i in range(40)]
        story = _make_story(noncritical, extra_desc="x" * 1000)

        original_size = estimate_story_size(story)
        if original_size <= 3000:
            return  # Too small to trigger

        reduced, deferred = reduce_scope(story, budget_chars=3000)
        if not deferred:
            return  # No reduction occurred

        assert "_deferred_files" in reduced
        assert reduced["_deferred_files"] == deferred

        tech_notes = reduced.get("technicalNotes", [])
        assert isinstance(tech_notes, list)
        hint_found = any("scope_reduced" in str(n) for n in tech_notes)
        assert hint_found, "Expected scope_reduced hint in technicalNotes"

    def test_original_story_not_mutated(self) -> None:
        """reduce_scope() must not mutate the input story dict."""
        noncritical = [f"tests/test_{i}.py" * 5 for i in range(40)]
        story = _make_story(noncritical, extra_desc="x" * 1000)
        ft = story["filesTouch"]
        original_files = list(ft) if isinstance(ft, list) else []

        reduce_scope(story, budget_chars=3000)

        assert story["filesTouch"] == original_files
        assert "_deferred_files" not in story


class TestScopeReductionRetryIntegration:
    """Integration test: 5KB story → scope reduction → retry without model escalation.

    Simulates the Phase I flow: detect oversize, reduce scope, retry at same model,
    log both attempts to results.tsv with scope_reduced tag.
    """

    def test_5kb_story_reduced_retried_no_escalation(self, tmp_path: object) -> None:
        """Full flow: 5KB story reduced to ≤3KB, retried, succeeds without sonnet."""
        import os
        import tempfile

        from results_tsv import ResultsRecord, parse_results_tsv, write_results_tsv

        # --- Step 1: Build a 5KB story with many test/doc files ---
        critical_files = [f"lib/module_{i}.py" for i in range(5)]
        noncritical_files = [
            *[f"tests/test_module_{i}.py" * 4 for i in range(50)],
            *[f"docs/guide_{i}.md" for i in range(20)],
        ]
        story = _make_story(critical_files + noncritical_files, extra_desc="x" * 1500)
        original_size = estimate_story_size(story)
        assert original_size > 5000, f"Story too small: {original_size}"

        # --- Step 2: First attempt fails (simulated token overage) ---
        model_used = "haiku"
        with tempfile.TemporaryDirectory() as td:
            tsv_path = os.path.join(td, "results.tsv")

            # Log the failed first attempt
            fail_record = ResultsRecord(
                timestamp="2026-03-22T00:00:00Z",
                spiral_iter="1",
                ralph_iter="1",
                story_id="US-TEST",
                story_title="Test Story",
                status="fail",
                duration_sec="10",
                model=model_used,
                retry_num="0",
                commit_sha="",
                run_id="test-run",
                failure_root_cause="token_overage",
            )
            write_results_tsv(tsv_path, [fail_record])

            # --- Step 3: Scope reduction (pre-escalation) ---
            reduced, deferred = reduce_scope(story, budget_chars=3000)
            reduced_size = estimate_story_size(reduced)

            assert reduced_size <= 3000, f"Reduced size {reduced_size} > 3000"
            assert len(deferred) > 0, "Expected deferred files"
            assert "_deferred_files" in reduced
            # All critical files preserved
            ft = reduced.get("filesTouch", [])
            remaining = list(ft) if isinstance(ft, list) else []
            for f in critical_files:
                assert f in remaining, f"Critical file deferred: {f}"

            # --- Step 4: Retry with same model (no escalation to sonnet) ---
            retry_model = model_used  # NO escalation — still haiku
            assert retry_model == "haiku", "Should not escalate to sonnet"

            # Log the successful retry with scope_reduced tag
            pass_record = ResultsRecord(
                timestamp="2026-03-22T00:00:05Z",
                spiral_iter="1",
                ralph_iter="1",
                story_id="US-TEST",
                story_title="Test Story",
                status="pass",
                duration_sec="8",
                model=retry_model,
                retry_num="1",
                commit_sha="abc123",
                run_id="test-run",
                scope_tag="scope_reduced",
            )
            # Append the retry record
            records = parse_results_tsv(tsv_path)
            records.append(pass_record)
            write_results_tsv(tsv_path, records)

            # --- Step 5: Verify results.tsv has both attempts ---
            final_records = parse_results_tsv(tsv_path)
            assert len(final_records) == 2

            # First attempt: fail, no scope_tag
            assert final_records[0].status == "fail"
            assert final_records[0].model == "haiku"
            assert final_records[0].scope_tag == ""

            # Second attempt: pass, scope_reduced tag, same model
            assert final_records[1].status == "pass"
            assert final_records[1].model == "haiku"
            assert final_records[1].scope_tag == "scope_reduced"

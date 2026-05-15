"""Tests for lib/central_log.py — CentralLog class."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from lib.central_log import CentralLog, compute_cost


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "test_central.db")


@pytest.fixture()
def cl(db_path):
    log = CentralLog(db_path=db_path)
    yield log
    log.close()


class TestComputeCost:
    def test_haiku_cost(self):
        # 1M read tokens at $0.80/M = $0.80
        cost = compute_cost("haiku", cache_read_tokens=1_000_000)
        assert abs(cost - 0.80) < 0.001

    def test_sonnet_output_cost(self):
        # 1M creation tokens at $15/M = $15.00
        cost = compute_cost("sonnet", cache_creation_tokens=1_000_000)
        assert abs(cost - 15.0) < 0.001

    def test_unknown_model_defaults_to_sonnet(self):
        cost = compute_cost("unknown-model", cache_read_tokens=1_000_000)
        expected = compute_cost("sonnet", cache_read_tokens=1_000_000)
        assert cost == expected

    def test_zero_tokens(self):
        assert compute_cost("haiku") == 0.0


class TestSchema:
    def test_tables_exist(self, cl, db_path):
        con = sqlite3.connect(db_path)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "runs" in tables
        assert "story_attempts" in tables
        con.close()

    def test_wal_mode(self, cl, db_path):
        con = sqlite3.connect(db_path)
        mode = con.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        con.close()


class TestRecordRunStart:
    def test_basic(self, cl):
        cl.record_run_start("run-1", "/home/user/project-a", "2026-01-01T00:00:00Z")
        row = cl.con.execute("SELECT * FROM runs WHERE run_id = 'run-1'").fetchone()
        assert row is not None
        assert row["project_name"] == "project-a"
        assert row["project_path"] == "/home/user/project-a"
        assert row["started_at"] == "2026-01-01T00:00:00Z"

    def test_duplicate_ignored(self, cl):
        cl.record_run_start("run-dup", "/foo")
        cl.record_run_start("run-dup", "/bar")  # should not crash
        count = cl.con.execute("SELECT COUNT(*) FROM runs WHERE run_id = 'run-dup'").fetchone()[0]
        assert count == 1


class TestRecordStory:
    def test_basic(self, cl):
        cl.record_run_start("run-s1", "/proj")
        cl.record_story(
            run_id="run-s1",
            project_name="proj",
            story_id="US-100",
            story_title="Add login",
            model="sonnet",
            duration_sec=120.5,
            status="pass",
            spiral_iter=3,
            cache_read_tokens=50000,
            cache_creation_tokens=10000,
        )
        row = cl.con.execute("SELECT * FROM story_attempts WHERE story_id = 'US-100'").fetchone()
        assert row is not None
        assert row["status"] == "pass"
        assert row["model"] == "sonnet"
        assert row["cost_usd"] > 0

    def test_auto_cost_computation(self, cl):
        cl.record_run_start("run-ac", "/proj")
        cl.record_story(
            run_id="run-ac",
            project_name="proj",
            story_id="US-200",
            model="haiku",
            cache_read_tokens=1_000_000,
            cache_creation_tokens=0,
        )
        row = cl.con.execute("SELECT cost_usd FROM story_attempts WHERE story_id = 'US-200'").fetchone()
        assert abs(row[0] - 0.80) < 0.001


class TestRecordRunEnd:
    def test_aggregates_cost_and_models(self, cl):
        cl.record_run_start("run-e1", "/proj")
        cl.record_story(run_id="run-e1", project_name="proj", story_id="US-1", model="haiku", status="pass", cache_read_tokens=500000)
        cl.record_story(run_id="run-e1", project_name="proj", story_id="US-2", model="sonnet", status="fail", failure_type="timeout", cache_read_tokens=100000)

        cl.record_run_end(
            run_id="run-e1",
            exit_code=0,
            iterations=5,
            stories_attempted=2,
            stories_passed=1,
            stories_failed=1,
        )

        row = cl.con.execute("SELECT * FROM runs WHERE run_id = 'run-e1'").fetchone()
        assert row["exit_code"] == 0
        assert row["iterations"] == 5
        assert row["stories_passed"] == 1
        assert row["stories_failed"] == 1
        assert row["total_cost_usd"] > 0

        models = json.loads(row["models_used"])
        assert "haiku" in models
        assert "sonnet" in models

        failures = json.loads(row["top_failure_types"])
        assert failures.get("timeout") == 1

    def test_end_without_stories(self, cl):
        cl.record_run_start("run-empty", "/proj")
        cl.record_run_end(run_id="run-empty", exit_code=1, iterations=0)
        row = cl.con.execute("SELECT * FROM runs WHERE run_id = 'run-empty'").fetchone()
        assert row["total_cost_usd"] == 0
        assert row["ended_at"] is not None


class TestContextManager:
    def test_with_statement(self, db_path):
        with CentralLog(db_path=db_path) as cl:
            cl.record_run_start("run-ctx", "/proj")
        # Connection should be closed — opening a new one should work
        con = sqlite3.connect(db_path)
        count = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert count == 1
        con.close()


class TestNeverCrashes:
    def test_record_story_without_run(self, cl):
        """Recording a story for a non-existent run should not crash."""
        cl.record_story(
            run_id="nonexistent",
            project_name="proj",
            story_id="US-999",
            model="haiku",
            status="pass",
        )
        row = cl.con.execute("SELECT * FROM story_attempts WHERE story_id = 'US-999'").fetchone()
        assert row is not None

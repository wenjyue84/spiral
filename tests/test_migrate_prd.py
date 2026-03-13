"""Tests for lib/migrate_prd.py migration logic."""
import json
import os
import sys
import subprocess
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from migrate_prd import migrate_prd, CURRENT_SCHEMA_VERSION


class TestMigratePrdFunction:
    """Unit tests for the migrate_prd() function."""

    def test_already_current_no_changes(self):
        """PRD at current version should produce no changes."""
        prd = {
            "schemaVersion": CURRENT_SCHEMA_VERSION,
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {"id": "US-001", "title": "T", "passes": False, "priority": "high",
                 "acceptanceCriteria": ["x"], "dependencies": []}
            ],
        }
        result, changes = migrate_prd(prd)
        assert changes == []
        assert result["schemaVersion"] == CURRENT_SCHEMA_VERSION

    def test_unversioned_gets_schema_version(self):
        """PRD without schemaVersion gets it added."""
        prd = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {"id": "US-001", "title": "T", "passes": False, "priority": "high",
                 "acceptanceCriteria": ["x"], "dependencies": []}
            ],
        }
        result, changes = migrate_prd(prd)
        assert result["schemaVersion"] == CURRENT_SCHEMA_VERSION
        assert any("schemaVersion" in c for c in changes)

    def test_missing_dependencies_added(self):
        """Stories missing dependencies get an empty list added."""
        prd = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {"id": "US-001", "title": "T", "passes": False, "priority": "high",
                 "acceptanceCriteria": ["x"]},
                {"id": "US-002", "title": "T2", "passes": False, "priority": "low",
                 "acceptanceCriteria": ["y"], "dependencies": ["US-001"]},
            ],
        }
        result, changes = migrate_prd(prd)
        assert result["userStories"][0]["dependencies"] == []
        assert result["userStories"][1]["dependencies"] == ["US-001"]
        assert any("US-001" in c for c in changes)

    def test_idempotent(self):
        """Running migration twice produces the same result."""
        prd = {
            "productName": "Test",
            "branchName": "main",
            "userStories": [
                {"id": "US-001", "title": "T", "passes": False, "priority": "high",
                 "acceptanceCriteria": ["x"]},
            ],
        }
        result1, changes1 = migrate_prd(prd)
        result2, changes2 = migrate_prd(result1)
        assert changes2 == []
        assert result1 == result2

    def test_future_version_no_changes(self):
        """PRD with future version should not be modified by migrate_prd."""
        prd = {
            "schemaVersion": CURRENT_SCHEMA_VERSION + 5,
            "productName": "Test",
            "branchName": "main",
            "userStories": [],
        }
        result, changes = migrate_prd(prd)
        assert changes == []
        assert result["schemaVersion"] == CURRENT_SCHEMA_VERSION + 5

    def test_non_dict_returns_unchanged(self):
        """Non-dict input is returned unchanged."""
        result, changes = migrate_prd([])
        assert result == []
        assert changes == []


class TestMigratePrdCli:
    """Integration tests for migrate_prd.py CLI."""

    def _run(self, prd_path, *extra_args):
        cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "..", "lib", "migrate_prd.py"),
               str(prd_path)] + list(extra_args)
        return subprocess.run(cmd, capture_output=True, text=True)

    def test_check_current_returns_0(self, tmp_path):
        prd = {"schemaVersion": CURRENT_SCHEMA_VERSION, "productName": "X",
               "branchName": "m", "userStories": []}
        p = tmp_path / "prd.json"
        p.write_text(json.dumps(prd), encoding="utf-8")
        result = self._run(p, "--check")
        assert result.returncode == 0

    def test_check_unversioned_returns_2(self, tmp_path):
        prd = {"productName": "X", "branchName": "m", "userStories": []}
        p = tmp_path / "prd.json"
        p.write_text(json.dumps(prd), encoding="utf-8")
        result = self._run(p, "--check")
        assert result.returncode == 2

    def test_dry_run_does_not_modify(self, tmp_path):
        prd = {"productName": "X", "branchName": "m", "userStories": []}
        p = tmp_path / "prd.json"
        p.write_text(json.dumps(prd), encoding="utf-8")
        original = p.read_text(encoding="utf-8")
        result = self._run(p, "--dry-run")
        assert result.returncode == 0
        assert p.read_text(encoding="utf-8") == original

    def test_migrate_writes_schema_version(self, tmp_path):
        prd = {"productName": "X", "branchName": "m", "userStories": [
            {"id": "US-001", "title": "T", "passes": False, "priority": "high",
             "acceptanceCriteria": ["x"]}
        ]}
        p = tmp_path / "prd.json"
        p.write_text(json.dumps(prd), encoding="utf-8")
        result = self._run(p)
        assert result.returncode == 0
        migrated = json.loads(p.read_text(encoding="utf-8"))
        assert migrated["schemaVersion"] == CURRENT_SCHEMA_VERSION
        assert migrated["userStories"][0]["dependencies"] == []

    def test_future_version_returns_2(self, tmp_path):
        prd = {"schemaVersion": 999, "productName": "X", "branchName": "m", "userStories": []}
        p = tmp_path / "prd.json"
        p.write_text(json.dumps(prd), encoding="utf-8")
        result = self._run(p)
        assert result.returncode == 2

    def test_missing_file_returns_1(self, tmp_path):
        result = self._run(tmp_path / "nonexistent.json")
        assert result.returncode == 1

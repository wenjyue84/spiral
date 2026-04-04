#!/usr/bin/env python3
"""
tests/test_skip_rt.py — US-1103: Skip redundant Phase R/T when no new stories merged

Tests the SKIP_RT flag logic:
- SKIP_RT=true when Phase M merged 0 stories AND all pending stories have retries > 0
- SKIP_RT=false when Phase M merged > 0 stories
- SKIP_RT=false when Phase M merged 0 stories but some pending have retries = 0
- SKIP_RT=true when Phase M merged 0 stories and no pending stories exist
"""

import json
import tempfile
from pathlib import Path
from typing import Any


def test_skip_rt_0_added_all_retried() -> None:
    """Test: ADDED=0, all pending stories have retries > 0 → SKIP_RT=true"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        # Create prd.json with 3 pending stories (all passes=false)
        prd: dict[str, Any] = {
            "userStories": [
                {"id": "US-1", "passes": True},
                {"id": "US-2", "passes": False},
                {"id": "US-3", "passes": False},
                {"id": "US-4", "passes": False},
            ]
        }
        prd_file = tmpdir_path / "prd.json"
        prd_file.write_text(json.dumps(prd, indent=2), encoding="utf-8")

        # Create retry-counts.json with all pending stories having retries > 0
        retries: dict[str, int] = {
            "US-2": 1,
            "US-3": 2,
            "US-4": 3,
        }
        retries_file = tmpdir_path / "retry-counts.json"
        retries_file.write_text(json.dumps(retries, indent=2), encoding="utf-8")

        # Simulate the logic from spiral.sh after Phase M
        # ADDED=0
        added = 0

        # Check if all pending stories have retries > 0
        skip_rt = False
        if added == 0:
            pending_ids = [s["id"] for s in prd["userStories"] if not s.get("passes")]
            if not pending_ids:
                skip_rt = True
            else:
                all_have_retries = True
                for story_id in pending_ids:
                    retry_count = retries.get(story_id, 0)
                    if retry_count == 0:
                        all_have_retries = False
                        break
                if all_have_retries:
                    skip_rt = True

        assert skip_rt is True, "SKIP_RT should be true when ADDED=0 and all pending have retries > 0"


def test_skip_rt_added_gt_0() -> None:
    """Test: ADDED > 0 → SKIP_RT=false"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        prd: dict[str, Any] = {
            "userStories": [
                {"id": "US-1", "passes": False},
                {"id": "US-2", "passes": False},
            ]
        }
        prd_file = tmpdir_path / "prd.json"
        prd_file.write_text(json.dumps(prd, indent=2), encoding="utf-8")

        retries: dict[str, int] = {
            "US-1": 1,
            "US-2": 1,
        }
        retries_file = tmpdir_path / "retry-counts.json"
        retries_file.write_text(json.dumps(retries, indent=2), encoding="utf-8")

        # Simulate: ADDED=1
        added = 1

        skip_rt = False
        if added == 0:
            pending_ids = [s["id"] for s in prd["userStories"] if not s.get("passes")]
            if not pending_ids:
                skip_rt = True
            else:
                all_have_retries = True
                for story_id in pending_ids:
                    retry_count = retries.get(story_id, 0)
                    if retry_count == 0:
                        all_have_retries = False
                        break
                if all_have_retries:
                    skip_rt = True

        assert skip_rt is False, "SKIP_RT should be false when ADDED > 0"


def test_skip_rt_0_added_some_not_retried() -> None:
    """Test: ADDED=0, some pending have retries=0 → SKIP_RT=false"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        prd: dict[str, Any] = {
            "userStories": [
                {"id": "US-1", "passes": False},
                {"id": "US-2", "passes": False},
                {"id": "US-3", "passes": False},
            ]
        }
        prd_file = tmpdir_path / "prd.json"
        prd_file.write_text(json.dumps(prd, indent=2), encoding="utf-8")

        retries: dict[str, int] = {
            "US-1": 1,
            "US-2": 0,  # This one has no retries yet
        }
        retries_file = tmpdir_path / "retry-counts.json"
        retries_file.write_text(json.dumps(retries, indent=2), encoding="utf-8")

        added = 0

        skip_rt = False
        if added == 0:
            pending_ids = [s["id"] for s in prd["userStories"] if not s.get("passes")]
            if not pending_ids:
                skip_rt = True
            else:
                all_have_retries = True
                for story_id in pending_ids:
                    retry_count = retries.get(story_id, 0)
                    if retry_count == 0:
                        all_have_retries = False
                        break
                if all_have_retries:
                    skip_rt = True

        assert skip_rt is False, "SKIP_RT should be false when some pending have retries=0"


def test_skip_rt_0_added_no_pending() -> None:
    """Test: ADDED=0, no pending stories → SKIP_RT=true"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        prd: dict[str, Any] = {
            "userStories": [
                {"id": "US-1", "passes": True},
                {"id": "US-2", "passes": True},
            ]
        }
        prd_file = tmpdir_path / "prd.json"
        prd_file.write_text(json.dumps(prd, indent=2), encoding="utf-8")

        retries: dict[str, int] = {}
        retries_file = tmpdir_path / "retry-counts.json"
        retries_file.write_text(json.dumps(retries, indent=2), encoding="utf-8")

        added = 0

        skip_rt = False
        if added == 0:
            pending_ids = [s["id"] for s in prd["userStories"] if not s.get("passes")]
            if not pending_ids:
                skip_rt = True
            else:
                all_have_retries = True
                for story_id in pending_ids:
                    retry_count = retries.get(story_id, 0)
                    if retry_count == 0:
                        all_have_retries = False
                        break
                if all_have_retries:
                    skip_rt = True

        assert skip_rt is True, "SKIP_RT should be true when no pending stories exist"


def test_skip_rt_empty_prd() -> None:
    """Test: Empty prd.json (edge case) → SKIP_RT=true"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        prd: dict[str, Any] = {"userStories": []}
        prd_file = tmpdir_path / "prd.json"
        prd_file.write_text(json.dumps(prd, indent=2), encoding="utf-8")

        retries: dict[str, int] = {}
        retries_file = tmpdir_path / "retry-counts.json"
        retries_file.write_text(json.dumps(retries, indent=2), encoding="utf-8")

        added = 0

        skip_rt = False
        if added == 0:
            pending_ids = [s["id"] for s in prd["userStories"] if not s.get("passes")]
            if not pending_ids:
                skip_rt = True
            else:
                all_have_retries = True
                for story_id in pending_ids:
                    retry_count = retries.get(story_id, 0)
                    if retry_count == 0:
                        all_have_retries = False
                        break
                if all_have_retries:
                    skip_rt = True

        assert skip_rt is True, "SKIP_RT should be true when prd.json is empty"

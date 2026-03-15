#!/usr/bin/env python3
"""
SPIRAL — Work-Offering Queue for idle worker prevention.

When SPIRAL_WORK_STEALING=true, finished workers can claim uncompleted
stories from the shared queue instead of sitting idle.

Queue file: .spiral/workers/_work_queue.json (file-locked for concurrency).
"""
import json
import os
import sys
import time
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from constants import PRIORITY_RANK
from spiral_io import atomic_write_json, configure_utf8_stdout, safe_read_json

configure_utf8_stdout()


class WorkQueue:
    def __init__(self, queue_path: str, lock_timeout: float = 10.0) -> None:
        self.queue_path = queue_path
        self.lock_path = queue_path + ".lock"
        self.lock_timeout = lock_timeout

    def _acquire_lock(self) -> int:
        """Acquire exclusive file lock. Returns fd."""
        os.makedirs(os.path.dirname(os.path.abspath(self.lock_path)), exist_ok=True)
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR)
        deadline = time.monotonic() + self.lock_timeout
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return fd
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(fd)
                    raise TimeoutError(
                        f"Could not acquire work queue lock within {self.lock_timeout}s"
                    )
                time.sleep(0.05)

    def _release_lock(self, fd: int) -> None:
        """Release file lock."""
        if sys.platform == "win32":
            import msvcrt
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def _read_queue(self) -> list[dict[str, Any]]:
        data = safe_read_json(self.queue_path, {"stories": []})
        if isinstance(data, dict):
            result: list[dict[str, Any]] = data.get("stories", [])
            return result
        return []

    def _write_queue(self, stories: list[dict[str, Any]]) -> None:
        atomic_write_json(self.queue_path, {"stories": stories})

    def offer(self, stories: list[dict[str, Any]], source_worker: int) -> int:
        """Add pending stories to queue. Returns count added."""
        if not stories:
            return 0
        fd = self._acquire_lock()
        try:
            queue = self._read_queue()
            existing_ids = {s.get("id") for s in queue}
            added = 0
            for story in stories:
                sid = story.get("id", "")
                if sid and sid not in existing_ids:
                    story["_offered_by"] = source_worker
                    queue.append(story)
                    existing_ids.add(sid)
                    added += 1
            if added:
                self._write_queue(queue)
            return added
        finally:
            self._release_lock(fd)

    def claim(self, worker_id: int, main_prd_path: str) -> dict[str, Any] | None:
        """Claim highest-priority story with satisfied deps. Returns None if empty."""
        fd = self._acquire_lock()
        try:
            queue = self._read_queue()
            if not queue:
                return None

            # Load main PRD to check which stories are already passed
            passed_ids: set[str] = set()
            if os.path.isfile(main_prd_path):
                prd = safe_read_json(main_prd_path, {})
                for s in prd.get("userStories", []):
                    if s.get("passes"):
                        passed_ids.add(s.get("id", ""))

            # Sort by priority (highest first)
            queue.sort(key=lambda s: PRIORITY_RANK.get(s.get("priority", "medium"), 2))

            claimed = None
            remaining = []
            for story in queue:
                sid = story.get("id", "")
                # Skip already-passed stories
                if sid in passed_ids:
                    continue
                # Check dependency satisfaction
                deps = story.get("dependencies", [])
                deps_met = all(d in passed_ids for d in deps)
                if claimed is None and deps_met:
                    story["_claimed_by"] = worker_id
                    claimed = story
                else:
                    remaining.append(story)

            self._write_queue(remaining)
            return claimed
        finally:
            self._release_lock(fd)

    def inject(self, prd_path: str, story: dict[str, Any]) -> None:
        """Add claimed story to worker's prd.json as pending."""
        if not os.path.isfile(prd_path):
            return
        with open(prd_path, encoding="utf-8") as f:
            prd = json.load(f)
        # Don't add if already present
        existing_ids = {s.get("id") for s in prd.get("userStories", [])}
        if story.get("id") in existing_ids:
            return
        story["passes"] = False
        story.pop("_offered_by", None)
        story.pop("_claimed_by", None)
        prd.setdefault("userStories", []).append(story)
        atomic_write_json(prd_path, prd)

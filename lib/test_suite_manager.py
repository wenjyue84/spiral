#!/usr/bin/env python3
"""
SPIRAL Test Suite Manager

Manages persistent test suites in .spiral/test-suites/. Each suite type
(smoke, regression, performance, security, uat) accumulates tests across
iterations. Tests are created from passed stories, reused each iteration,
and marked obsolete when the source story is decomposed or removed.

Directory layout:
  .spiral/test-suites/
    smoke/
      suite.json          — test entries for this suite type
      results/
        iter-001.json     — results snapshot from iteration 1
        iter-002.json     — ...
    regression/
      suite.json
      results/
    performance/
      suite.json
      results/
    security/
      suite.json
      results/
    uat/
      scenarios.json      — UAT scenario descriptions (run by subagent)
      results/

Usage (CLI):
  python test_suite_manager.py run smoke --iteration 3
  python test_suite_manager.py add-from-prd --prd prd.json --suite-types smoke,regression
  python test_suite_manager.py status
  python test_suite_manager.py mark-obsolete --story-id US-042
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SUITE_TYPES = ["smoke", "regression", "performance", "security", "uat"]

# Keywords that classify a story into suite types
_SUITE_KW: dict[str, set[str]] = {
    "smoke": {
        "create", "read", "update", "delete", "list", "save", "load",
        "start", "stop", "connect", "basic", "core", "main",
    },
    "regression": {
        "fix", "bug", "patch", "correct", "revert", "restore", "broken",
    },
    "performance": {
        "performance", "speed", "cache", "slow", "optimize", "bulk",
        "batch", "concurrent", "parallel", "load", "scale", "throughput",
    },
    "security": {
        "auth", "login", "token", "permission", "role", "password",
        "secret", "encrypt", "jwt", "session", "oauth", "csrf", "xss",
    },
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write(data: Any, path: str) -> None:
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


class TestSuiteManager:
    def __init__(self, suite_root: str):
        self.suite_root = suite_root
        os.makedirs(suite_root, exist_ok=True)

    def _suite_dir(self, suite_type: str) -> str:
        d = os.path.join(self.suite_root, suite_type)
        os.makedirs(os.path.join(d, "results"), exist_ok=True)
        return d

    def _suite_path(self, suite_type: str) -> str:
        filename = "scenarios.json" if suite_type == "uat" else "suite.json"
        return os.path.join(self._suite_dir(suite_type), filename)

    def load(self, suite_type: str) -> dict[str, Any]:
        path = self._suite_path(suite_type)
        if not os.path.exists(path):
            return {"type": suite_type, "version": 1, "tests": []}
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"type": suite_type, "version": 1, "tests": []}

    def save(self, suite_type: str, suite: dict[str, Any]) -> None:
        _atomic_write(suite, self._suite_path(suite_type))

    def add_test(self, suite_type: str, test: dict[str, Any]) -> bool:
        """Add a test to suite. Returns True if newly added (not a duplicate)."""
        suite = self.load(suite_type)
        existing_titles = {t.get("title", "").lower() for t in suite.get("tests", [])}
        title = test.get("title", "").strip()
        if not title or title.lower() in existing_titles:
            return False
        test.setdefault("id", f"{suite_type}-{len(suite.get('tests', [])) + 1:03d}")
        test.setdefault("created_ts", _now())
        test.setdefault("last_run_ts", "")
        test.setdefault("last_result", "pending")
        test.setdefault("obsolete", False)
        test.setdefault("run_count", 0)
        suite.setdefault("tests", []).append(test)
        self.save(suite_type, suite)
        return True

    def mark_obsolete(self, suite_type: str, story_id: str) -> int:
        """Mark all tests created from story_id as obsolete. Returns count marked."""
        suite = self.load(suite_type)
        count = 0
        for test in suite.get("tests", []):
            if test.get("from_story") == story_id and not test.get("obsolete"):
                test["obsolete"] = True
                count += 1
        if count:
            self.save(suite_type, suite)
        return count

    def run_suite(
        self, suite_type: str, iteration: int, repo_root: str = ".", timeout: int = 120
    ) -> dict[str, Any]:
        """Run all non-obsolete tests with a runnable command. Returns summary dict."""
        suite = self.load(suite_type)
        active = [t for t in suite.get("tests", []) if not t.get("obsolete")]

        if not active:
            return {
                "suite_type": suite_type,
                "total": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
            }

        passed = failed = skipped = 0
        results: list[dict] = []

        for test in active:
            cmd = test.get("command", "").strip()
            if not cmd:
                skipped += 1
                results.append({**test, "result": "skip", "reason": "no command defined"})
                continue

            try:
                proc = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=repo_root,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                )
                result = "pass" if proc.returncode == 0 else "fail"
                (passed if result == "pass" else failed).__class__  # dummy
                if result == "pass":
                    passed += 1
                else:
                    failed += 1
                results.append(
                    {
                        **test,
                        "result": result,
                        "stdout": (proc.stdout or "")[-500:],
                        "stderr": (proc.stderr or "")[-200:],
                    }
                )
            except subprocess.TimeoutExpired:
                failed += 1
                results.append({**test, "result": "timeout"})
            except Exception as exc:
                skipped += 1
                results.append({**test, "result": "error", "reason": str(exc)})

            # Update last-run metadata in suite
            for t in suite.get("tests", []):
                if t.get("id") == test.get("id"):
                    t["last_run_ts"] = _now()
                    t["last_result"] = results[-1]["result"]
                    t["run_count"] = t.get("run_count", 0) + 1

        self.save(suite_type, suite)

        # Persist iteration results
        results_dir = os.path.join(self._suite_dir(suite_type), "results")
        results_path = os.path.join(results_dir, f"iter-{iteration:03d}.json")
        _atomic_write(
            {
                "iteration": iteration,
                "suite_type": suite_type,
                "timestamp": _now(),
                "summary": {
                    "total": len(active),
                    "passed": passed,
                    "failed": failed,
                    "skipped": skipped,
                },
                "tests": results,
            },
            results_path,
        )

        return {
            "suite_type": suite_type,
            "total": len(active),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        }

    def generate_entry_from_story(
        self, story: dict[str, Any], suite_type: str
    ) -> dict[str, Any] | None:
        """Generate a test suite entry from a passed story. Returns None if not applicable."""
        sid = story.get("id", "")
        title = story.get("title", "")
        if not sid or not title:
            return None

        # Determine if story is relevant for this suite type
        story_tokens = _tokens(f"{title} {story.get('description', '')}")
        suite_kw = _SUITE_KW.get(suite_type, set())

        # smoke: always add (every feature needs a smoke test)
        # others: only if keywords match OR complexity is large
        if suite_type != "smoke":
            complexity = story.get("estimatedComplexity", "medium")
            if not (story_tokens & suite_kw) and complexity != "large":
                return None

        return {
            "title": f"[{suite_type}] {title}",
            "description": f"Auto-generated {suite_type} test from {sid}",
            "from_story": sid,
            "command": "",  # placeholder — Ralph fills this in via test-story
            "priority": "high" if suite_type in ("security", "regression") else "medium",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="SPIRAL persistent test suite manager")
    sub = parser.add_subparsers(dest="cmd")

    # run: execute a suite
    p_run = sub.add_parser("run", help="Run a named test suite")
    p_run.add_argument("suite_type", choices=SUITE_TYPES)
    p_run.add_argument("--suite-root", default=".spiral/test-suites")
    p_run.add_argument("--iteration", type=int, default=1)
    p_run.add_argument("--repo-root", default=".")
    p_run.add_argument("--timeout", type=int, default=120, help="Timeout per test (seconds)")

    # add-from-prd: populate suites from prd.json passed stories
    p_add = sub.add_parser("add-from-prd", help="Add tests from passed stories in prd.json")
    p_add.add_argument("--prd", default="prd.json")
    p_add.add_argument("--suite-root", default=".spiral/test-suites")
    p_add.add_argument(
        "--suite-types",
        default="smoke,regression",
        help="Comma-separated suite types to populate (default: smoke,regression)",
    )

    # status: print suite summary
    p_status = sub.add_parser("status", help="Print test suite status")
    p_status.add_argument("--suite-root", default=".spiral/test-suites")

    # mark-obsolete: mark tests from a story as obsolete
    p_obs = sub.add_parser("mark-obsolete", help="Mark tests from a story as obsolete")
    p_obs.add_argument("--story-id", required=True)
    p_obs.add_argument("--suite-root", default=".spiral/test-suites")

    args = parser.parse_args()

    if args.cmd == "run":
        mgr = TestSuiteManager(args.suite_root)
        summary = mgr.run_suite(
            args.suite_type, args.iteration, args.repo_root, args.timeout
        )
        status = f"{summary['passed']}/{summary['total']} pass"
        if summary["failed"]:
            status += f", {summary['failed']} FAILED"
        if summary["skipped"]:
            status += f", {summary['skipped']} skipped"
        print(f"  [test-suite:{args.suite_type}] {status}")
        return 0 if summary["failed"] == 0 else 1

    elif args.cmd == "add-from-prd":
        if not os.path.isfile(args.prd):
            print(f"  [test-suite] WARNING: {args.prd} not found", file=sys.stderr)
            return 0
        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)

        mgr = TestSuiteManager(args.suite_root)
        suite_types = [s.strip() for s in args.suite_types.split(",") if s.strip()]
        passed_stories = [
            s
            for s in prd.get("userStories", [])
            if s.get("passes") and s.get("_source") not in ("test-story", "test-fix")
        ]

        total_added = 0
        for story in passed_stories:
            for st in suite_types:
                entry = mgr.generate_entry_from_story(story, st)
                if entry and mgr.add_test(st, entry):
                    total_added += 1

        print(f"  [test-suite] Added {total_added} test(s) across: {', '.join(suite_types)}")
        return 0

    elif args.cmd == "status":
        mgr = TestSuiteManager(args.suite_root)
        for st in SUITE_TYPES:
            suite = mgr.load(st)
            tests = suite.get("tests", [])
            active = sum(1 for t in tests if not t.get("obsolete"))
            last_results = {t.get("last_result") for t in tests if t.get("last_result")}
            status = f"{active} active"
            if "fail" in last_results:
                status += " [has failures]"
            elif "pass" in last_results:
                status += " [all passing]"
            print(f"  [test-suite:{st}] {status} ({len(tests)} total)")
        return 0

    elif args.cmd == "mark-obsolete":
        mgr = TestSuiteManager(args.suite_root)
        total = 0
        for st in SUITE_TYPES:
            total += mgr.mark_obsolete(st, args.story_id)
        print(f"  [test-suite] Marked {total} test(s) obsolete for story {args.story_id}")
        return 0

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

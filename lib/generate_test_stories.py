#!/usr/bin/env python3
"""
SPIRAL Source 5 — Test Story Generator

Analyzes recently passed implementation stories and generates test story
candidates tagged _source="test-story".

Test story types generated:
  integration  — for complex (large) or multi-file stories (>=3 files touched)
  e2e          — for user-facing stories (UI/flow keywords detected)
  security     — for auth/permission-sensitive stories
  performance  — for performance-sensitive stories
  regression   — fallback for medium+ complexity stories not matching above

These candidates flow into Phase S → M and Ralph implements them by writing
actual test code. This replaces hard-coded SPIRAL_VALIDATE_CMD / SPIRAL_E2E_TEST_CMD
layer invocations in Phase V.

Output: .spiral/_test_story_candidates.json {"stories": [...]}
"""
import argparse
import json
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, configure_utf8_stdout
configure_utf8_stdout()

# Keywords that indicate a user-facing feature → E2E test
_E2E_KW = {
    "user", "page", "view", "display", "form", "login", "signup",
    "dashboard", "screen", "interface", "button", "modal", "navigate",
    "flow", "checkout", "profile", "settings", "menu", "table", "list",
    "search", "filter", "sort", "upload", "download", "export", "import",
}

# Keywords that indicate security-sensitive logic → security test
_SECURITY_KW = {
    "auth", "login", "token", "permission", "role", "password", "secret",
    "encrypt", "jwt", "session", "access", "oauth", "csrf", "xss",
    "injection", "sanitize", "validate", "authoriz", "authenticat",
}

# Keywords that indicate performance concern → performance test
_PERF_KW = {
    "performance", "speed", "cache", "latency", "slow", "optimiz",
    "bulk", "batch", "concurrent", "parallel", "load", "scale", "throughput",
    "paginate", "index", "query",
}

_COMPLEXITY_RANK = {"small": 0, "medium": 1, "large": 2}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def classify_story(story: dict) -> list[str]:
    """Return list of test types warranted by this story (may be empty)."""
    title = story.get("title", "")
    description = story.get("description", "")
    text = f"{title} {description}".lower()
    text_tokens = _tokens(text)
    files_touched = story.get("filesTouch", [])
    complexity = story.get("estimatedComplexity", "medium")
    complexity_rank = _COMPLEXITY_RANK.get(complexity, 1)

    types: list[str] = []

    # Integration: large complexity OR touches 3+ files
    if complexity == "large" or len(files_touched) >= 3:
        types.append("integration")

    # E2E: user-facing keywords
    if text_tokens & _E2E_KW:
        types.append("e2e")

    # Security: auth/permission keywords
    if text_tokens & _SECURITY_KW:
        types.append("security")

    # Performance: perf-sensitive keywords
    if text_tokens & _PERF_KW:
        types.append("performance")

    # Regression: medium+ complexity fallback if no other type assigned
    if complexity_rank >= 1 and not types:
        types.append("regression")

    return types


def _make_test_story(source: dict, test_type: str) -> dict:
    """Build a test story entry from an implementation story."""
    sid = source.get("id", "")
    title = source.get("title", "")
    description = source.get("description", "")

    configs: dict[str, dict] = {
        "integration": {
            "title": f"[Integration Test] {title}",
            "description": (
                f"Write integration tests for the feature implemented in {sid}. "
                f"Story description: {description}"
            ),
            "criteria": [
                f"Integration tests exist covering the core behaviour of {sid}",
                "Tests cover the happy path and at least one error/edge case",
                "Tests run without requiring external services or manual setup",
            ],
            "priority": "high",
        },
        "e2e": {
            "title": f"[E2E Test] {title}",
            "description": (
                f"Write end-to-end user flow test for the feature in {sid}. "
                f"Story description: {description}"
            ),
            "criteria": [
                f"E2E test covers the user flow introduced by {sid}",
                "Test navigates to relevant page(s) and asserts on visible state",
                "Test passes in headless browser (Playwright/Cypress/similar)",
            ],
            "priority": "medium",
        },
        "security": {
            "title": f"[Security Test] {title}",
            "description": (
                f"Write security tests for auth/permission logic in {sid}. "
                f"Story description: {description}"
            ),
            "criteria": [
                f"Security test covers access control introduced by {sid}",
                "Test verifies unauthorized access is blocked (401/403 responses)",
                "No sensitive data (tokens, passwords) leaked in error responses",
            ],
            "priority": "high",
        },
        "performance": {
            "title": f"[Performance Test] {title}",
            "description": (
                f"Write performance benchmark for the operation in {sid}. "
                f"Story description: {description}"
            ),
            "criteria": [
                f"Performance test measures key metrics for {sid}",
                "Baseline captured and acceptable threshold defined",
                "Test fails if response time degrades more than 20% from baseline",
            ],
            "priority": "medium",
        },
        "regression": {
            "title": f"[Regression Test] {title}",
            "description": (
                f"Write regression test to guard against future breakage of {sid}. "
                f"Story description: {description}"
            ),
            "criteria": [
                f"Regression test covers core observable behaviour of {sid}",
                f"Test would reliably fail if the {sid} feature were removed or broken",
            ],
            "priority": "medium",
        },
    }

    cfg = configs.get(test_type, configs["regression"])
    return {
        "title": cfg["title"][:100],
        "description": cfg["description"],
        "acceptanceCriteria": cfg["criteria"],
        "priority": cfg["priority"],
        "dependencies": [sid],
        "_source": "test-story",
        "_testType": test_type,
        "_forStoryId": sid,
        "tags": [test_type, "auto-generated"],
    }


def _existing_test_story_keys(prd: dict) -> set[tuple[str, str]]:
    """Return set of (forStoryId, testType) already in prd.json."""
    keys: set[tuple[str, str]] = set()
    for story in prd.get("userStories", []):
        if story.get("_source") in ("test-story", "test-fix") or story.get("isTestFix"):
            for_id = story.get("_forStoryId", "")
            test_type = story.get("_testType", "")
            if for_id and test_type:
                keys.add((for_id, test_type))
    return keys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Source 5: Generate test story candidates from passed implementation stories"
    )
    parser.add_argument("--prd", default="prd.json")
    parser.add_argument(
        "--out",
        default=".spiral/_test_story_candidates.json",
        help="Output path for test story candidates",
    )
    parser.add_argument(
        "--min-complexity",
        default="medium",
        choices=["small", "medium", "large"],
        help="Minimum story complexity to trigger test story generation (default: medium)",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.prd):
        print(f"  [test-stories] WARNING: {args.prd} not found", file=sys.stderr)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"stories": []}, f)
        return 0

    with open(args.prd, encoding="utf-8") as f:
        prd = json.load(f)

    min_rank = _COMPLEXITY_RANK.get(args.min_complexity, 1)
    existing_keys = _existing_test_story_keys(prd)

    # Candidate source stories: passed implementation stories meeting min complexity
    candidates_source = [
        s for s in prd.get("userStories", [])
        if s.get("passes") is True
        and s.get("_source") not in ("test-story", "test-fix")
        and not s.get("isTestFix")
        and _COMPLEXITY_RANK.get(s.get("estimatedComplexity", "medium"), 1) >= min_rank
    ]

    candidates: list[dict] = []
    seen_keys: set[tuple[str, str]] = set(existing_keys)

    for story in candidates_source:
        for test_type in classify_story(story):
            key = (story.get("id", ""), test_type)
            if key not in seen_keys:
                candidate = _make_test_story(story, test_type)
                candidates.append(candidate)
                seen_keys.add(key)  # prevent duplicates within this run

    atomic_write_json(args.out, {"stories": candidates})

    if candidates:
        by_type: dict[str, int] = {}
        for c in candidates:
            t = c.get("_testType", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        parts = ", ".join(f"{k}={v}" for k, v in by_type.items())
        print(f"  [test-stories] Generated {len(candidates)} test story candidate(s): {parts}")
    else:
        print("  [test-stories] No new test story candidates — all passed stories already covered")

    return 0


if __name__ == "__main__":
    sys.exit(main())

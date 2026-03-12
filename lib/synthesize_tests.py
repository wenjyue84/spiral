#!/usr/bin/env python3
"""
SPIRAL Phase T — Test Synthesis
Reads the N most recent test-reports/*/report.json files, unions all FAIL/ERROR
results (deduplicated by test ID), and turns them into story candidates.
Deduplicates against existing prd.json titles using 60% word-overlap heuristic.
Optionally enriches stories with the failing test method source code.
Writes {"stories": [...]} to --output path.
stdlib only — no extra dependencies.
"""
import argparse
import json
import os
import re
import sys
from typing import Any

# Force UTF-8 stdout — prevents UnicodeEncodeError on Windows cp1252 terminals
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# Default priority mapping for test categories.
# Projects can override by using different category names in their test reports.
# Unknown categories fall back to "medium".
PRIORITY_MAP = {
    "smoke": "critical",
    "security": "critical",
    "regression": "high",
    "api_contract": "high",
    "integration": "high",
    "unit": "medium",
    "edge_cases": "medium",
    "performance": "low",
}


def find_recent_reports(reports_dir: str, n: int = 3) -> list[str]:
    """Return up to n most recent report.json paths, sorted newest-first."""
    if not os.path.isdir(reports_dir):
        return []
    subdirs = sorted(
        [d for d in os.listdir(reports_dir) if os.path.isdir(os.path.join(reports_dir, d))],
        reverse=True,
    )
    paths = []
    for d in subdirs:
        candidate = os.path.join(reports_dir, d, "report.json")
        if os.path.isfile(candidate):
            paths.append(candidate)
            if len(paths) >= n:
                break
    return paths


def normalize(text: str) -> set[str]:
    """Lowercase alphanum words only."""
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def overlap_ratio(a: str, b: str) -> float:
    """Fraction of words in `a` that also appear in `b`."""
    wa = normalize(a)
    wb = normalize(b)
    if not wa:
        return 0.0
    return len(wa & wb) / len(wa)


def is_duplicate(candidate_title: str, existing_titles: list[str], threshold: float = 0.6) -> bool:
    for existing in existing_titles:
        if overlap_ratio(candidate_title, existing) >= threshold:
            return True
        if overlap_ratio(existing, candidate_title) >= threshold:
            return True
    return False


def parse_test_id(test_id: str) -> tuple[str, str, str]:
    """
    Parse 'tests.unit.module.test_file.TestClass.test_method'
    → (category_hint, class_name, method_name)
    """
    parts = test_id.split(".")
    method = parts[-1] if parts else test_id
    class_name = parts[-2] if len(parts) >= 2 else ""
    category_hint = ".".join(parts[1:3]) if len(parts) >= 3 else "unit"
    return category_hint, class_name, method


def _extract_method_source(filepath: str, method_name: str, max_lines: int = 20) -> str | None:
    """Extract up to max_lines of a test method's source from a Python file."""
    try:
        with open(filepath, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return None

    # Find the method definition
    start: int | None = None
    base_indent: int = 0
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(f"def {method_name}(") or stripped.startswith(
            f"async def {method_name}("
        ):
            start = i
            base_indent = len(line) - len(stripped)
            break

    if start is None:
        return None

    # Collect lines until indentation returns to or below the def line level
    result = [lines[start].rstrip()]
    for line in lines[start + 1 : start + max_lines + 1]:
        if line.strip() == "":
            result.append("")
            continue
        cur_indent = len(line) - len(line.lstrip())
        if line.strip() and cur_indent <= base_indent:
            break
        result.append(line.rstrip())

    return "\n".join(result)


def extract_test_source(test_id: str, repo_root: str) -> str | None:
    """
    Locate the test file for a given test_id and return the failing method source.
    Tries progressively shorter module paths to find the .py file.

    Example: 'tests.unit.module.test_file.TestClass.test_method'
             → file:   tests/unit/module/test_file.py
             → method: test_basic
    """
    parts = test_id.split(".")
    for end in range(len(parts), 0, -1):
        candidate = os.path.join(repo_root, *parts[:end]) + ".py"
        if os.path.isfile(candidate):
            remainder = parts[end:]
            method_name = remainder[-1] if remainder else None
            if not method_name or not method_name.startswith("test"):
                return None
            return _extract_method_source(candidate, method_name)
    return None


def aggregate_failures(report_paths: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Load multiple reports, union all FAIL/ERROR results, deduplicate by test ID.
    Returns (failures_list, report_names_used).
    """
    seen_ids: set[str] = set()
    failures: list[dict[str, Any]] = []
    report_names: list[str] = []

    for path in report_paths:
        try:
            with open(path, encoding="utf-8") as f:
                report = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue

        report_dir = os.path.basename(os.path.dirname(path))
        all_results = report.get("all_results", [])
        batch = [r for r in all_results if r.get("status") in ("FAIL", "ERROR")]
        new_count = 0
        for r in batch:
            tid = r.get("id", "")
            if tid and tid not in seen_ids:
                seen_ids.add(tid)
                failures.append(r)
                new_count += 1

        report_names.append(report_dir)
        print(
            f"[synthesize] Report {report_dir}: "
            f"{new_count} new failures (running pool: {len(failures)})"
        )

    return failures, report_names


def result_to_story(
    result: dict[str, Any], repo_root: str | None = None
) -> dict[str, Any]:
    """Convert a FAIL/ERROR test result to a story candidate."""
    test_id = result.get("id", "")
    name = result.get("name", test_id)
    description = result.get("description", "")
    category = result.get("category", "unit")
    error = result.get("error") or {}

    category_hint, class_name, method_name = parse_test_id(test_id)

    priority = PRIORITY_MAP.get(
        category, PRIORITY_MAP.get(category_hint.split(":")[0], "medium")
    )

    readable = method_name.lstrip("test_").replace("_", " ").strip()
    if class_name:
        cls_readable = class_name.replace("Test", "").replace("_", " ").strip()
        title = f"Fix failing test: {cls_readable} — {readable}"
    else:
        title = f"Fix failing test: {readable}"

    ac = [f"Test `{test_id}` passes without error."]
    if error.get("message"):
        msg = error["message"][:200].replace("\n", " ")
        ac.append(f"Root cause resolved: {msg}")

    tech_notes = [f"Test category: {category}", f"Test ID: {test_id}"]
    if error.get("type"):
        tech_notes.append(f"Error type: {error['type']}")
    if description:
        tech_notes.append(f"Test description: {description}")

    # Enhancement 8: enrich with failing test source so ralph doesn't hunt for it
    if repo_root:
        source = extract_test_source(test_id, repo_root)
        if source:
            tech_notes.append(f"Failing test source:\n```python\n{source}\n```")

    return {
        "title": title,
        "priority": priority,
        "description": (
            f"Automated test `{name}` is failing with status {result.get('status', 'FAIL')}. "
            f"This indicates a regression or missing implementation in the {category} suite. "
            f"{description}"
        ).strip(),
        "acceptanceCriteria": ac,
        "technicalNotes": tech_notes,
        "dependencies": [],
        "estimatedComplexity": "small",
        "_source": f"test-synthesis:{test_id}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SPIRAL test synthesis")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json")
    parser.add_argument("--reports-dir", default="test-reports", help="Test reports directory")
    parser.add_argument(
        "--output",
        default=".spiral/_test_stories_output.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--recent-reports",
        type=int,
        default=3,
        metavar="N",
        help="Aggregate failures from last N reports (default: 3)",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repo root for test source extraction (default: current dir)",
    )
    parser.add_argument("--focus", default="", help="Focus theme — tag matching stories for priority boost")
    args = parser.parse_args()

    if args.focus:
        print(f"[synthesize] Focus active: \"{args.focus}\" — matching stories tagged for priority boost")

    # Load existing titles from prd.json for dedup
    existing_titles: list[str] = []
    if os.path.isfile(args.prd):
        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)
        existing_titles = [s.get("title", "") for s in prd.get("userStories", [])]

    # Find recent reports
    report_paths = find_recent_reports(args.reports_dir, args.recent_reports)
    if not report_paths:
        print(f"[synthesize] WARNING: No test reports found in {args.reports_dir}/")
        output = {"stories": []}
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2)
        print(f"[synthesize] Wrote 0 stories → {args.output}")
        return 0

    # Aggregate failures from all recent reports (dedup by test ID)
    failures, report_names = aggregate_failures(report_paths)
    print(
        f"[synthesize] Aggregated {len(failures)} unique failures "
        f"from {len(report_names)} report(s)"
    )

    repo_root = os.path.abspath(args.repo_root)

    # Convert to story candidates, dedup against prd + each other
    candidates = []
    seen_titles: list[str] = list(existing_titles)

    for result in failures:
        story = result_to_story(result, repo_root=repo_root)
        title = story["title"]
        if is_duplicate(title, seen_titles):
            print(f"[synthesize] Skipping duplicate: {title}")
            continue
        candidates.append(story)
        seen_titles.append(title)

        if args.focus:
            focus_lower = args.focus.lower()
            searchable = (story.get("title", "") + " " + story.get("description", "")).lower()
            story["_focusRelevant"] = focus_lower in searchable

    print(f"[synthesize] Generated {len(candidates)} new story candidates from test failures")

    output = {"stories": candidates}
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    tmp = args.output + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    os.replace(tmp, args.output)
    print(f"[synthesize] Wrote {len(candidates)} stories → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

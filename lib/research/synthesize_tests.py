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
import tempfile
from typing import Any

try:
    import yaml as _yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from flaky_detector import is_flaky_test

try:
    from test_classifier import classify_test_failure as _classify_failure

    _HAS_CLASSIFIER = True
except ImportError:
    _HAS_CLASSIFIER = False
from prd_schema import validate_prd
from spiral_io import atomic_write_json, configure_utf8_stdout
from test_failure_clustering import cluster_failures

configure_utf8_stdout()


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
        if stripped.startswith(f"def {method_name}(") or stripped.startswith(f"async def {method_name}("):
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


def aggregate_failures(
    report_paths: list[str], exclude_flaky: bool = True, spiral_home: str | None = None, record_results: bool = True
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """
    Load multiple reports, union all FAIL/ERROR results, deduplicate by test ID.
    Optionally exclude flaky tests (AC1: tests failing <50% are excluded).
    Record all test results to flaky detector for history tracking.
    Returns (failures_list, report_names_used, excluded_flaky_tests).
    """
    seen_ids: set[str] = set()
    failures: list[dict[str, Any]] = []
    report_names: list[str] = []
    excluded_flaky: list[str] = []

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
        skipped_flaky = 0

        # Record all test results (pass/fail) to flaky detector for history tracking
        if record_results:
            for r in all_results:
                tid = r.get("id", "")
                if tid:
                    passed = r.get("status") not in ("FAIL", "ERROR")
                    from flaky_detector import record_test_result

                    record_test_result(tid, passed, spiral_home=spiral_home)

        for r in batch:
            tid = r.get("id", "")
            if tid and tid not in seen_ids:
                # Check if test is flaky and should be excluded
                if exclude_flaky and is_flaky_test(tid, spiral_home=spiral_home):
                    excluded_flaky.append(tid)
                    skipped_flaky += 1
                else:
                    seen_ids.add(tid)
                    failures.append(r)
                    new_count += 1

        report_names.append(report_dir)
        status_msg = f"[synthesize] Report {report_dir}: {new_count} new failures"
        if skipped_flaky:
            status_msg += f" ({skipped_flaky} flaky tests excluded)"
        status_msg += f" (running pool: {len(failures)})"
        print(status_msg)

    return failures, report_names, excluded_flaky


def result_to_story(result: dict[str, Any], repo_root: str | None = None) -> dict[str, Any]:
    """Convert a FAIL/ERROR test result to a story candidate."""
    test_id = result.get("id", "")
    name = result.get("name", test_id)
    description = result.get("description", "")
    category = result.get("category", "unit")
    error = result.get("error") or {}

    category_hint, class_name, method_name = parse_test_id(test_id)

    priority = PRIORITY_MAP.get(category, PRIORITY_MAP.get(category_hint.split(":")[0], "medium"))

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

    story: dict[str, Any] = {
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

    # US-1337: Enrich stories with root cause classification and remediation hint
    if _HAS_CLASSIFIER:
        snippet = error.get("message") or error.get("type") or ""
        if snippet:
            classification = _classify_failure(snippet)
            story["_rootCause"] = classification["type"]
            story["_hint"] = classification["hint"]

    return story


def _filter_none(d: dict[str, Any]) -> dict[str, Any]:
    """Remove keys with None values for compact YAML output (AC4: omit null fields)."""
    return {k: v for k, v in d.items() if v is not None}


def _atomic_write_yaml(path: str, data: dict[str, Any]) -> None:
    """Write *data* as YAML to *path* atomically using a temp file + rename.

    Uses block scalars (|) for multiline strings (AC4) to reduce token cost
    compared to JSON-escaped newlines.
    """
    if not HAS_YAML:
        raise ImportError("pyyaml is required for YAML output — install with: uv add pyyaml")

    # Custom representer: use block scalar style (|) for multiline strings
    def _block_str(dumper: _yaml.Dumper, data: str) -> _yaml.Node:
        if "\n" in data:
            return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
        return dumper.represent_scalar("tag:yaml.org,2002:str", data)

    dumper = _yaml.Dumper
    dumper.add_representer(str, _block_str)

    parent = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            _yaml.dump(data, fh, Dumper=dumper, default_flow_style=False, sort_keys=False, allow_unicode=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


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
    parser.add_argument(
        "--output-format",
        choices=["json", "yaml"],
        default="json",
        help="Output format: 'json' (default, backward compat) or 'yaml' (compact, ~40%% fewer tokens)",
    )
    args = parser.parse_args()

    if args.focus:
        print(f'[synthesize] Focus active: "{args.focus}" — matching stories tagged for priority boost')

    # Load existing titles from prd.json for dedup
    existing_titles: list[str] = []
    if os.path.isfile(args.prd):
        with open(args.prd, encoding="utf-8") as f:
            prd = json.load(f)
        errors = validate_prd(prd)
        if errors:
            print("[schema] PRD validation failed:", file=sys.stderr)
            for e in errors:
                print(f"  - {e}", file=sys.stderr)
            return 1
        existing_titles = [s.get("title", "") for s in prd.get("userStories", [])]

    # Find recent reports
    report_paths = find_recent_reports(args.reports_dir, args.recent_reports)
    if not report_paths:
        print(f"[synthesize] WARNING: No test reports found in {args.reports_dir}/")
        empty_output: dict[str, Any] = {"stories": []}
        if args.output_format == "yaml":
            _atomic_write_yaml(args.output, empty_output)
        else:
            atomic_write_json(args.output, empty_output)
        print(f"[synthesize] Wrote 0 stories → {args.output}")
        return 0

    # Aggregate failures from all recent reports (dedup by test ID, exclude flaky tests)
    failures, report_names, excluded_flaky = aggregate_failures(
        report_paths, exclude_flaky=True, spiral_home=os.environ.get("SPIRAL_HOME")
    )
    print(f"[synthesize] Aggregated {len(failures)} unique failures from {len(report_names)} report(s)")
    if excluded_flaky:
        print(f"[synthesize] Excluded {len(excluded_flaky)} flaky tests from story generation")
        for test_id in excluded_flaky[:5]:
            print(f"  - {test_id}")
        if len(excluded_flaky) > 5:
            print(f"  ... and {len(excluded_flaky) - 5} more")

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

    # Apply test failure clustering: group 3+ failures from same source into 1 root-cause story
    clustered_candidates = cluster_failures(candidates)
    if len(clustered_candidates) < len(candidates):
        print(f"[synthesize] Clustered failures: {len(candidates)} -> {len(clustered_candidates)} stories")

    if args.output_format == "yaml":
        # AC4: omit null fields and use block scalars for compact YAML
        filtered_candidates = [_filter_none(s) for s in clustered_candidates]
        _atomic_write_yaml(args.output, {"stories": filtered_candidates})
        print(f"[synthesize] Wrote {len(clustered_candidates)} stories (YAML) → {args.output}")
    else:
        atomic_write_json(args.output, {"stories": clustered_candidates})
        print(f"[synthesize] Wrote {len(clustered_candidates)} stories → {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

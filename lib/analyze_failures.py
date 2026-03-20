#!/usr/bin/env python3
"""
lib/analyze_failures.py — Story Failure Root-Cause Analyzer (US-547).

Parses Phase V validation logs and retry metadata to categorize failures into
root causes and recommend SPIRAL configuration tuning.

Categories:
  scope_exceeded       — Token-limit overruns ("exceeds.*max_tokens", "context_length")
  api_rate_limit       — Rate-limit / quota errors ("rate_limit", "429", "quota")
  type_error           — Type/import/syntax errors ("TypeError", "ImportError", "SyntaxError")
  validation_timeout   — Timeout during validation ("timed out", "TimeoutError", "timeout")
  model_capability_gap — Model couldn't understand the task ("model.*not.*capable", "unsupported")
  unknown              — No pattern matched

Usage:
    from lib.analyze_failures import FailureAnalyzer
    fa = FailureAnalyzer(repo_root=Path("."))
    result = fa.analyze()
    print(result)  # dict with by_category, by_phase, recommendation
"""

from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

# ── Pattern registry ──────────────────────────────────────────────────────────

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("scope_exceeded", re.compile(r"exceeds.*max_tokens|max_tokens.*exceed|context.?length|token.?limit|context.?window", re.IGNORECASE)),
    ("api_rate_limit", re.compile(r"rate.?limit|ratelimit|429|quota.?exceeded|too.?many.?requests", re.IGNORECASE)),
    ("type_error", re.compile(r"\bTypeError\b|\bImportError\b|\bSyntaxError\b|\bAttributeError\b|\bNameError\b", re.IGNORECASE)),
    ("validation_timeout", re.compile(r"timed?\s+out|TimeoutError|timeout.*expired|deadline.?exceeded", re.IGNORECASE)),
    ("model_capability_gap", re.compile(r"model.{0,20}not.{0,20}capable|unsupported.{0,20}model|capability.{0,20}gap|beyond.{0,20}model", re.IGNORECASE)),
]


def categorize_text(text: str) -> str:
    """Return the first matching failure category for *text*, or 'unknown'."""
    for category, pattern in _PATTERNS:
        if pattern.search(text):
            return category
    return "unknown"


# ── FailureAnalyzer ────────────────────────────────────────────────────────────


class FailureAnalyzer:
    """Reads .spiral/logs/ and results.tsv, categorizes retry failures."""

    def __init__(
        self,
        repo_root: Path | None = None,
        logs_dir: Path | None = None,
        results_tsv: Path | None = None,
    ) -> None:
        self.repo_root = repo_root or Path(".")
        self.logs_dir = logs_dir or (self.repo_root / ".spiral" / "logs")
        self.results_tsv = results_tsv or (self.repo_root / "results.tsv")

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_results(self) -> list[dict[str, str]]:
        """Load results.tsv rows, returning [] if missing or malformed."""
        if not self.results_tsv.exists():
            return []
        rows: list[dict[str, str]] = []
        try:
            with open(self.results_tsv, encoding="utf-8", errors="replace") as f:
                reader = csv.DictReader(f, delimiter="\t")
                for row in reader:
                    rows.append(dict(row))
        except OSError:
            pass
        return rows

    def _load_log_texts(self) -> list[tuple[str, str]]:
        """Load all phase-i-*.log files from .spiral/logs/.

        Returns list of (filename, content) tuples.
        """
        pairs: list[tuple[str, str]] = []
        if not self.logs_dir.is_dir():
            return pairs
        for log_file in sorted(self.logs_dir.glob("phase-i-*.log")):
            try:
                text = log_file.read_text(encoding="utf-8", errors="replace")
                pairs.append((log_file.name, text))
            except OSError:
                pass
        return pairs

    # ── Analysis ─────────────────────────────────────────────────────────────

    def _analyze_results_rows(
        self,
        rows: list[dict[str, str]],
    ) -> tuple[dict[str, int], dict[str, int]]:
        """Categorize failed/retried rows from results.tsv.

        Returns (by_category, by_phase) counts.
        by_phase keys are derived from the 'status' column (e.g. 'fail', 'retry').
        """
        by_category: dict[str, int] = {}
        by_phase: dict[str, int] = {}

        for row in rows:
            status = (row.get("status") or "").lower()
            # Only analyse failed / retried rows
            if status not in ("fail", "retry", "failed", "error", "skip"):
                continue

            # Use pre-existing failure_root_cause if present, else re-derive
            root_cause = (row.get("failure_root_cause") or "").strip()
            if not root_cause:
                # Derive from available text fields
                candidate_text = " ".join([
                    row.get("story_title", ""),
                    row.get("status", ""),
                ])
                root_cause = categorize_text(candidate_text)

            by_category[root_cause] = by_category.get(root_cause, 0) + 1

            # Phase derived from status column
            phase_key = status or "unknown"
            by_phase[phase_key] = by_phase.get(phase_key, 0) + 1

        return by_category, by_phase

    def _analyze_logs(
        self,
        log_pairs: list[tuple[str, str]],
        by_category: dict[str, int],
        by_phase: dict[str, int],
    ) -> None:
        """Augment by_category / by_phase from phase-i-*.log content (in-place)."""
        for filename, text in log_pairs:
            # Extract root cause lines emitted by Ralph's failure logger
            for line in text.splitlines():
                if "FAILURE_ROOT_CAUSE:" in line:
                    # Line format: "FAILURE_ROOT_CAUSE: <category>"
                    parts = line.split("FAILURE_ROOT_CAUSE:", 1)
                    if len(parts) == 2:
                        cat = parts[1].strip().lower().replace(" ", "_")
                        by_category[cat] = by_category.get(cat, 0) + 1
                        by_phase["phase_i"] = by_phase.get("phase_i", 0) + 1
                        continue

                # Fall back to pattern matching on log lines
                if re.search(r"error|exception|fail|timeout|limit", line, re.IGNORECASE):
                    cat = categorize_text(line)
                    if cat != "unknown":
                        by_category[cat] = by_category.get(cat, 0) + 1
                        by_phase["phase_i"] = by_phase.get("phase_i", 0) + 1

    def _build_recommendation(self, by_category: dict[str, int]) -> str:
        """Generate a tuning recommendation from category distribution."""
        total = sum(by_category.values())
        if total == 0:
            return "No failures found — nothing to tune."

        recommendations: list[str] = []

        scope = by_category.get("scope_exceeded", 0)
        if scope / total > 0.30:
            recommendations.append(
                f"scope_exceeded accounts for {scope}/{total} ({scope*100//total}%) failures. "
                "Lower SPIRAL_DECOMPOSE_THRESHOLD to split large stories earlier."
            )

        rate = by_category.get("api_rate_limit", 0)
        if rate / total > 0.20:
            recommendations.append(
                f"api_rate_limit accounts for {rate}/{total} ({rate*100//total}%) failures. "
                "Consider increasing SPIRAL_RETRY_DELAY or adding jitter between API calls."
            )

        timeout = by_category.get("validation_timeout", 0)
        if timeout / total > 0.20:
            recommendations.append(
                f"validation_timeout accounts for {timeout}/{total} ({timeout*100//total}%) failures. "
                "Increase SPIRAL_VALIDATE_TIMEOUT or simplify SPIRAL_VALIDATE_CMD."
            )

        cap_gap = by_category.get("model_capability_gap", 0)
        if cap_gap / total > 0.20:
            recommendations.append(
                f"model_capability_gap accounts for {cap_gap}/{total} ({cap_gap*100//total}%) failures. "
                "Use SPIRAL_MODEL_ROUTING=auto to escalate to a more capable model on retry."
            )

        if not recommendations:
            dominant = max(by_category, key=lambda k: by_category[k])
            recommendations.append(
                f"Dominant failure category: {dominant} ({by_category[dominant]}/{total}). "
                "No single category exceeds 30% threshold — distribution looks healthy."
            )

        return " | ".join(recommendations)

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(self) -> dict[str, Any]:
        """Run full analysis and return structured report dict.

        Returns::

            {
                "by_category": {"scope_exceeded": 3, "api_rate_limit": 1, ...},
                "by_phase": {"fail": 2, "retry": 2, "phase_i": 4, ...},
                "recommendation": "Lower SPIRAL_DECOMPOSE_THRESHOLD ...",
            }
        """
        rows = self._load_results()
        log_pairs = self._load_log_texts()

        by_category: dict[str, int] = {}
        by_phase: dict[str, int] = {}

        self._analyze_results_rows(rows)
        bc, bp = self._analyze_results_rows(rows)
        by_category.update(bc)
        by_phase.update(bp)

        self._analyze_logs(log_pairs, by_category, by_phase)

        recommendation = self._build_recommendation(by_category)

        return {
            "by_category": by_category,
            "by_phase": by_phase,
            "recommendation": recommendation,
        }


# ── CLI entry point ───────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> None:
    """Standalone CLI: python -m lib.analyze_failures [--format json]."""
    import argparse

    parser = argparse.ArgumentParser(description="Analyze SPIRAL failure root causes")
    parser.add_argument("--format", choices=["json", "text"], default="json", help="Output format")
    parser.add_argument("--repo", default=".", metavar="PATH", help="Repo root (default: .)")
    args = parser.parse_args(argv)

    fa = FailureAnalyzer(repo_root=Path(args.repo))
    result = fa.analyze()

    if args.format == "json":
        print(json.dumps(result, indent=2))
    else:
        print(f"By category: {result['by_category']}")
        print(f"By phase:    {result['by_phase']}")
        print(f"Recommendation: {result['recommendation']}")


if __name__ == "__main__":
    main(sys.argv[1:])

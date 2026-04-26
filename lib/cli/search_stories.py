"""lib/cli/search_stories.py — CLI driver for `spiral search <query>`.

Calls search_across_projects() and renders results in table, json, or csv format.

Usage:
    python lib/cli/search_stories.py <prd_path> <query> [--format table|json|csv]
                                                         [--project NAME]
                                                         [--min-score N]
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from typing import Any

from lib.federated_search import search_across_projects


class FederatedStorySearch:
    """Run federated story search and format results."""

    def __init__(self, query: str, prd_path: str, project: str | None = None, min_score: int = 30) -> None:
        self.query = query
        self.prd_path = prd_path
        self.project = project
        self.min_score = min_score
        self._results: list[dict[str, Any]] | None = None

    def run(self) -> list[dict[str, Any]]:
        """Execute the search and cache results."""
        self._results = search_across_projects(
            self.query,
            self.prd_path,
            min_score=self.min_score,
            project_filter=self.project,
        )
        return self._results

    @property
    def results(self) -> list[dict[str, Any]]:
        if self._results is None:
            return self.run()
        return self._results

    def format_table(self) -> str:
        """Render results as a fixed-width table."""
        rows = self.results
        if not rows:
            return f"No stories matched '{self.query}'"
        id_w = max(len(r["story_id"]) for r in rows)
        id_w = max(id_w, 8)
        proj_w = max(len(r["project"]) for r in rows)
        proj_w = max(proj_w, 7)
        title_w = min(max(len(r["title"]) for r in rows), 60)
        title_w = max(title_w, 5)

        header = f"{'ID':<{id_w}}  {'PROJECT':<{proj_w}}  {'TITLE':<{title_w}}  SCORE"
        sep = "-" * len(header)
        lines = [header, sep]
        for r in rows:
            title = r["title"]
            if len(title) > title_w:
                title = title[: title_w - 1] + "…"
            lines.append(f"{r['story_id']:<{id_w}}  {r['project']:<{proj_w}}  {title:<{title_w}}  {r['score']}")
        return "\n".join(lines)

    def format_json(self) -> str:
        """Render results as JSON array."""
        return json.dumps(self.results, indent=2)

    def format_csv(self) -> str:
        """Render results as CSV with header."""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=["story_id", "project", "title", "score", "description"])
        writer.writeheader()
        writer.writerows(self.results)
        return buf.getvalue()

    def render(self, fmt: str) -> str:
        """Render results in the specified format."""
        if fmt == "json":
            return self.format_json()
        if fmt == "csv":
            return self.format_csv()
        return self.format_table()


def main(argv: list[str] | None = None) -> int:
    """Entry point for CLI invocation."""
    parser = argparse.ArgumentParser(description="Search stories in prd.json")
    parser.add_argument("prd_path", help="Path to prd.json")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--format", choices=["table", "json", "csv"], default="table")
    parser.add_argument("--project", default=None, help="Filter by sub-project name")
    parser.add_argument("--min-score", type=int, default=30, dest="min_score")
    args = parser.parse_args(argv)

    searcher = FederatedStorySearch(
        query=args.query,
        prd_path=args.prd_path,
        project=args.project,
        min_score=args.min_score,
    )
    print(searcher.render(args.format))
    return 0


if __name__ == "__main__":
    sys.exit(main())

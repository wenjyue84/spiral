#!/usr/bin/env python3
"""
SPIRAL — import_github.py
Import user stories from GitHub Issues via the GraphQL API.

Usage (library):
    from import_github import import_github_issues
    added, skipped = import_github_issues(
        repo="owner/repo",
        label="spiral",
        prd_path="prd.json",
        token="ghp_...",
        dry_run=False,
    )

Usage (CLI):
    python lib/import_github.py --repo owner/repo --label spiral [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, configure_utf8_stdout
configure_utf8_stdout()

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# Map GitHub label names to SPIRAL priority values.
_PRIORITY_LABELS: dict[str, str] = {
    "priority:critical": "critical",
    "priority:high": "high",
    "priority:medium": "medium",
    "priority:low": "low",
}

_ISSUES_QUERY = """
query($owner: String!, $repo: String!, $label: String!, $cursor: String) {
  repository(owner: $owner, name: $repo) {
    issues(states: [OPEN], labels: [$label], first: 100, after: $cursor) {
      pageInfo {
        hasNextPage
        endCursor
      }
      nodes {
        number
        title
        body
        milestone {
          title
        }
        labels(first: 20) {
          nodes {
            name
          }
        }
      }
    }
  }
}
"""


# ── GraphQL fetching ──────────────────────────────────────────────────────────


def _graphql_request(query: str, variables: dict[str, Any], token: str) -> dict[str, Any]:
    """Execute a single GraphQL request and return the parsed JSON response."""
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        GITHUB_GRAPHQL_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "spiral-import-github/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitHub API error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error reaching GitHub: {exc.reason}") from exc


def fetch_issues(owner: str, repo: str, label: str, token: str) -> Iterator[dict[str, Any]]:
    """Yield all open GitHub issues matching *label* with cursor-based pagination."""
    cursor: str | None = None
    while True:
        variables: dict[str, Any] = {
            "owner": owner,
            "repo": repo,
            "label": label,
            "cursor": cursor,
        }
        data = _graphql_request(_ISSUES_QUERY, variables, token)

        errors = data.get("errors")
        if errors:
            msgs = "; ".join(e.get("message", str(e)) for e in errors)
            raise RuntimeError(f"GitHub GraphQL errors: {msgs}")

        repo_data = data.get("data", {}).get("repository")
        if repo_data is None:
            raise RuntimeError(
                f"Repository {owner}/{repo!r} not found or inaccessible. "
                "Check that GITHUB_TOKEN has repo read permission."
            )

        issues_page = repo_data["issues"]
        for node in issues_page["nodes"]:
            yield node

        page_info = issues_page["pageInfo"]
        if not page_info["hasNextPage"]:
            break
        cursor = page_info["endCursor"]


# ── Mapping ───────────────────────────────────────────────────────────────────


def _extract_priority(issue: dict[str, Any]) -> str:
    """Determine SPIRAL priority from GitHub labels, then milestone title."""
    label_names: list[str] = [n["name"] for n in issue.get("labels", {}).get("nodes", [])]

    # Check explicit priority labels first (most specific wins).
    for label_name in label_names:
        if label_name in _PRIORITY_LABELS:
            return _PRIORITY_LABELS[label_name]

    # Fall back to milestone title.
    milestone = issue.get("milestone")
    if milestone:
        title_lower = (milestone.get("title") or "").lower()
        if "critical" in title_lower:
            return "critical"
        if "high" in title_lower:
            return "high"
        if "low" in title_lower:
            return "low"

    return "medium"


def _next_story_id(existing_stories: list[dict[str, Any]]) -> str:
    """Return the next available US-NNN id not already present in *existing_stories*."""
    pattern = re.compile(r"^US-(\d+)$")
    max_num = 0
    for story in existing_stories:
        m = pattern.match(story.get("id", ""))
        if m:
            max_num = max(max_num, int(m.group(1)))
    return f"US-{max_num + 1}"


def map_issue_to_story(
    issue: dict[str, Any],
    existing_titles: set[str],
    next_id: str,
) -> dict[str, Any] | None:
    """
    Convert a GitHub issue node to a SPIRAL story dict.

    Returns *None* if the issue title already exists in *existing_titles*
    (duplicate detection).
    """
    title: str = (issue.get("title") or "").strip()
    if not title:
        return None

    if title in existing_titles:
        return None

    body: str = (issue.get("body") or "").strip()
    priority: str = _extract_priority(issue)

    return {
        "id": next_id,
        "title": title,
        "priority": priority,
        "description": body,
        "acceptanceCriteria": [],
        "technicalNotes": [],
        "dependencies": [],
        "estimatedComplexity": "medium",
        "passes": False,
        "_source": "github-import",
        "_githubIssueNumber": issue.get("number"),
    }


# ── I/O helpers ───────────────────────────────────────────────────────────────


def _load_prd(prd_path: str) -> dict[str, Any]:
    path = Path(prd_path)
    if not path.exists():
        raise FileNotFoundError(f"prd.json not found at {prd_path!r}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ── Public API ────────────────────────────────────────────────────────────────


def import_github_issues(
    *,
    repo: str,
    label: str,
    prd_path: str,
    token: str,
    dry_run: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Fetch GitHub issues from *repo* tagged with *label* and append them to *prd_path*.

    Parameters
    ----------
    repo:     ``owner/repo`` string, e.g. ``"anthropics/claude-code"``
    label:    GitHub label to filter by, e.g. ``"spiral"``
    prd_path: Path to prd.json
    token:    GitHub personal access token (or fine-grained token with Issues read)
    dry_run:  If True, compute changes but do NOT write prd.json

    Returns
    -------
    (added_stories, skipped_titles)
        added_stories   — list of story dicts that were (or would be) added
        skipped_titles  — list of issue titles that were skipped as duplicates
    """
    if "/" not in repo:
        raise ValueError(f"repo must be in 'owner/repo' format, got: {repo!r}")

    owner, repo_name = repo.split("/", 1)

    prd_data = _load_prd(prd_path)
    existing_stories: list[dict[str, Any]] = prd_data.get("userStories", [])
    existing_titles: set[str] = {(s.get("title") or "").strip() for s in existing_stories}

    added: list[dict[str, Any]] = []
    skipped: list[str] = []

    # We need a running counter for IDs since multiple issues may be added.
    # Build a temporary extended list to compute sequential IDs.
    working_stories = list(existing_stories)

    for issue in fetch_issues(owner, repo_name, label, token):
        next_id = _next_story_id(working_stories + added)
        story = map_issue_to_story(issue, existing_titles, next_id)
        if story is None:
            title = (issue.get("title") or "").strip()
            if title:
                skipped.append(title)
        else:
            added.append(story)
            existing_titles.add(story["title"])

    if not dry_run and added:
        prd_data["userStories"] = existing_stories + added
        atomic_write_json(prd_path, prd_data)

    return added, skipped


# ── CLI ───────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="spiral import-github",
        description="Import GitHub Issues as SPIRAL user stories into prd.json.",
    )
    parser.add_argument(
        "--repo",
        required=True,
        metavar="OWNER/REPO",
        help="GitHub repository in owner/repo format",
    )
    parser.add_argument(
        "--label",
        default="spiral",
        metavar="LABEL",
        help="GitHub label to filter issues by (default: spiral)",
    )
    parser.add_argument(
        "--prd",
        default="prd.json",
        metavar="PATH",
        help="Path to prd.json (default: prd.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print stories that would be added without modifying prd.json",
    )

    args = parser.parse_args(argv)

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print(
            "ERROR: GITHUB_TOKEN environment variable is not set.\n"
            "Create a GitHub token at https://github.com/settings/tokens "
            "and export it as GITHUB_TOKEN.",
            file=sys.stderr,
        )
        return 1

    try:
        added, skipped = import_github_issues(
            repo=args.repo,
            label=args.label,
            prd_path=args.prd,
            token=token,
            dry_run=args.dry_run,
        )
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    for title in skipped:
        print(f"[skip] Duplicate: {title!r}")

    if args.dry_run:
        if added:
            print(f"\n[dry-run] Would add {len(added)} story/stories:")
            for story in added:
                print(f"  {story['id']} ({story['priority']}) — {story['title']}")
        else:
            print("[dry-run] No new stories to add.")
        return 0

    if added:
        print(f"Added {len(added)} story/stories to prd.json:")
        for story in added:
            print(f"  {story['id']} ({story['priority']}) — {story['title']}")
    else:
        print("No new stories to add.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
SPIRAL — import_jira.py
Import user stories from Jira issues via the Jira REST API v3.

Usage (library):
    from import_jira import import_jira_issues
    added, skipped = import_jira_issues(
        host="mycompany.atlassian.net",
        project="ENG",
        jql="labels=spiral AND status=Backlog",
        prd_path="prd.json",
        email="user@example.com",
        api_token="mytoken",
        dry_run=False,
    )

Usage (CLI):
    python lib/import_jira.py --host mycompany.atlassian.net --project ENG \
        --jql "labels=spiral AND status=Backlog" [--dry-run]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import atomic_write_json, configure_utf8_stdout

configure_utf8_stdout()

_PAGE_SIZE = 50  # Jira default max per page

# Map Jira priority names to SPIRAL priority values.
_PRIORITY_MAP: dict[str, str] = {
    "highest": "critical",
    "high": "high",
    "medium": "medium",
    "low": "low",
    "lowest": "low",
}


# ── REST API helpers ──────────────────────────────────────────────────────────


def _build_auth_header(email: str, api_token: str) -> str:
    """Return a Basic auth header value for Jira Cloud authentication."""
    credentials = f"{email}:{api_token}"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _jira_get(url: str, auth_header: str) -> dict[str, Any]:
    """Execute a GET request to the Jira REST API and return parsed JSON."""
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "spiral-import-jira/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Jira API error {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Network error reaching Jira: {exc.reason}") from exc


def fetch_issues(
    host: str,
    jql: str,
    email: str,
    api_token: str,
) -> Iterator[dict[str, Any]]:
    """Yield all Jira issues matching *jql* with maxResults/startAt pagination."""
    auth_header = _build_auth_header(email, api_token)
    start_at = 0

    while True:
        params = urllib.parse.urlencode(
            {
                "jql": jql,
                "maxResults": _PAGE_SIZE,
                "startAt": start_at,
                "fields": "summary,description,priority,issuetype",
            }
        )
        url = f"https://{host}/rest/api/3/search?{params}"
        data = _jira_get(url, auth_header)

        issues: list[dict[str, Any]] = data.get("issues", [])
        for issue in issues:
            yield issue

        total: int = int(data.get("total", 0))
        start_at += len(issues)

        # Stop when we've received all issues or the page was empty.
        if not issues or start_at >= total:
            break


# ── Mapping ───────────────────────────────────────────────────────────────────


def _extract_priority(issue: dict[str, Any]) -> str:
    """Return SPIRAL priority string from a Jira issue's priority field."""
    fields: dict[str, Any] = issue.get("fields") or {}
    priority_obj = fields.get("priority") or {}
    raw_name: str = (priority_obj.get("name") or "").strip().lower()
    return _PRIORITY_MAP.get(raw_name, "medium")


def _extract_description(issue: dict[str, Any]) -> str:
    """Extract plain-text description from Jira ADF or plain string body."""
    fields: dict[str, Any] = issue.get("fields") or {}
    desc = fields.get("description")
    if not desc:
        return ""
    # Jira REST API v3 returns description as Atlassian Document Format (ADF).
    # Walk the ADF tree to collect text nodes.
    if isinstance(desc, dict):
        return _adf_to_text(desc).strip()
    # Fallback: plain string (e.g. in mocked tests)
    return str(desc).strip()


def _adf_to_text(node: dict[str, Any]) -> str:
    """Recursively extract plain text from an ADF node."""
    if node.get("type") == "text":
        return node.get("text", "")
    parts: list[str] = []
    for child in node.get("content") or []:
        parts.append(_adf_to_text(child))
    # Join block-level nodes with newlines, inline nodes with empty string.
    separator = "\n" if node.get("type") in ("doc", "paragraph", "bulletList", "listItem") else ""
    return separator.join(parts)


def _next_story_id(existing_stories: list[dict[str, Any]]) -> str:
    """Return the next available US-NNN id not already in *existing_stories*."""
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
    Convert a Jira issue dict to a SPIRAL story dict.

    Returns *None* if the issue summary already exists in *existing_titles*
    (duplicate detection).
    """
    fields: dict[str, Any] = issue.get("fields") or {}
    title: str = (fields.get("summary") or "").strip()
    if not title:
        return None

    if title in existing_titles:
        return None

    jira_key: str = (issue.get("key") or "").strip()
    description: str = _extract_description(issue)
    priority: str = _extract_priority(issue)

    return {
        "id": next_id,
        "title": title,
        "priority": priority,
        "description": description,
        "acceptanceCriteria": [],
        "technicalNotes": [],
        "dependencies": [],
        "estimatedComplexity": "medium",
        "passes": False,
        "_source": "jira-import",
        "_jiraKey": jira_key,
    }


# ── I/O helpers ───────────────────────────────────────────────────────────────


def _load_prd(prd_path: str) -> dict[str, Any]:
    path = Path(prd_path)
    if not path.exists():
        raise FileNotFoundError(f"prd.json not found at {prd_path!r}")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ── Public API ────────────────────────────────────────────────────────────────


def import_jira_issues(
    *,
    host: str,
    project: str | None = None,
    jql: str | None = None,
    prd_path: str,
    email: str,
    api_token: str,
    dry_run: bool = False,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Fetch Jira issues and append them as stories to *prd_path*.

    Parameters
    ----------
    host:       Jira Cloud hostname, e.g. ``"mycompany.atlassian.net"``
    project:    Jira project key (used to build a default JQL filter)
    jql:        Raw JQL override.  If provided, *project* is ignored for filtering
                but is still accepted for CLI symmetry.
    prd_path:   Path to prd.json
    email:      Jira account email (JIRA_USER_EMAIL)
    api_token:  Jira API token (JIRA_API_TOKEN)
    dry_run:    If True, compute changes but do NOT write prd.json

    Returns
    -------
    (added_stories, skipped_titles)
        added_stories   — list of story dicts that were (or would be) added
        skipped_titles  — list of issue titles that were skipped as duplicates
    """
    if not host:
        raise ValueError("host must not be empty (e.g. 'mycompany.atlassian.net')")

    # Build effective JQL: explicit --jql takes priority; fall back to project filter.
    if jql:
        effective_jql = jql
    elif project:
        effective_jql = f"project = {project} ORDER BY created DESC"
    else:
        raise ValueError("Either --jql or --project must be provided")

    prd_data = _load_prd(prd_path)
    existing_stories: list[dict[str, Any]] = prd_data.get("userStories", [])
    existing_titles: set[str] = {(s.get("title") or "").strip() for s in existing_stories}

    added: list[dict[str, Any]] = []
    skipped: list[str] = []

    for issue in fetch_issues(host, effective_jql, email, api_token):
        next_id = _next_story_id(existing_stories + added)
        story = map_issue_to_story(issue, existing_titles, next_id)
        if story is None:
            fields: dict[str, Any] = issue.get("fields") or {}
            title = (fields.get("summary") or "").strip()
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
        prog="spiral import-jira",
        description="Import Jira issues as SPIRAL user stories into prd.json.",
    )
    parser.add_argument(
        "--host",
        required=True,
        metavar="HOST",
        help="Jira Cloud hostname (e.g. mycompany.atlassian.net)",
    )
    parser.add_argument(
        "--project",
        default=None,
        metavar="PROJECT",
        help="Jira project key used to build a default JQL filter (e.g. ENG)",
    )
    parser.add_argument(
        "--jql",
        default=None,
        metavar="JQL",
        help="Raw JQL query to select issues (overrides --project filter)",
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

    email = os.environ.get("JIRA_USER_EMAIL", "").strip()
    api_token = os.environ.get("JIRA_API_TOKEN", "").strip()

    if not email or not api_token:
        missing = []
        if not email:
            missing.append("JIRA_USER_EMAIL")
        if not api_token:
            missing.append("JIRA_API_TOKEN")
        print(
            f"ERROR: Missing environment variable(s): {', '.join(missing)}\n"
            "Set JIRA_USER_EMAIL and JIRA_API_TOKEN before running this command.\n"
            "Generate an API token at https://id.atlassian.com/manage-profile/security/api-tokens",
            file=sys.stderr,
        )
        return 1

    if not args.jql and not args.project:
        print(
            "ERROR: Provide either --project PROJECT or --jql 'JQL query'",
            file=sys.stderr,
        )
        return 1

    try:
        added, skipped = import_jira_issues(
            host=args.host,
            project=args.project,
            jql=args.jql,
            prd_path=args.prd,
            email=email,
            api_token=api_token,
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
                key = story.get("_jiraKey", "")
                key_str = f" [{key}]" if key else ""
                print(f"  {story['id']} ({story['priority']}){key_str} — {story['title']}")
        else:
            print("[dry-run] No new stories to add.")
        return 0

    if added:
        print(f"Added {len(added)} story/stories to prd.json:")
        for story in added:
            key = story.get("_jiraKey", "")
            key_str = f" [{key}]" if key else ""
            print(f"  {story['id']} ({story['priority']}){key_str} — {story['title']}")
    else:
        print("No new stories to add.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

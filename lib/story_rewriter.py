#!/usr/bin/env python3
"""
lib/story_rewriter.py — Phase S story rewriting for constitution compliance.

When a story fails constitution check, optionally rewrite title and acceptance
criteria to comply with constitution rules while preserving original intent.
Max 1 rewrite attempt per story (checked via _rewritten flag).
"""

import json
from typing import Any


def rewrite_story(story: dict[str, Any], api_key: str) -> dict[str, Any] | None:
    """
    Rewrite a story's title and acceptance criteria for constitution compliance.

    Args:
        story: Story dict with id, title, description, acceptanceCriteria
        api_key: Anthropic API key

    Returns:
        Rewritten story with _rewritten=true flag, or None if rewrite failed.
    """
    if story.get("_rewritten"):
        return None  # Already rewritten once

    title = story.get("title", "").strip()
    description = story.get("description", "").strip()
    acs = story.get("acceptanceCriteria", [])
    if isinstance(acs, list):
        acs_text = "\n".join(str(ac) for ac in acs)
    else:
        acs_text = str(acs)

    prompt = f"""You are a PRD expert. A story failed constitution compliance checks.
Rewrite ONLY the title and acceptance criteria to comply with these rules:
- Use concrete, measurable language
- Avoid vague terms ("improve", "better", "optimize")
- Each AC must be testable and have clear pass/fail criteria
- NEVER change the original intent or description

Original Story:
ID: {story.get("id", "unknown")}
Title: {title}
Description: {description}
Acceptance Criteria:
{acs_text}

Return ONLY valid JSON (no markdown, no explanation):
{{
  "title": "rewritten title",
  "acceptanceCriteria": ["AC 1", "AC 2", "AC 3"]
}}"""

    try:
        import requests

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-3-5-haiku-20241022",
                "max_tokens": 500,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=30,
        )
        if response.status_code != 200:
            return None

        result = response.json()
        if "content" not in result or not result["content"]:
            return None

        text = result["content"][0].get("text", "").strip()
        # Extract JSON from response (handle markdown code blocks)
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        text = text.strip()

        rewritten = json.loads(text)
        updated_story = {**story}
        if "title" in rewritten:
            updated_story["title"] = rewritten["title"]
        if "acceptanceCriteria" in rewritten:
            updated_story["acceptanceCriteria"] = rewritten["acceptanceCriteria"]
        updated_story["_rewritten"] = True
        return updated_story
    except Exception:
        return None

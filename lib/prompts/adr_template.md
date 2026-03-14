Generate an Architecture Decision Record (ADR) in MADR (Markdown Architectural Decision Records) format.

## Story Context

**Story ID:** {story_id}
**Title:** {story_title}

**Description:** {story_description}

**Acceptance Criteria:**
{acceptance_criteria}

## Code Changes

```diff
{git_diff}
```

## Instructions

Based on the story specification and the git diff above, write a concise ADR that captures:
1. **Context**: What problem or need drove this change?
2. **Decision**: What design choices were made, and why?
3. **Consequences**: What are the trade-offs (positive and negative)?

Format EXACTLY as follows (MADR format — no preamble, just the markdown):

# {story_id} — {story_title}

## Status

Accepted

## Context

<2-4 sentences: the problem, constraint, or requirement that motivated this change>

## Decision

<3-6 sentences or bullets describing the specific design choices and implementation approach, derived from the diff>

## Consequences

**Positive:**
- <benefit 1>
- <benefit 2>

**Negative / Trade-offs:**
- <trade-off or "None identified" if truly none>

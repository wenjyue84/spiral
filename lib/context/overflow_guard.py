"""Context window overflow guard for Phase X.

Estimates total prompt tokens before sending to Claude CLI.
If estimated tokens exceed SPIRAL_CONTEXT_BUDGET (default 180000),
applies progressive trimming: diff depth reduction -> file chunking -> comment stripping.
"""

import json
import os


def estimate_tokens(text: str) -> int:
    """Estimate token count using tiktoken or 4-char heuristic.

    Args:
        text: String to estimate token count for

    Returns:
        Estimated token count
    """
    try:
        import tiktoken

        enc = tiktoken.encoding_for_model("gpt-4")
        return len(enc.encode(text))
    except ImportError:
        # Fallback to 4 chars per token heuristic
        return len(text) // 4


def _strip_comments(text: str) -> str:
    """Strip verbose comments from code blocks.

    Args:
        text: Code block text

    Returns:
        Code with verbose comments removed
    """
    lines = text.split("\n")
    result = []

    for line in lines:
        # Skip lines that are pure comments (>80% of line is comment)
        stripped = line.lstrip()
        if stripped.startswith(("#", "//", "--", "/*")):
            if len(stripped) > len(line) * 0.2:  # Skip if mostly comment
                continue
        result.append(line)

    return "\n".join(result)


def _chunk_to_modified_sections(diff_block: str, context_lines: int = 50) -> str:
    """Extract modified sections from diff with boundary context.

    Args:
        diff_block: Unified diff text
        context_lines: Lines of context around each modification

    Returns:
        Trimmed diff with only modified sections + boundary context
    """
    lines = diff_block.split("\n")
    result = []
    in_hunk = False

    for line in lines:
        if line.startswith("@@"):
            in_hunk = True
            # Include hunk header
            result.append(line)
        elif in_hunk:
            # Keep diff lines, stop after context_lines of context past last change
            if line.startswith(("+", "-")):
                result.append(line)
            elif line.startswith(" "):
                result.append(line)
            elif line.startswith("\\"):
                result.append(line)

    return "\n".join(result)


def _trim_large_files(story: dict) -> dict:
    """Trim large file contents to relevant chunks.

    Args:
        story: Story dictionary with potential large file contents

    Returns:
        Story with trimmed file contents
    """
    trimmed_story = json.loads(json.dumps(story))

    # Trim description if it's very long (>2000 chars)
    if "description" in trimmed_story:
        desc = trimmed_story["description"]
        if len(desc) > 2000:
            # Keep first 1500 chars + ellipsis
            trimmed_story["description"] = desc[:1500] + "..."

    # Trim acceptance criteria if there are many
    if "acceptanceCriteria" in trimmed_story:
        criteria = trimmed_story["acceptanceCriteria"]
        if isinstance(criteria, list) and len(criteria) > 10:
            trimmed_story["acceptanceCriteria"] = criteria[:10] + ["[... {} more criteria]".format(len(criteria) - 10)]

    return trimmed_story


def trim_progressive(
    story: dict,
    max_tokens: int,
    ralph_prompt: str = "",
    ralph_prompt_tokens: int = 0,
) -> tuple[dict, bool]:
    """Apply progressive trimming to story context.

    Args:
        story: Story dictionary to trim
        max_tokens: Maximum allowed tokens
        ralph_prompt: Ralph CLAUDE.md prompt text (for estimation)
        ralph_prompt_tokens: Pre-calculated ralph prompt tokens

    Returns:
        Tuple of (trimmed_story, was_trimmed)
    """
    # Estimate current token count
    story_str = json.dumps(story)
    ralph_tokens = ralph_prompt_tokens or estimate_tokens(ralph_prompt)
    current_tokens = estimate_tokens(story_str) + ralph_tokens

    if current_tokens <= max_tokens:
        return story, False

    trimmed_story = json.loads(json.dumps(story))

    # Stage 1: Reduce diff depth in technicalNotes or injected content
    if "technicalNotes" in trimmed_story:
        notes = trimmed_story["technicalNotes"]
        if isinstance(notes, list):
            # Remove verbose/long technical notes
            trimmed_story["technicalNotes"] = [n for n in notes if isinstance(n, str) and len(n) < 200]

    # Stage 2: Trim large files and descriptions
    trimmed_story = _trim_large_files(trimmed_story)

    # Stage 3: Strip verbose comments from code blocks in description
    if "description" in trimmed_story:
        trimmed_story["description"] = _strip_comments(trimmed_story["description"])

    # Check if we're under budget now
    trimmed_str = json.dumps(trimmed_story)
    new_tokens = estimate_tokens(trimmed_str) + ralph_tokens

    if new_tokens <= max_tokens:
        trimmed_story["_context_trimmed"] = True
        return trimmed_story, True

    # If still over, remove optional fields
    optional_fields = [
        "technicalNotes",
        "filesTouch",
        "dependencies",
        "estimatedComplexity",
    ]
    for field in optional_fields:
        if field in trimmed_story:
            del trimmed_story[field]

    trimmed_str = json.dumps(trimmed_story)
    new_tokens = estimate_tokens(trimmed_str) + ralph_tokens

    if new_tokens > max_tokens:
        # As a last resort, keep only critical fields
        critical_only = {
            "id": trimmed_story.get("id"),
            "title": trimmed_story.get("title"),
            "description": trimmed_story.get("description", "")[:500],
            "acceptanceCriteria": (
                trimmed_story.get("acceptanceCriteria", [])[:3] if trimmed_story.get("acceptanceCriteria") else []
            ),
        }
        trimmed_story = critical_only

    trimmed_story["_context_trimmed"] = True
    return trimmed_story, True


def guard_story_context(
    story: dict,
    budget_tokens: int = 180000,
    ralph_prompt: str = "",
) -> dict:
    """Main entry point for context overflow guard.

    Estimates total prompt tokens (story + ralph prompt + files).
    If over budget, applies progressive trimming.

    Args:
        story: Story dictionary
        budget_tokens: Max allowed tokens (default 180000)
        ralph_prompt: Ralph CLAUDE.md prompt for size estimation

    Returns:
        Story dictionary, potentially with _context_trimmed=True
    """
    # Get budget from environment variable if set
    env_budget = os.environ.get("SPIRAL_CONTEXT_BUDGET")
    if env_budget and env_budget.isdigit():
        budget_tokens = int(env_budget)

    # Estimate ralph prompt tokens once
    ralph_tokens = estimate_tokens(ralph_prompt) if ralph_prompt else 0

    # Apply trimming
    trimmed_story, was_trimmed = trim_progressive(story, budget_tokens, ralph_prompt, ralph_tokens)

    return trimmed_story

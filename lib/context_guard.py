"""lib/context_guard.py — Token estimation and prompt trimming for Phase I."""

from __future__ import annotations

MODEL_LIMITS: dict[str, int] = {
    "haiku": 80000,
    "sonnet": 200000,
    "opus": 200000,
}
TRIM_THRESHOLD = 0.88


def estimate_phase_i_tokens(prompt: str) -> int:
    """Estimate token count for a Phase I prompt.

    Raises ValueError for non-string or None input.
    Approximation: 1 token ≈ 4 characters.
    """
    if not isinstance(prompt, str):
        raise ValueError(f"prompt must be a string, got {type(prompt).__name__!r}")
    return max(1, len(prompt) // 4)


def trim_prompt_sections(
    prompt: str,
    model: str = "haiku",
    _token_limit: int | None = None,
) -> str:
    """Trim prompt by removing example sections when it exceeds 88% of context limit.

    Trim order: example code sections first, then AC examples, then truncate
    description. Story title is always preserved.

    Args:
        prompt: The full prompt string to trim.
        model: Model name used to look up the context limit.
        _token_limit: Override the model token limit (for testing).

    Returns:
        Trimmed prompt string. Sensitive data in removed sections will not
        appear in the returned value.
    """
    limit = _token_limit if _token_limit is not None else MODEL_LIMITS.get(model, 80000)
    threshold = int(limit * TRIM_THRESHOLD)

    if estimate_phase_i_tokens(prompt) <= threshold:
        return prompt

    lines = prompt.split("\n")
    result_lines: list[str] = []
    in_removable_section = False

    for line in lines:
        stripped = line.strip().lower()
        # Detect removable section headers
        if stripped.startswith("## example") or stripped.startswith("## ac example"):
            in_removable_section = True
            continue  # drop this header and enter skip mode
        # A new h2 ends the removable section
        if stripped.startswith("## ") and in_removable_section:
            in_removable_section = False
        if not in_removable_section:
            result_lines.append(line)

    trimmed = "\n".join(result_lines)

    # If still over threshold, remove description section body
    if estimate_phase_i_tokens(trimmed) > threshold:
        desc_start = trimmed.find("\n## Description")
        if desc_start != -1:
            next_section = trimmed.find("\n## ", desc_start + 1)
            if next_section != -1:
                trimmed = trimmed[:desc_start] + trimmed[next_section:]

    return trimmed

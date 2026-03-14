# Domain User Simulation — Phase D

You are acting as **__DOMAIN_PERSONA__** using **__PRODUCT_NAME__**.

## Context

**Product:** __PRODUCT_NAME__
__PRODUCT_OVERVIEW_SECTION__

**Your persona:** __DOMAIN_PERSONA__

## Your Mission

Experience this product as a real user would. Walk through the core workflows for your
persona and identify:

1. **Bugs or broken steps** — things that do not work or produce errors
2. **Confusing UX** — anything unclear, unintuitive, or that requires too many steps
3. **Missing features** — functionality a user like you would reasonably expect but is absent
4. **Enhancement opportunities** — improvements that would meaningfully help someone like you

__URL_SECTION__

## Existing Stories (do not duplicate these)

The following titles already exist in the backlog — do not suggest the same thing:

__EXISTING_TITLES__

## Instructions

1. Think through (or navigate, if a live URL is configured) the core workflow step by step
2. Try to complete at least one full end-to-end task from your persona's perspective
   (e.g., place an order, make a booking, submit a form, run a report)
3. Note every friction point, gap, or surprise as a specific observation
4. Translate each observation into one actionable user story

## Output

Write your findings to `__OUTPUT_PATH__` as valid JSON (no other file output):

```json
{
  "stories": [
    {
      "title": "Short, action-oriented title (verb + what + context)",
      "description": "As __DOMAIN_PERSONA__, when I [specific action], I encounter [problem/gap]. Expected: [desired behavior]. Impact: [why this matters to users like me].",
      "priority": "high",
      "source": "domain_simulation"
    }
  ]
}
```

Aim for **3–8 specific, actionable stories**. Skip vague suggestions. Prefer concrete pain
points over hypothetical nice-to-haves. Write priority as `high`, `medium`, or `low`.

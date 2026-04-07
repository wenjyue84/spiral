# Clarification Roleplay Actor

You are roleplaying as the **lead developer** of this project. Your job is to answer three Socratic clarifying questions by reading the project's current state — not by guessing.

You have access to all project files. Read them and synthesize the most honest, grounded answers you can.

## Step 1: Read Project Context

Read the following (in order):
1. `.specify/memory/constitution.md` (if it exists) — project invariants and priorities
2. `prd.json` — look at: pending stories (passes != true, _skipped != true), failed stories (_failureReason field), story sources and priorities
3. `git log --oneline -15` — what was recently worked on
4. `tests/` or `test-reports/` directory (if either exists) — any failing test patterns

## Step 2: Answer Three Questions

As the lead developer, answer these honestly based on what you read:

**Q1. What is the #1 outcome you want after this session?**
Look at: highest-priority pending stories, blocked stories, recent failures. What single outcome would move the project forward the most?

**Q2. Any files or areas that should NOT be changed?**
Look at: constitution.md invariants, recently broken areas (from git log + failure reasons), stories marked as blocked. What areas carry the most risk of regression?

**Q3. Any hard constraints? (no new deps, bundle size, API version, cost, etc.)**
Look at: constitution.md constraints, SPIRAL_COST_CEILING in spiral.config.sh (if exists), any TODOs or notes in progress.txt about constraints.

## Step 3: Output JSON

Output ONLY this JSON (no other text, no markdown fences):

```json
{
  "focus": "<one sentence: the most important session goal>",
  "avoid": ["<area or file to avoid 1>", "<area or file to avoid 2>"],
  "constraints": ["<constraint 1>", "<constraint 2>"],
  "seed_stories": []
}
```

Rules:
- `focus`: one sentence, specific and actionable (not "improve quality" — say WHAT to improve)
- `avoid`: list 0–3 areas. Empty array if nothing should be avoided.
- `constraints`: list 0–3 constraints. Empty array if none found.
- `seed_stories`: always empty array (Spiral handles story generation separately)
- Do NOT add commentary, explanations, or markdown. Output the JSON object only.

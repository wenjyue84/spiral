# Phase 0 — CLARIFY

Phase 0 is a one-time interactive session that runs **before the loop begins**.
Its job is to align you and Spiral on goals, constraints, and initial work so the
autonomous loop stays on-track from the very first iteration.

**Without Phase 0, Spiral drifts** — Phase R discovers whatever looks interesting
rather than what actually advances your project's goals.

---

## When It Runs

| Condition | Behaviour |
|-----------|-----------|
| First run (no `.spiral/_phase_0_done` marker) | Runs all 5 sub-phases interactively |
| Resume / `--gate proceed` / `--gate skip` | Skipped entirely |
| After Phase 0 completes | Marker written; subsequent runs skip it |

To re-run Phase 0 on the next loop start, delete `.spiral/_phase_0_done`.

---

## Sub-phases

```
Phase 0: Session Setup
├── 0-A  Constitution   — establish/review non-negotiable rules
├── 0-B  Focus          — set the theme for this spiral session
├── 0-C  Clarify        — 3 questions to lock scope, prevent drift
├── 0-D  Stories        — initial seeds + AI-suggested examples
└── 0-E  Options        — time limit and other session knobs
```

---

### 0-A — Constitution

The constitution is **the most important output of Phase 0**. It defines what
Spiral IS, what stories are in-scope, and what is absolutely forbidden. Every
Phase R research run and every Ralph implementation agent reads it.

**Without a constitution, story drift is guaranteed.**

#### What happens

1. If a constitution file already exists at `SPIRAL_SPECKIT_CONSTITUTION`
   (default: `.specify/memory/constitution.md`):
   - Shows a 10-line preview
   - Prompts: `(r)euse  (e)dit  (R)eplace with generated`

2. If no constitution exists:
   - Generates a suggested constitution from `prd.json` (productName, overview,
     goals, epics) plus the current focus
   - Shows the full suggestion
   - Prompts: `(a)ccept  (e)dit  (s)kip`

#### Constitution structure

```markdown
# My Project — Spiral Constitution

## What This Project Is
One-paragraph description from prd.json overview.

## Session Focus
(Populated from 0-B if set before 0-A runs, or on Replace.)

## Core Goals
- Goal 1 from prd.json
- Goal 2 from prd.json

## Epics In Scope
- Epic title: description

## Invariants (Never Break These)
1. Phase ordering — R → T → M → G → I → V → C must not be bypassed
2. Git ratchet — all existing tests must pass before a story closes
3. Story atomicity — each story is one independent, self-contained unit
4. Config API — spiral.config.sh env vars are user-facing; renames need migration
5. No scope drift — every story must directly advance one of the core goals above

## What Stories Must NOT Do
- NEVER break the phase ordering or bypass existing quality gates
- NOT: add features outside the stated goals without explicit approval
- AVOID: hard dependencies on tools not auto-installed by setup.sh
- FORBIDDEN: commit broken or partially-implemented intermediate states

## Acceptable Story Scope
- Directly advancing one of the core goals above
- Improving existing phases for speed, reliability, or observability
- Adding optional capabilities behind env var flags (default off)
- Fixing bugs in existing behaviour
```

#### Constitution enforcement

The `NOT:`, `NEVER:`, `AVOID:`, `FORBIDDEN:` prefixes in "What Stories Must NOT Do"
are machine-readable. `lib/validate_stories.py` extracts them and rejects any
generated story whose title or description matches a forbidden phrase.

#### Customise the constitution path

```bash
# spiral.config.sh
SPIRAL_SPECKIT_CONSTITUTION=".specify/memory/constitution.md"
```

---

### 0-B — Session Focus

Sets `$SPIRAL_FOCUS` — an optional free-form string that guides Phase R's story
discovery for **this session only**.

```
What should Spiral focus on this session?
Example: "Chrome DevTools integration", "fix test flakiness"
> improve Phase R reliability
```

You can also set it via CLI to skip the prompt:

```bash
bash spiral.sh 5 --focus "improve Phase R reliability"
```

The focus string flows into:
- Phase R research prompt (steers story generation)
- Ralph system prompt (steers implementation choices)
- Constitution `Session Focus` section (if constitution is generated/replaced)

---

### 0-C — Clarifying Questions

Three targeted questions whose answers are appended to `$SPIRAL_FOCUS`,
giving Phase R and Ralph richer context to avoid scope drift.

```
Q1. What is the #1 outcome you want after this session?
> Phase R should return 0 false-positive stories

Q2. Any files or areas that should NOT be changed?
> ralph/ralph.sh — do not touch the inner loop

Q3. Any hard constraints? (no new deps, bundle size, target version, etc.)
> no new Python dependencies
```

Answers are concatenated with `|` delimiters:

```
Goal: Phase R should return 0 false-positive stories | Avoid: ralph/ralph.sh | Constraint: no new Python dependencies
```

You can press Enter to skip any question.

---

### 0-D — Initial Stories

Optionally seed `prd.json` with story ideas before the loop starts.
Phase R will still discover more, but seeds are useful when you already know
exactly what you want implemented.

**AI-suggested examples** are generated from `prd.json` goals and epics:

```
Suggested seeds based on your goals & focus:
    [1] Implement: Phase R Reliability — improve story quality scoring and dedup
    [2] Implement: Token Efficiency — reduce per-story token consumption
    [3] Goal: All stories must have at least one acceptance criterion
    [4] Improve: Phase R reliability

Type seeds or enter a number from above (blank line to finish):
> 1
  → Implement: Phase R Reliability — improve story quality scoring and dedup
> Add retry budget per story per session
>
```

Each seed is added to `prd.json` with:
- `"priority": "medium"`
- `"passes": false`
- `"seed": true`
- `"added_by": "phase_0_clarify"`

---

### 0-E — Session Options

Currently: **time limit**.

```
How many hours should Spiral run? (Enter for unlimited): 2
[0-E] Time limit: 120m (~2h)
```

When the time limit is reached, the loop exits cleanly at the end of the current
iteration (not mid-story).

You can also set it via CLI:

```bash
bash spiral.sh 10 --time-limit 120   # 120 minutes
```

---

## Audit Log

After all sub-phases complete, Phase 0 writes `.spiral/_clarify_output.json`:

```json
{
  "phase": "0",
  "ts": "2026-03-15T10:00:00Z",
  "time_limit_mins": 120,
  "focus": "improve Phase R reliability | Goal: 0 false positives | Avoid: ralph/ralph.sh",
  "seeds_added": 2,
  "constitution_created": true,
  "constitution_path": ".specify/memory/constitution.md",
  "clarifying_answers": {
    "q1_primary_outcome": "Phase R should return 0 false-positive stories",
    "q2_avoid_areas": "ralph/ralph.sh",
    "q3_constraints": "no new Python dependencies"
  }
}
```

---

## Skipping Phase 0

For CI / non-interactive runs, pass `--gate proceed` or `--gate skip`:

```bash
bash spiral.sh 5 --gate proceed    # skip Phase 0, auto-approve Gate
bash spiral.sh 5 --gate skip       # skip Phase 0, auto-skip Gate
```

Constitution and focus can still be pre-set via `spiral.config.sh`:

```bash
# spiral.config.sh
SPIRAL_SPECKIT_CONSTITUTION=".specify/memory/constitution.md"
SPIRAL_FOCUS="improve Phase R reliability"
```

---

## Re-running Phase 0

```bash
rm .spiral/_phase_0_done
bash spiral.sh
```

This re-runs all 5 sub-phases on the next launch. The constitution will show
the `(r)euse / (e)dit / (R)eplace` prompt instead of generating from scratch.

---

## Relationship to the Constitution

The constitution written in **0-A** is consumed throughout the loop:

| Phase | How the constitution is used |
|-------|------------------------------|
| **Phase R** | Injected into research prompt — stories that conflict with invariants are not generated |
| **Phase S** | `validate_stories.py` extracts `NEVER/NOT/AVOID/FORBIDDEN` phrases; matching stories are rejected |
| **Ralph** | Appended to system prompt — implementation choices respect the invariants |

The constitution is the primary mechanism for preventing **story drift** — the
tendency for an autonomous loop to implement interesting but off-scope work.

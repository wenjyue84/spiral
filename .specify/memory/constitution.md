# Spiral Project Constitution

## What Spiral Is
Spiral is a **Self-iterating PRD Research & Implementation Autonomous Loop**.
It runs in two stages: a one-time startup to align on goals and stories (Clarify first),
then a repeating loop that researches, validates, merges, implements, and checks until
all stories pass or a time/iteration limit is hit.

## How It Works — Phase Flow

### STARTUP (runs once before the loop)

```
Phase 0: CLARIFY (5 sub-phases, skipped with --gate proceed/skip)
  0-A Constitution — create/review non-negotiable rules
  0-B Focus        — set this session's theme
  0-C Clarify      — 3 questions to lock scope & prevent drift
  0-D Story Prep   — seed stories → prd.json, ai-example picks → queue
  0-E Options      — time limit & session knobs
```

### STORY PIPELINE (per iteration — all 5 story sources)

```
Phase A: AI SUGGESTIONS    — consume Phase 0-D queue + PRD gap analysis + test stories
Phase R: RESEARCH          — Gemini web pre-fetch → Claude agent → story candidates
Phase T: TEST SYNTHESIS    — scan test-reports/ failures → regression story candidates
  (R and T run in parallel)
Phase S: STORY VALIDATE    — constitution check, goal-alignment, dedup
Phase M: MERGE             — patch prd.json, priority: test-fix > research > ai-example
Phase G: HUMAN GATE        — optional checkpoint (skipped with --gate proceed)
```

### IMPLEMENTATION (per iteration — turns stories into code)

```
Phase I: IMPLEMENT
  ├─ Decompose      — split oversized stories into sub-stories
  ├─ Execute         — Ralph workers (sequential or parallel worktrees)
  ├─ Retry           — failure → escalate model (haiku→sonnet→opus→skip)
  ├─ Self-Review     — Phase I.5: diff sent for AI self-review
  ├─ Quality Gates   — test-ratchet, security-scan
  └─ Commit/Revert   — merge on pass, drop branch on fail
Phase V: VALIDATE
  ├─ SPIRAL_VALIDATE_CMD (full integration suite)
  └─ Persistent suites (smoke, regression, security, perf)
Phase P: PUSH             — push commits to origin/main
Phase C: CHECK DONE       — all pass? exit. else loop back to Phase A
```

Every story carries a `_source` field: seed (user), ai-example (AI-picked), research,
test-fix (regression), test-story (generated tests). Phase V builds a persistent test
suite that grows more comprehensive each iteration.

## Core Invariants (Never Break These)
1. **Phase ordering** — 0 → A → R/T → S → M → G → I → V → P → C → (loop to A). Stories must not introduce shortcuts that skip phases.
2. **Clarify first** — Phase 0 establishes constitution, focus, and scope before any implementation begins.
3. **Git ratchet** — Committed state must always pass quality gates. No story may weaken the gate chain.
4. **Story atomicity** — Each story is one independent unit. Stories must not have hidden co-dependencies.
5. **Backward compatibility** — `spiral.config.sh` env vars are user-facing API. Renames/removals require migration paths.
6. **Token efficiency** — Ralph agents use `rtk`. New tooling must not increase per-story token consumption without justification.

## What Stories Must NOT Do
- Add features that require re-architecting the phase structure
- Remove or bypass existing quality gates (secret scan, security scan, test ratchet)
- Add hard dependencies on tools not auto-installed by `setup.sh`
- Commit broken intermediate states
- Skip or remove the Clarify phase (Phase 0)

## Acceptable Story Scope
- Improving existing phases (speed, reliability, observability)
- Adding optional capabilities behind env var flags (default off)
- Expanding test coverage
- Fixing bugs in existing behaviour
- Improving documentation and onboarding

## Story Prioritization: Production Value First

**The primary question for every story**: "Would a user NOTICE or FEEL this improvement when running Spiral?"

### Priority Tiers (highest to lowest)

1. **Tier 1 — Visible & Felt** (implement first)
   - Terminal UX improvements during a run (colors, progress, summaries)
   - Web dashboard (localhost:5299) enhancements visible in real-time
   - Features a user would demo to another person
   - Improvements that reduce run failures or wasted API spend

2. **Tier 2 — Reliability & Correctness** (implement when blocking)
   - Crash recovery and data integrity
   - Features that prevent silent data loss
   - Error messages that explain WHY something failed

3. **Tier 3 — Power User Features** (implement after Tier 1 & 2)
   - CLI flags for advanced control (--replay, --cost-report, --focus-tags)
   - Configuration options that reduce cost or improve quality
   - Test coverage for existing features

4. **Tier 4 — Infrastructure & Observability** (candidates/backlog)
   - OTel spans, OpenMetrics endpoints, telemetry pipelines
   - TLA+ specs, bats test scaffolding, contract tests
   - CI/CD workflow enhancements (GitHub Actions)
   - Niche features used by <5% of users

### Anti-Patterns to Avoid
- Stories that only change internal file formats with no user-facing effect
- "Add X for future use" stories with no current consumer
- Duplicate coverage of already-tested code paths
- Features that require rare external dependencies (GPG, TLA+ toolchain)
- Telemetry/observability infrastructure before there is a consumer UI

### This Principle Applies to ALL Projects
When writing a prd.json for any project (not just Spiral), always ask:
> "If someone ran this software today after this story is done, would they notice something better?"

If the answer is "no" or "only a developer would notice", the story belongs in Tier 4 (candidates).

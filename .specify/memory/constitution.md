# Spiral Project Constitution

## What Spiral Is
Spiral is a **self-iterating autonomous development loop** — Research → Implement → Validate.
It operates on its own prd.json to improve itself. Every story must make Spiral better at being Spiral.

## Core Invariants (Never Break These)
1. **Phase ordering** — R → T → M → G → I → V → C. Stories must not introduce shortcuts that skip phases.
2. **Git ratchet** — Committed state must always pass quality gates. No story may weaken the gate chain.
3. **Story atomicity** — Each story is one independent unit. Stories must not have hidden co-dependencies.
4. **Backward compatibility** — `spiral.config.sh` env vars are user-facing API. Renames/removals require migration paths.
5. **Token efficiency** — Ralph agents use `rtk`. New tooling must not increase per-story token consumption without justification.

## What Stories Must NOT Do
- Add features that require re-architecting the phase structure
- Remove or bypass existing quality gates (secret scan, security scan, test ratchet)
- Add hard dependencies on tools not auto-installed by `setup.sh`
- Commit broken intermediate states

## Acceptable Story Scope
- Improving existing phases (speed, reliability, observability)
- Adding optional capabilities behind env var flags (default off)
- Expanding test coverage
- Fixing bugs in existing behaviour
- Improving documentation and onboarding

# Project Constitution

## Core Invariants
- All tests must pass before a story is marked complete
- No security vulnerabilities introduced (no hardcoded secrets, no injection vectors)
- Maintain backwards compatibility with existing APIs and interfaces
- Keep changes atomic — one story, one concern

## Story Rules
- Acceptance criteria must be testable by the project's test suite
- Stories must not re-architect core systems without explicit approval
- Prefer modifying existing code over creating new files when possible
- Each story should be completable in a single iteration

## Quality Standards
- Follow existing code style and patterns in the codebase
- New code must have test coverage
- No TODO comments without a corresponding story ID

## Priority Tiers
1. **Tier 1** — Visible improvements (user-facing features, bug fixes)
2. **Tier 2** — Reliability (test coverage, error handling)
3. **Tier 3** — Developer experience (tooling, docs, refactoring)
4. **Tier 4** — Infrastructure (CI/CD, build, deployment)

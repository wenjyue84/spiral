# Contributing to SPIRAL

## GitHub Actions Security — Pinned Action SHAs

All third-party GitHub Actions used in `.github/workflows/` **must** be pinned
to an immutable 40-character commit SHA, not a mutable version tag.

### Why SHA pinning matters

Mutable version tags (e.g., `actions/checkout@v4`) can be silently reassigned
by the action's maintainer — or by a supply-chain attacker who has compromised
the upstream repository. A tag can point to a completely different (malicious)
commit without any warning.

Pinning to a full commit SHA (`actions/checkout@<40-char-hex>`) guarantees that
the exact code that was reviewed is the code that runs, even if the tag is later
moved or deleted.

Reference: [GitHub Actions security hardening](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions#using-third-party-actions)

### Required format

Every `uses:` line that references a third-party action must use the format:

```yaml
uses: owner/repo@<40-char-SHA>  # vX.Y.Z
```

Example:

```yaml
- uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
```

### Enforcement

A `pinned-actions-check` CI job runs on every pull request. It fails if any
`uses:` line references a mutable tag (e.g., `@v3`, `@main`, `@master`) instead
of a full 40-character SHA. PRs that fail this check cannot be merged.

The check is also enforced via CODEOWNERS: any change to `.github/workflows/`
requires explicit approval from `@spiral-security-team`.

### How to update a pinned action

When a new version of an action is released, update its SHA pin as follows:

1. Find the new commit SHA on the action's GitHub releases page (e.g.,
   `https://github.com/actions/checkout/releases`). Click the tag, then copy
   the full commit SHA from the git tree view.

2. Replace the old SHA in the workflow file:
   ```yaml
   # Before
   uses: actions/checkout@34e114876b0b11c390a56381ad16ebd13914f8d5  # v4
   # After
   uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
   ```

3. Update the inline version comment to the new human-readable tag.

4. Open a PR. The `pinned-actions-check` job will verify the new SHA format.

**Automated updates:** Dependabot is configured (`.github/dependabot.yml`) to
open weekly PRs that update SHA pins automatically. These PRs still require
review from `@spiral-security-team` via CODEOWNERS before merge.

### Verifying a SHA independently

To verify that a SHA matches the expected release tag:

```bash
# Example: verify that a SHA corresponds to actions/checkout v4.2.2
git ls-remote https://github.com/actions/checkout refs/tags/v4.2.2
```

The first column is the commit SHA. Compare it against the SHA in the workflow.

---

## Python Toolchain (uv)

SPIRAL uses [uv](https://docs.astral.sh/uv/) exclusively for Python dependency management.
**Never use `pip install` or `pip install -r requirements.txt`** — always use `uv sync`.

### Set up your local environment

```bash
# Install uv (first time only)
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS/Linux
# or: winget install astral-sh.uv                  # Windows

# Install all Python dependencies (reads pyproject.toml + uv.lock)
uv sync

# After adding/removing a dependency in pyproject.toml, regenerate the lockfile:
uv lock
# Then commit both pyproject.toml and uv.lock together.
```

CI uses `uv sync --frozen` to enforce exact lockfile reproducibility.
If CI fails with a lockfile error, run `uv lock` locally and commit the updated `uv.lock`.

## Running Tests Locally

```bash
# Python tests
uv run pytest tests/ -v --tb=short

# Bash tests (requires bats-core submodule)
tests/bats-core/bin/bats tests/*.bats tests/lib/*.bats

# Type checking
uv run mypy lib/ --strict

# Shell linting
shellcheck --severity=error spiral.sh setup.sh lib/*.sh
shfmt -d -i 2 -ci spiral.sh ralph/ralph.sh lib/*.sh
```

## Commit Message Convention

SPIRAL uses [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]
```

Common types: `feat`, `fix`, `chore`, `docs`, `test`, `refactor`, `ci`.

Example:
```
feat(phase-i): add story drift detection after implementation
```

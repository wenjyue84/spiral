# GitHub Actions Security — Credential & OIDC Checklist

This document is the authoritative inventory of credential usage across SPIRAL's GitHub Actions
workflows. It must be updated whenever a new integration is added or an existing one changes.

---

## Current Integrations Inventory

### ✅ Static secrets currently in use: NONE

No long-lived API keys or static secrets are stored as GitHub repository secrets.
All workflows run with least-privilege `GITHUB_TOKEN` only.

| Integration | Auth Method | Scope / Permissions | Notes |
|---|---|---|---|
| `GITHUB_TOKEN` | Automatic (GitHub-managed) | `contents: read` (most jobs); `contents: write` (`release.yml` only) | Expires at job end. No rotation needed. |
| CodeQL SARIF upload | `GITHUB_TOKEN` | `security-events: write` | Granted per-job in `codeql.yml`. |
| Artifact upload | `GITHUB_TOKEN` | `actions: read` (implicit) | `actions/upload-artifact` uses built-in token. |

### ✅ Cloud provider integrations: NONE

SPIRAL does not deploy to AWS, GCP, Azure, or any other cloud provider from CI.
If a cloud deployment step is added in the future, **OIDC must be used** (see below).

---

## OIDC Policy — Required When Cloud Integrations Are Added

If a future workflow requires cloud credentials (AWS, GCP, Azure, Vault, etc.),
the following rules apply **before the PR can be merged**:

### Mandatory checklist for any new OIDC-based job

- [ ] Job has `id-token: write` in its `permissions` block.
- [ ] All other permissions in that job are explicitly minimised (`contents: read`, etc.).
- [ ] `id-token: write` is **NOT** set at the workflow level — only on the job that needs it.
- [ ] Trust policy on the cloud side restricts issuance to:
  - Exact repository: `repo:OWNER/REPO:*` — no `*` wildcards for the owner segment.
  - Branch-scoped where possible: `repo:OWNER/REPO:ref:refs/heads/main`.
  - Never use `repo:*:*` or organisation-wide wildcards.
- [ ] Token audience (`aud`) is set to the minimum required scope (e.g., `sts.amazonaws.com`).
- [ ] This table is updated with the new integration.

### Example: adding an AWS deploy job

```yaml
jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      id-token: write   # OIDC token issuance
      contents: read    # checkout only
    steps:
      - uses: actions/checkout@<SHA>  # pinned

      - name: Configure AWS credentials via OIDC
        uses: aws-actions/configure-aws-credentials@<SHA>  # pinned
        with:
          role-to-assume: arn:aws:iam::123456789012:role/spiral-ci
          aws-region: ap-southeast-1
          # No access-key-id / secret-access-key — OIDC only
```

Corresponding AWS trust policy (IAM role):

```json
{
  "Effect": "Allow",
  "Principal": { "Federated": "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com" },
  "Action": "sts:AssumeRoleWithWebIdentity",
  "Condition": {
    "StringEquals": {
      "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
      "token.actions.githubusercontent.com:sub": "repo:OWNER/spiral:ref:refs/heads/main"
    }
  }
}
```

**No wildcards** in the `sub` condition.

---

## Integrations That Must Retain Static Secrets (if added)

| Integration | Reason static secret is required | Rotation cadence |
|---|---|---|
| Third-party LLM providers (Anthropic, Google, OpenAI) | OIDC not supported by these APIs today | 90 days (add to calendar) |
| npm publish token | npm OIDC granular access tokens are supported — use [npm OIDC](https://docs.npmjs.com/generating-provenance-statements) if added | N/A if OIDC used |
| PyPI publish | Use [Trusted Publishers](https://docs.pypi.org/trusted-publishers/) (OIDC) — no static token needed | N/A if OIDC used |

Any static secret stored in GitHub must be documented in the table above with a rotation cadence.

---

## Workflow-Level Permission Defaults

All workflows must declare `permissions: {}` at the top level (or per-job) to prevent accidental
over-privilege. The current workflows use per-job `permissions:` blocks, which is acceptable.

Forbidden patterns:
- `permissions: write-all` at workflow level
- Missing `permissions:` key (defaults to repo-level token settings, which may be overly broad)
- `id-token: write` at workflow level when only one job needs OIDC

---

## References

- [GitHub OIDC concepts](https://docs.github.com/en/actions/concepts/security/openid-connect)
- [AWS OIDC setup](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
- [GCP Workload Identity Federation](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/configuring-openid-connect-in-google-cloud-platform)
- [PyPI Trusted Publishers (OIDC)](https://docs.pypi.org/trusted-publishers/)
- [npm provenance / OIDC](https://docs.npmjs.com/generating-provenance-statements)
- [step-security/harden-runner](https://github.com/step-security/harden-runner) — used in all SPIRAL workflows

---

*Last updated: 2026-03-15. Update this file whenever a new integration is added or a secret is rotated.*

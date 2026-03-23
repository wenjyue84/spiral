"""
Security tests for GitHub Actions workflow and action YAML files.

Verifies that:
1. All workflows declare explicit `permissions:` blocks with no `write-all` scope
2. Every `uses:` action reference is pinned to a full 40-char commit SHA
3. No YAML file contains plaintext secret strings (password=, token=, api_key=)
"""

import glob
import re
from pathlib import Path

import yaml


def get_workflow_files() -> list[Path]:
    """Return all workflow YAML files under .github/."""
    workflow_dir = Path(".github")
    if not workflow_dir.exists():
        return []

    yml_files = glob.glob(".github/**/*.yml", recursive=True)
    yaml_files = glob.glob(".github/**/*.yaml", recursive=True)
    return [Path(f) for f in yml_files + yaml_files]


class TestWorkflowsHaveExplicitPermissions:
    """Test that all workflows declare explicit permissions blocks."""

    def test_workflows_have_explicit_permissions(self) -> None:
        """All workflow YAML files must declare explicit permissions: blocks."""
        workflow_files = get_workflow_files()
        assert len(workflow_files) > 0, "No workflow files found"

        failures: list[str] = []

        for workflow_file in workflow_files:
            # Skip custom actions and dependabot config; they don't need top-level permissions
            file_str = str(workflow_file).replace("\\", "/")
            if ".github/actions/" in file_str or "dependabot" in file_str:
                continue

            try:
                with open(workflow_file) as f:
                    data = yaml.safe_load(f)
            except (yaml.YAMLError, OSError) as e:
                failures.append(f"{workflow_file}: Failed to parse YAML: {e}")
                continue

            if data is None:
                failures.append(f"{workflow_file}: Empty or invalid YAML")
                continue

            # Check top-level permissions key exists
            if "permissions" not in data:
                failures.append(f"{workflow_file}: Missing top-level `permissions:` block")
                continue

            permissions = data["permissions"]

            # Permissions can be:
            # - A string like "read-all" (valid, means all scopes are read-only)
            # - A dict with explicit scopes (valid, grants specific permissions)
            # But NOT the string "write-all" (overly permissive)
            if isinstance(permissions, str):
                if permissions == "write-all":
                    failures.append(
                        f"{workflow_file}: `permissions: write-all` is overly permissive; use `read-all` or specific scopes"
                    )
                # "read-all" and other valid strings are OK, no action needed
                continue

            # If dict, should not be empty
            if isinstance(permissions, dict) and not permissions:
                failures.append(f"{workflow_file}: `permissions:` dict is empty; must declare scopes")
                continue

        assert not failures, "\n".join(failures)


class TestActionsPinnedToSha:
    """Test that all actions are pinned to full 40-char commit SHAs."""

    def test_actions_pinned_to_sha(self) -> None:
        """Every `uses:` action reference must be pinned to a full 40-char commit SHA."""
        workflow_files = get_workflow_files()
        assert len(workflow_files) > 0, "No workflow files found"

        # Regex to match `uses:` with full 40-char SHA
        # Pattern: [dash?] uses: owner/action@[40 hex chars]
        # Must allow both lowercase and uppercase hex digits
        # The `-` is optional YAML list item prefix
        sha_pattern = re.compile(r"^\s*-?\s*uses:\s+[^@]+@([0-9a-fA-F]{40})\s*(?:#.*)?$")

        # Patterns for non-SHA references that are ALLOWED
        # (local actions via ./.github/actions/... or ../.github/actions/... are allowed)
        local_action_pattern = re.compile(r"^\s*-?\s*uses:\s+\.{1,2}/\.?github/actions/")

        failures: list[str] = []

        for workflow_file in workflow_files:
            try:
                with open(workflow_file) as f:
                    content = f.read()
            except OSError as e:
                failures.append(f"{workflow_file}: Failed to read: {e}")
                continue

            line_num = 0
            for line in content.split("\n"):
                line_num += 1

                # Skip comment-only lines (even if they contain 'uses:')
                if line.strip().startswith("#"):
                    continue

                # Skip lines that don't contain `uses:` as a YAML key
                # This avoids shell commands that contain 'uses:' string
                if "uses:" not in line:
                    continue

                # Skip if line contains shell syntax (e.g., grep, |, \)
                # These are command examples or test code, not actual action declarations
                if any(c in line for c in ["$", "|", "\\", "grep", "sed", "awk"]):
                    continue

                # Allow local actions (e.g., uses: ./.github/actions/setup-uv)
                if local_action_pattern.match(line):
                    continue

                # Check if this line has a full 40-char SHA
                if not sha_pattern.match(line):
                    failures.append(f"{workflow_file}:{line_num}: Action not pinned to full SHA: {line.strip()}")

        assert not failures, "\n".join(failures)


class TestNoPlaintextSecrets:
    """Test that workflow YAML files contain no plaintext secret strings."""

    def test_no_plaintext_secrets(self) -> None:
        """No YAML file under .github/ should contain plaintext secret patterns."""
        workflow_files = get_workflow_files()
        assert len(workflow_files) > 0, "No workflow files found"

        # Patterns to detect bare secrets (not comments or examples)
        secret_patterns = [
            re.compile(r"password\s*=", re.IGNORECASE),
            re.compile(r"token\s*=", re.IGNORECASE),
            re.compile(r"api_key\s*=", re.IGNORECASE),
            re.compile(r"api-key\s*=", re.IGNORECASE),
        ]

        failures: list[str] = []

        for workflow_file in workflow_files:
            try:
                with open(workflow_file) as f:
                    content = f.read()
            except OSError as e:
                failures.append(f"{workflow_file}: Failed to read: {e}")
                continue

            line_num = 0
            for line in content.split("\n"):
                line_num += 1

                # Skip comment lines
                if line.strip().startswith("#"):
                    continue

                # Check against secret patterns
                for pattern in secret_patterns:
                    if pattern.search(line):
                        failures.append(f"{workflow_file}:{line_num}: Potential plaintext secret: {line.strip()}")

        assert not failures, "\n".join(failures)

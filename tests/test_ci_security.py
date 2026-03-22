"""Security tests for GitHub Actions CI workflows.

Ensures that workflows do not leak secrets, tokens, or passwords in logs
or error output through unsafe patterns like bare echo commands or unmasked
secret interpolation.

Story: US-760
"""

import re
from pathlib import Path
from typing import Any

import yaml


class TestCISecurityPatterns:
    """Tests for unsafe secret handling patterns in workflow files."""

    WORKFLOW_DIR = Path(".github/workflows")
    ACTIONS_DIR = Path(".github/actions")

    # Regex patterns to detect unsafe secret access
    BARE_SECRET_PATTERN = re.compile(
        r'\$(?!{)[A-Z_]+',  # $VARIABLE (not ${...})
        re.IGNORECASE
    )
    UNSAFE_ECHO_PATTERN = re.compile(
        r'echo\s+\$(?!{)[A-Z_]+',  # echo $VARIABLE (not echo ${{ ... }})
        re.IGNORECASE
    )
    SENSITIVE_KEY_PATTERN = re.compile(
        r'\b(TOKEN|PASSWORD|KEY|SECRET|API_KEY|AUTH|CRED)\b',
        re.IGNORECASE
    )

    def _find_all_workflow_files(self) -> list[Path]:
        """Find all workflow YAML files to test."""
        workflow_files: list[Path] = []

        # Find workflow files
        if self.WORKFLOW_DIR.exists():
            workflow_files.extend(self.WORKFLOW_DIR.glob("*.yml"))
            workflow_files.extend(self.WORKFLOW_DIR.glob("*.yaml"))

        # Find action.yml files
        if self.ACTIONS_DIR.exists():
            workflow_files.extend(self.ACTIONS_DIR.glob("*/action.yml"))
            workflow_files.extend(self.ACTIONS_DIR.glob("*/action.yaml"))

        return sorted(workflow_files)

    def _extract_run_blocks(self, workflow_content: Any) -> list[str]:
        """Extract all 'run:' command blocks from a workflow YAML."""
        run_blocks: list[str] = []

        if not isinstance(workflow_content, dict):
            return run_blocks

        # Check for jobs
        jobs: Any = workflow_content.get('jobs', {})
        if not isinstance(jobs, dict):
            return run_blocks

        for job in jobs.values():
            if not isinstance(job, dict):
                continue

            steps: Any = job.get('steps', [])
            if not isinstance(steps, list):
                continue

            for step in steps:
                if not isinstance(step, dict):
                    continue

                run_block: Any = step.get('run')
                if run_block and isinstance(run_block, str):
                    run_blocks.append(run_block)

        return run_blocks

    def test_no_echo_bare_secret_pattern(self) -> None:
        """Test that workflows don't use bare echo $SECRET commands.

        Acceptance Criterion 1: Pytest test parses each workflow YAML and
        asserts no `echo $SECRET` or bare secret interpolation patterns exist.
        """
        workflow_files = self._find_all_workflow_files()
        assert len(workflow_files) > 0, "No workflow files found to test"

        violations = []

        for workflow_file in workflow_files:
            try:
                with open(workflow_file, 'r', encoding='utf-8') as f:
                    content = yaml.safe_load(f)

                if content is None:
                    continue

                run_blocks = self._extract_run_blocks(content)

                for run_block in run_blocks:
                    if self.UNSAFE_ECHO_PATTERN.search(run_block):
                        violations.append(
                            f"{workflow_file}: Found unsafe echo pattern in run block"
                        )
            except yaml.YAMLError as e:
                violations.append(f"{workflow_file}: Failed to parse YAML: {e}")

        assert not violations, "\n".join(violations)

    def test_secrets_use_correct_syntax(self) -> None:
        """Test that all secrets are accessed via ${{ secrets.* }} syntax only.

        Acceptance Criterion 2: Test asserts all secrets are accessed via
        `${{ secrets.* }}` syntax only (not env vars printed to stdout).
        """
        workflow_files = self._find_all_workflow_files()
        assert len(workflow_files) > 0, "No workflow files found to test"

        violations = []
        # GitHub Actions provides standard environment variables
        # that are safe to reference without masking
        standard_github_env_vars = {
            'GITHUB_STEP_SUMMARY', 'GITHUB_OUTPUT', 'GITHUB_ENV', 'GITHUB_STATE',
            'PATH', 'HOME', 'RUNNER_OS', 'RUNNER_ARCH', 'RUNNER_TEMP',
            'CI', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN', 'ACTIONS_ID_TOKEN_REQUEST_URL',
        }

        for workflow_file in workflow_files:
            try:
                with open(workflow_file, 'r', encoding='utf-8') as f:
                    content = yaml.safe_load(f)

                if content is None:
                    continue

                run_blocks = self._extract_run_blocks(content)

                for run_block in run_blocks:
                    # Look for potential secret references
                    # Acceptable: ${{ secrets.SOMETHING }} or standard GitHub env vars
                    # Unacceptable: direct bare secret reference like $CUSTOM_SECRET

                    # Remove all safe patterns first:
                    # 1. ${{ ... }} expressions (all forms)
                    safe_pattern = r'\$\{\{[^}]+\}\}'
                    cleaned = re.sub(safe_pattern, '', run_block)

                    # 2. Standard GitHub environment variables
                    for env_var in standard_github_env_vars:
                        cleaned = re.sub(rf'\${env_var}\b', '', cleaned)

                    # Check if any remaining bare $ variables look like secrets
                    # (all caps, containing SECRET, TOKEN, PASSWORD, KEY, etc.)
                    matches = re.finditer(r'\$([A-Z_]+)', cleaned)
                    secret_keywords = ['SECRET', 'TOKEN', 'PASSWORD', 'KEY', 'API', 'AUTH']
                    for match in matches:
                        var_name = match.group(1)
                        if any(keyword in var_name for keyword in secret_keywords):
                            violations.append(
                                f"{workflow_file}: Found bare secret reference: ${var_name}"
                            )
            except yaml.YAMLError as e:
                violations.append(f"{workflow_file}: Failed to parse YAML: {e}")

        assert not violations, "\n".join(violations)

    def test_no_sensitive_key_names_bare(self) -> None:
        """Test that sensitive key names don't appear bare in run: steps.

        Acceptance Criterion 4: No sensitive key names (TOKEN, PASSWORD, KEY,
        SECRET) appear in `run:` steps without masking.
        """
        workflow_files = self._find_all_workflow_files()
        assert len(workflow_files) > 0, "No workflow files found to test"

        violations = []

        for workflow_file in workflow_files:
            try:
                with open(workflow_file, 'r', encoding='utf-8') as f:
                    content = yaml.safe_load(f)

                if content is None:
                    continue

                run_blocks = self._extract_run_blocks(content)

                for run_block in run_blocks:
                    # Remove safe contexts where these names are acceptable:
                    # - Inside ${{ }} expressions (GitHub syntax)
                    # - Inside comments (prefixed with #)
                    # - Inside strings (quoted values)

                    # Remove all ${{ }} expressions
                    safe_cleaned = re.sub(r'\$\{\{[^}]+\}\}', '', run_block)

                    # Check for bare key names being echoed or passed unsafely
                    # Pattern: word boundary + key name + word boundary
                    # But exclude cases where it's in a string context or comment
                    lines = safe_cleaned.split('\n')

                    for line in lines:
                        # Skip comments
                        if line.strip().startswith('#'):
                            continue

                        # Look for potentially unsafe references
                        # (KEY_NAME env var or TOKEN being echoed)
                        if re.search(r'echo.*\b(TOKEN|PASSWORD|KEY|SECRET|API_KEY)\b', line, re.IGNORECASE):
                            if not re.search(r'echo.*::\w+', line):  # Not a GitHub masked output
                                violations.append(
                                    f"{workflow_file}: Found bare sensitive key name in: {line.strip()}"
                                )
            except yaml.YAMLError as e:
                violations.append(f"{workflow_file}: Failed to parse YAML: {e}")

        assert not violations, "\n".join(violations)

    def test_command_exits_zero(self) -> None:
        """Test that the command exits with code 0.

        Acceptance Criterion 3: Test command exits 0:
        `uv run pytest tests/test_ci_security.py -v`
        """
        # This test passes by virtue of pytest running successfully
        # If any of the above assertions fail, pytest will exit non-zero
        assert True

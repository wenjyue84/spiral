"""Security tests for html/pages/06-configuration.html"""

import re
from pathlib import Path
from typing import ClassVar


class TestConfigPageSecurity:
    """Verify configuration page contains no hardcoded secrets or credentials."""

    content: ClassVar[str] = ""

    @classmethod
    def setup_class(cls) -> None:
        """Load the configuration HTML file once."""
        config_file = Path(__file__).parent.parent / "html" / "pages" / "06-configuration.html"
        assert config_file.exists(), f"Configuration file not found: {config_file}"
        cls.content = config_file.read_text(encoding="utf-8")

    def test_file_exists(self) -> None:
        """Verify the configuration HTML file exists and is readable."""
        config_file = Path(__file__).parent.parent / "html" / "pages" / "06-configuration.html"
        assert config_file.exists(), "Configuration HTML file must exist"
        assert config_file.is_file(), "Configuration path must be a file"

    def test_no_api_key_patterns(self) -> None:
        """
        Verify no real-looking API key patterns appear in the file.
        Checks for:
        - sk-ant- prefix (Anthropic keys)
        - 40-character hex strings (common for tokens)
        """
        # Pattern for Anthropic API keys or 40-char hex tokens
        api_key_pattern = r"(sk-ant-|[0-9a-f]{40})"
        matches = re.findall(api_key_pattern, self.content, re.IGNORECASE)
        assert len(matches) == 0, f"Found potential API keys: {matches}"

    def test_no_credential_identifiers_in_scripts(self) -> None:
        """
        Verify no script blocks contain credential-like identifiers.
        Checks for: api.key, password, secret (case-insensitive)
        """
        # Extract all script blocks
        script_pattern = r"<script[^>]*>(.*?)</script>"
        scripts = re.findall(script_pattern, self.content, re.DOTALL | re.IGNORECASE)

        for script_content in scripts:
            # Check for credential identifiers
            credential_patterns = r"(api[\s.]*key|password|secret)"
            matches = re.findall(credential_patterns, script_content, re.IGNORECASE)
            assert len(matches) == 0, f"Found credential identifiers in script block: {matches}"

    def test_no_placeholder_violations(self) -> None:
        """Verify all variable examples use proper placeholder strings."""
        # Check for common problematic patterns in config-default spans
        default_pattern = r'<code class="config-default">([^<]+)</code>'
        defaults = re.findall(default_pattern, self.content)

        # These are acceptable placeholder values
        acceptable_patterns = {
            "false",
            "true",
            "—",  # Em dash for empty/unset
            "0",
            "off",
            "git config",
            "auto",
            "dag",
            "parallel",
        }

        for default_text in defaults:
            default_clean = default_text.strip()

            # Skip numeric values and known safe patterns
            if any(
                default_clean.startswith(acceptable)
                for acceptable in [
                    "0",
                    "1",
                    "2",
                    "3",
                    "5",
                    "7",
                    "10",
                    "12",
                    "18",
                    "24",
                    "25",
                    "30",
                    "40",
                    "50",
                    "60",
                    "100",
                    "300",
                    "600",
                    "1",
                ]
            ):
                continue

            if default_clean in acceptable_patterns:
                continue

            # Verify it doesn't look like a real credential
            if re.match(r"[a-f0-9]{20,}", default_clean):
                raise AssertionError(f"Default value looks like hex token: {default_text}")

"""Security tests for html/pages/06-configuration.html.

Verify that the static configuration reference page does not render any actual
secret values, API keys, or tokens — only variable names and descriptions.
"""

import re
from html.parser import HTMLParser
from pathlib import Path


class ConfigAnchorExtractor(HTMLParser):
    """Parse HTML and extract all config anchor IDs."""

    def __init__(self) -> None:
        super().__init__()
        self.anchor_ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("tr", "td", "div", "span", "h3"):
            for name, value in attrs:
                if name == "id" and value and value.startswith("config-"):
                    self.anchor_ids.append(value)


def test_no_secret_patterns() -> None:
    """Verify no high-entropy secret patterns in configuration HTML.

    Check for patterns like: api_key=<20+ alphanumeric chars>, token=..., etc.
    """
    html_path = Path("html/pages/06-configuration.html")
    assert html_path.exists(), f"Missing file: {html_path}"

    content = html_path.read_text(encoding="utf-8")

    # Pattern for secrets: (api_key|token|password|secret) = <20+ alphanumeric chars>
    secret_pattern = re.compile(
        r"(api_key|token|password|secret)\s*=\s*[A-Za-z0-9+/]{20,}",
        re.IGNORECASE,
    )

    matches = secret_pattern.findall(content)

    assert not matches, f"Found potential secret patterns in {html_path}: {matches}"


def test_anchor_ids_present() -> None:
    """Verify that configuration HTML contains anchor IDs for config variables.

    Should have at least 10 anchored variables with id="config-SPIRAL_*" format.
    """
    html_path = Path("html/pages/06-configuration.html")
    assert html_path.exists(), f"Missing file: {html_path}"

    content = html_path.read_text(encoding="utf-8")

    # Parse HTML to find all config anchor IDs
    parser = ConfigAnchorExtractor()
    parser.feed(content)

    # Filter for SPIRAL config anchors
    spiral_anchors = [aid for aid in parser.anchor_ids if "SPIRAL" in aid]

    assert len(spiral_anchors) >= 10, f"Expected at least 10 SPIRAL config anchors, found {len(spiral_anchors)}"


def test_config_anchor_format() -> None:
    """Verify that all config anchors match the expected format.

    Format: id="config-SPIRAL_<UPPERCASE_NAME>"
    """
    html_path = Path("html/pages/06-configuration.html")
    assert html_path.exists(), f"Missing file: {html_path}"

    content = html_path.read_text(encoding="utf-8")

    # Extract all id="config-*" attributes using regex
    anchor_pattern = r'id="(config-[^"]+)"'
    matches = re.findall(anchor_pattern, content)

    assert len(matches) >= 10, f"Expected at least 10 config anchors, found {len(matches)}"

    # Verify format: config-SPIRAL_[A-Z_]+
    valid_pattern = re.compile(r"^config-SPIRAL_[A-Z_0-9]+$")
    for anchor_id in matches:
        assert valid_pattern.match(anchor_id), f"Invalid anchor format: {anchor_id}. Expected config-SPIRAL_<UPPERCASE>"

"""Test that configuration reference page contains all required SPIRAL_* variables with anchors."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup


@pytest.fixture
def config_html_path() -> Path:
    """Return path to configuration HTML page."""
    return Path(__file__).parent.parent / "html" / "pages" / "06-configuration.html"


def test_config_page_exists(config_html_path: Path) -> None:
    """Test that html/pages/06-configuration.html exists and is non-empty."""
    assert config_html_path.exists(), f"Config page not found at {config_html_path}"
    assert config_html_path.stat().st_size > 0, f"Config page is empty at {config_html_path}"


def test_config_page_contains_representative_anchors(config_html_path: Path) -> None:
    """Test that configuration HTML contains anchor elements for SPIRAL_* variables.

    Validates a representative sample of required anchors to ensure deep-links resolve.
    """
    with open(config_html_path, encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")

    # Representative sample of required anchors
    required_anchors = [
        "config-SPIRAL_VALIDATE_CMD",  # from AC: representative sample
        "config-SPIRAL_MAX_PENDING",  # from Loop & Iteration section
        "config-SPIRAL_STORY_BATCH_SIZE",  # from Loop & Iteration section
        "config-SPIRAL_MODEL_ROUTING",  # from Implementation section
    ]

    for anchor_id in required_anchors:
        element = soup.find(id=anchor_id)
        assert element is not None, f"Anchor {anchor_id} not found in configuration page"


def test_config_page_has_multiple_variable_anchors(config_html_path: Path) -> None:
    """Test that configuration page has multiple SPIRAL_* variable anchors."""
    with open(config_html_path, encoding="utf-8") as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, "html.parser")

    # Find all elements with id starting with "config-SPIRAL_"
    config_anchors = [
        elem.get("id") for elem in soup.find_all(id=True) if str(elem.get("id")).startswith("config-SPIRAL_")
    ]

    # Should have a substantial number of anchors
    assert len(config_anchors) >= 50, f"Expected at least 50 SPIRAL_* anchors, found {len(config_anchors)}"

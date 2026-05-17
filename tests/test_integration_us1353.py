"""Integration tests for html/index.html structure (US-1353).

Verifies that the dashboard HTML embeds expected navigation elements,
progress tracking, and data binding for KPI display.
"""

import re
from pathlib import Path

from bs4 import BeautifulSoup


def get_html_path() -> Path:
    """Get the path to html/index.html relative to the repo root."""
    test_dir = Path(__file__).parent
    repo_root = test_dir.parent
    return repo_root / "html" / "index.html"


def test_start_reading_link() -> None:
    """Verify that html/index.html contains a 'Start Reading' link.

    The link should navigate to the first documentation page.
    Tests that either:
    - An anchor with text 'Start Reading' and href containing '01-introduction.html'
    - A button with text 'Start Reading' that calls startReading()
    """
    html_path = get_html_path()
    assert html_path.exists(), f"HTML file not found at {html_path}"

    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    soup = BeautifulSoup(content, "html.parser")

    # Look for "Start Reading" in the content
    found_element = False

    # Check for anchor tag first
    for anchor in soup.find_all("a"):
        if anchor.get_text(strip=True) == "Start Reading":
            href = anchor.get("href", "")
            if "01-introduction.html" in href:
                found_element = True
                break

    # Check for button with onclick handler (alternative implementation)
    if not found_element:
        for button in soup.find_all("button"):
            text = button.get_text(strip=True)
            if text == "Start Reading":
                onclick = button.get("onclick", "")
                if "startReading" in onclick:
                    found_element = True
                    break

    # If button found, verify the startReading function navigates to 01-introduction.html
    if found_element:
        scripts = soup.find_all("script")
        found_navigation = False
        for script in scripts:
            if script.string:
                # Check if the script contains the startReading function
                if "startReading" in script.string and "goToPage" in script.string:
                    # Check if PAGES array has Introduction as first entry
                    # The goToPage function will create pages/01-introduction.html for page 1
                    if "Introduction" in script.string:
                        found_navigation = True
                        break
        assert found_navigation, "'Start Reading' button found but doesn't navigate to introduction page"

    assert found_element, "Could not find 'Start Reading' link/button"


def test_nine_step_progress_strip() -> None:
    """Verify that html/index.html contains exactly 9 progress steps.

    The progress strip is rendered dynamically via JavaScript, so this test
    checks that the PAGES array in the script defines exactly 9 pages.
    """
    html_path = get_html_path()
    assert html_path.exists(), f"HTML file not found at {html_path}"

    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()

    soup = BeautifulSoup(content, "html.parser")

    # Find the script containing PAGES array
    pages_count = 0
    scripts = soup.find_all("script")

    for script in scripts:
        if script.string:
            # Look for PAGES array definition
            if "PAGES" in script.string:
                # Extract the PAGES array definition
                # Pattern: const PAGES = [ ... ];
                match = re.search(r"const PAGES = \[([\s\S]*?)\];", script.string)
                if match:
                    pages_str = match.group(1)
                    # Count objects in the array (count { occurrences)
                    pages_count = pages_str.count("{")
                    break

    assert pages_count == 9, f"Expected 9 progress steps, found {pages_count}"

    # Also verify the progress-strip element exists in the HTML
    progress_strip = soup.find("div", {"id": "progressStrip"})
    assert progress_strip is not None, "progress-strip div not found in HTML"
    assert "progress-strip" in progress_strip.get("class", []), \
        "progress-strip div missing expected CSS class"

"""Test html/pages/06-configuration.html: anchor IDs and category groupings.

Verify that the configuration reference page has proper anchor IDs for SPIRAL_*
variables and that major category headings are present and properly structured.
"""

from pathlib import Path

from bs4 import BeautifulSoup


def test_anchor_ids_present() -> None:
    """Verify that configuration HTML contains at least 10 anchor IDs for config variables.

    Asserts that at least 10 elements with id="config-SPIRAL_*" exist in the HTML.
    """
    html_path = Path("html/pages/06-configuration.html")
    assert html_path.exists(), f"Missing file: {html_path}"

    content = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(content, "html.parser")

    # Find all elements with id starting with config-SPIRAL_
    anchors = []
    for elem in soup.find_all(id=True):
        elem_id = elem.get("id")
        if isinstance(elem_id, str) and elem_id.startswith("config-SPIRAL_"):
            anchors.append(elem_id)

    assert len(anchors) >= 10, f"Expected at least 10 config-SPIRAL_* anchors, found {len(anchors)}"


def test_category_headings_present() -> None:
    """Verify that configuration HTML contains at least 5 category headings.

    Asserts that at least 5 h2 or h3 elements are present (major category headings).
    """
    html_path = Path("html/pages/06-configuration.html")
    assert html_path.exists(), f"Missing file: {html_path}"

    content = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(content, "html.parser")

    # Find all h2 and h3 elements (category headings)
    headings = soup.find_all(["h2", "h3"])

    assert len(headings) >= 5, f"Expected at least 5 category headings (h2/h3), found {len(headings)}"

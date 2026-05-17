"""Integration tests for html/ scaffold created by US-1343.

Tests verify:
1. All expected page files exist on disk (01-09)
2. index.html contains href links to all pages
3. nav.js contains localStorage reference for dark-mode persistence
"""

from html.parser import HTMLParser
from pathlib import Path


class LinkExtractor(HTMLParser):
    """Extract href attributes from HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for attr, value in attrs:
                if attr == "href" and value:
                    self.hrefs.append(value)


def test_scaffold_files_exist() -> None:
    """Verify all expected page files exist: 01-introduction through 09-troubleshooting."""
    html_dir = Path(__file__).parent.parent / "html"
    pages_dir = html_dir / "pages"

    # Expected page filenames based on nav.js NAV_LINKS mapping
    expected_pages = [
        "01-introduction.html",
        "02-quick-start.html",
        "03-architecture.html",
        "04-phase-deep-dive.html",
        "05-cli-reference.html",
        "06-configuration.html",
        "07-examples-and-recipes.html",
        "08-glossary.html",
        "09-troubleshooting.html",
    ]

    for page in expected_pages:
        page_path = pages_dir / page
        assert page_path.exists(), f"Expected page file not found: {page_path}"


def test_index_links_all_pages() -> None:
    """Verify html/index.html contains href links to all pages 01-09."""
    html_dir = Path(__file__).parent.parent / "html"
    index_html = html_dir / "index.html"

    assert index_html.exists(), f"index.html not found: {index_html}"

    # Read and parse index.html
    content = index_html.read_text(encoding="utf-8")
    parser = LinkExtractor()
    parser.feed(content)

    # Verify links to pages 01-09 exist
    page_links = [
        "pages/01-introduction.html",
        "pages/02-quick-start.html",
        "pages/03-architecture.html",
        "pages/04-phase-deep-dive.html",
        "pages/05-cli-reference.html",
        "pages/06-configuration.html",
        "pages/07-examples-and-recipes.html",
        "pages/08-glossary.html",
        "pages/09-troubleshooting.html",
    ]

    for link in page_links:
        assert (
            link in parser.hrefs
        ), f"Expected link not found in index.html: {link}\nFound links: {parser.hrefs}"


def test_nav_js_localstorage() -> None:
    """Verify html/assets/js/nav.js contains 'localStorage' for dark-mode persistence."""
    html_dir = Path(__file__).parent.parent / "html"
    nav_js = html_dir / "assets" / "js" / "nav.js"

    assert nav_js.exists(), f"nav.js not found: {nav_js}"

    content = nav_js.read_text(encoding="utf-8")
    assert (
        "localStorage" in content
    ), "nav.js does not contain 'localStorage' reference for dark-mode persistence"

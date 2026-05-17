"""Unit tests for lib/gen_html_data.py."""

import json
import re

# Import the module under test
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))
from gen_html_data import generate_data_js


def test_data_js_fields(tmp_path: Path) -> None:
    """Verify that gen_html_data.py produces html/data.js with numeric fields.

    Tests that the generated data.js contains:
    - storiesTotal: numeric value
    - storiesPassed: numeric value
    - lastUpdated: ISO timestamp string
    """
    # Create a minimal prd.json with 2 stories for testing
    prd_data = {
        "userStories": [
            {"id": "US-001", "title": "Test story 1", "passes": True},
            {"id": "US-002", "title": "Test story 2", "passes": False},
        ]
    }

    # Write test prd.json to tmp_path
    prd_path = tmp_path / "prd.json"
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd_data, f)

    # Write output to tmp_path
    output_path = tmp_path / "data.js"

    # Generate the data.js file
    generate_data_js(str(output_path), str(prd_path))

    # Read the generated data.js
    assert output_path.exists(), f"Generated file {output_path} does not exist"
    with open(output_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Strip JavaScript wrapper to extract the data object
    # Pattern: window.SPIRAL_DATA = {...};
    match = re.search(r"window\.SPIRAL_DATA = ({[\s\S]*?});", content)
    assert match, "Could not find window.SPIRAL_DATA object in generated file"

    data_str = match.group(1)

    # Extract storiesTotal
    stories_total_match = re.search(r"storiesTotal:\s*(\d+)", data_str)
    assert stories_total_match, "storiesTotal field missing"
    stories_total = int(stories_total_match.group(1))

    # Extract storiesPassed
    stories_passed_match = re.search(r"storiesPassed:\s*(\d+)", data_str)
    assert stories_passed_match, "storiesPassed field missing"
    stories_passed = int(stories_passed_match.group(1))

    # Extract lastUpdated
    last_updated_match = re.search(r'lastUpdated:\s*"([^"]+)"', data_str)
    assert last_updated_match, "lastUpdated field missing"
    last_updated = last_updated_match.group(1)

    # Verify types
    assert isinstance(stories_total, int), "storiesTotal must be numeric"
    assert isinstance(stories_passed, int), "storiesPassed must be numeric"
    assert isinstance(last_updated, str), "lastUpdated must be a string"

    # Verify values are correct for our test data
    assert stories_total == 2, f"storiesTotal should be 2, got {stories_total}"
    assert stories_passed == 1, f"storiesPassed should be 1, got {stories_passed}"
    assert len(last_updated) > 0, "lastUpdated should not be empty"

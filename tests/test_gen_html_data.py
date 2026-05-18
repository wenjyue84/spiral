"""Unit tests for lib/gen_html_data.py."""

import json
import re

# Import the module under test
import sys
from pathlib import Path

import pytest

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


def test_us_1353_missing_prd_json(tmp_path: Path) -> None:
    """Test that missing prd.json raises FileNotFoundError.

    Verifies that generate_data_js() raises a clear error (FileNotFoundError)
    when prd.json does not exist.
    """
    # Point to a prd.json that does not exist
    prd_path = tmp_path / "nonexistent.json"
    output_path = tmp_path / "data.js"

    # Should raise FileNotFoundError
    with pytest.raises(FileNotFoundError):
        generate_data_js(str(output_path), str(prd_path))


def test_us_1353_malformed_prd_json(tmp_path: Path) -> None:
    """Test that malformed prd.json raises JSONDecodeError.

    Verifies that generate_data_js() raises a clear error (JSONDecodeError)
    when prd.json contains invalid JSON.
    """
    # Create a prd.json with invalid JSON content
    prd_path = tmp_path / "prd.json"
    with open(prd_path, "w", encoding="utf-8") as f:
        f.write("{invalid json content")

    output_path = tmp_path / "data.js"

    # Should raise JSONDecodeError
    with pytest.raises(json.JSONDecodeError):
        generate_data_js(str(output_path), str(prd_path))


def test_kpi_keys_present(tmp_path: Path) -> None:
    """Verify that gen_html_data.py produces html/data.js with all KPI keys.

    Tests that the generated data.js contains the KPI keys:
    - storiesTotal: numeric count of all stories
    - storiesPassed: numeric count of passed stories
    - lastUpdated: ISO timestamp string
    """
    prd_data = {
        "userStories": [
            {"id": "US-001", "title": "Story A", "passes": True},
            {"id": "US-002", "title": "Story B", "passes": True},
            {"id": "US-003", "title": "Story C", "passes": False},
        ]
    }
    prd_path = tmp_path / "prd.json"
    with open(prd_path, "w", encoding="utf-8") as f:
        json.dump(prd_data, f)

    output_path = tmp_path / "data.js"
    generate_data_js(str(output_path), str(prd_path))

    assert output_path.exists(), "data.js was not created"
    content = output_path.read_text(encoding="utf-8")

    # All KPI keys must be present
    assert re.search(r"storiesTotal\s*:", content), "storiesTotal key missing from data.js"
    assert re.search(r"storiesPassed\s*:", content), "storiesPassed key missing from data.js"
    assert re.search(r"lastUpdated\s*:", content), "lastUpdated key missing from data.js"

    # Values must be correct
    total_match = re.search(r"storiesTotal:\s*(\d+)", content)
    passed_match = re.search(r"storiesPassed:\s*(\d+)", content)
    assert total_match and int(total_match.group(1)) == 3, "storiesTotal should be 3"
    assert passed_match and int(passed_match.group(1)) == 2, "storiesPassed should be 2"


def test_missing_prd_raises(tmp_path: Path) -> None:
    """Verify gen_html_data.py raises a clear error when prd.json is missing.

    Tests that generate_data_js() raises FileNotFoundError when the prd.json
    path does not exist, providing a clear diagnostic to the caller.
    """
    prd_path = tmp_path / "does_not_exist.json"
    output_path = tmp_path / "data.js"

    with pytest.raises(FileNotFoundError):
        generate_data_js(str(output_path), str(prd_path))

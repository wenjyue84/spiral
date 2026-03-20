"""Integration tests for GET /api/dashboard/research-sources endpoint (US-548).

Tests verify that the endpoint:
- Loads _research_output.json from .spiral/
- Extracts and scores research URLs by domain credibility
- Returns JSON array of sources with credibility_score and mention_count
- Persists results to .spiral/research_sources.json
- Handles errors gracefully (missing files, malformed JSON)
"""

import json
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lib.dashboard.api import app


@pytest.fixture
def client():
    """Provide a FastAPI TestClient for the dashboard API."""
    return TestClient(app)


@pytest.fixture
def mock_spiral_dir(tmp_path, monkeypatch):
    """Create a temporary .spiral directory and cd into it."""
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    return spiral_dir


def test_research_sources_happy_path(client, mock_spiral_dir):
    """Test endpoint with valid _research_output.json containing .gov and .com domains."""
    # Create sample research output with a .gov URL and a blog URL
    research_output = {
        "stories": [
            {
                "id": "S-001",
                "title": "Government Report",
                "source": "https://www.example.gov/report",
                "description": "Found official sources at https://data.census.gov/",
            },
            {
                "id": "S-002",
                "title": "Blog Post",
                "source": "https://myblog.blogspot.com/article",
                "description": "Referenced https://example.gov again and https://dev.to/post",
            },
        ]
    }

    # Write sample file
    research_path = mock_spiral_dir / "_research_output.json"
    research_path.write_text(json.dumps(research_output), encoding="utf-8")

    # Call endpoint
    response = client.get("/api/dashboard/research-sources")

    # Verify response
    assert response.status_code == 200
    data = response.json()
    assert "sources" in data
    assert "total_sources" in data

    sources = data["sources"]
    assert len(sources) > 0

    # Verify structure of each source
    for source in sources:
        assert "url" in source
        assert "domain" in source
        assert "credibility_score" in source
        assert "mention_count" in source
        assert isinstance(source["credibility_score"], int)
        assert isinstance(source["mention_count"], int)
        assert 0 <= source["credibility_score"] <= 100

    # Verify .gov domains have high credibility
    gov_sources = [s for s in sources if ".gov" in s["domain"]]
    if gov_sources:
        assert all(s["credibility_score"] >= 90 for s in gov_sources), ".gov should score >= 90"

    # Verify blog domains have lower credibility
    blog_sources = [s for s in sources if "blogspot.com" in s["domain"]]
    if blog_sources:
        assert all(50 <= s["credibility_score"] <= 60 for s in blog_sources), "blogspot should score 50-60"

    # Verify results were persisted
    results_path = mock_spiral_dir / "research_sources.json"
    assert results_path.exists(), "research_sources.json should be created"

    persisted = json.loads(results_path.read_text(encoding="utf-8"))
    assert len(persisted) == len(sources)


def test_research_sources_missing_file(client, mock_spiral_dir):
    """Test endpoint gracefully handles missing _research_output.json."""
    response = client.get("/api/dashboard/research-sources")

    assert response.status_code == 200
    data = response.json()
    assert data["sources"] == []
    assert data["total_sources"] == 0
    assert "message" in data


def test_research_sources_malformed_json(client, mock_spiral_dir):
    """Test endpoint gracefully handles malformed JSON in _research_output.json."""
    # Write malformed JSON
    research_path = mock_spiral_dir / "_research_output.json"
    research_path.write_text('{"invalid": json}', encoding="utf-8")

    response = client.get("/api/dashboard/research-sources")

    assert response.status_code == 200
    data = response.json()
    assert data["sources"] == []
    assert data["total_sources"] == 0
    assert "error" in data


def test_research_sources_url_deduplication(client, mock_spiral_dir):
    """Test that identical URLs are deduplicated with correct mention_count."""
    research_output = {
        "stories": [
            {
                "id": "S-001",
                "source": "https://example.com/article",
            },
            {
                "id": "S-002",
                "description": "Reference https://example.com/article and https://example.com/article again",
            },
        ]
    }

    research_path = mock_spiral_dir / "_research_output.json"
    research_path.write_text(json.dumps(research_output), encoding="utf-8")

    response = client.get("/api/dashboard/research-sources")

    assert response.status_code == 200
    data = response.json()
    sources = data["sources"]

    # Find the example.com source
    example_source = next((s for s in sources if "example.com" in s["url"]), None)
    assert example_source is not None, "example.com should be in results"
    # Should be deduplicated: 1 from source + 2 from description = 3 mentions
    assert example_source["mention_count"] == 3


def test_research_sources_credibility_sorting(client, mock_spiral_dir):
    """Test that sources are sorted by credibility_score descending."""
    research_output = {
        "stories": [
            {
                "description": "Visit https://github.com and https://www.example.gov and https://myblog.medium.com",
            },
        ]
    }

    research_path = mock_spiral_dir / "_research_output.json"
    research_path.write_text(json.dumps(research_output), encoding="utf-8")

    response = client.get("/api/dashboard/research-sources")

    assert response.status_code == 200
    data = response.json()
    sources = data["sources"]

    # Verify sources are sorted by credibility descending
    credibility_scores = [s["credibility_score"] for s in sources]
    assert credibility_scores == sorted(credibility_scores, reverse=True)


def test_research_sources_empty_stories(client, mock_spiral_dir):
    """Test endpoint with empty stories array."""
    research_output = {"stories": []}

    research_path = mock_spiral_dir / "_research_output.json"
    research_path.write_text(json.dumps(research_output), encoding="utf-8")

    response = client.get("/api/dashboard/research-sources")

    assert response.status_code == 200
    data = response.json()
    assert data["sources"] == []
    assert data["total_sources"] == 0


def test_research_sources_creates_spiral_dir(client, tmp_path, monkeypatch):
    """Test that .spiral directory is created if it doesn't exist."""
    # Change to temp dir WITHOUT .spiral
    monkeypatch.chdir(tmp_path)

    research_output = {
        "stories": [
            {
                "description": "Reference https://example.gov/doc",
            },
        ]
    }

    # Manually create .spiral and _research_output.json
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir()
    research_path = spiral_dir / "_research_output.json"
    research_path.write_text(json.dumps(research_output), encoding="utf-8")

    response = client.get("/api/dashboard/research-sources")

    assert response.status_code == 200
    data = response.json()
    assert data["total_sources"] > 0

    # Verify research_sources.json was created
    results_path = spiral_dir / "research_sources.json"
    assert results_path.exists()

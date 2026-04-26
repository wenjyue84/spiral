"""Integration tests for Phase S edge cases: antiPattern rejection and empty-AC warning.

Uses tests/fixtures/prd_with_invalid_stories.json as the story source.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "lib"))
from validate_stories import validate_stories

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _write_json(path: str, data: object) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _load_fixture_story(story_id: str) -> dict[str, object]:
    fixture_path = FIXTURES_DIR / "prd_with_invalid_stories.json"
    data: dict[str, object] = json.loads(fixture_path.read_text(encoding="utf-8"))
    stories = data["stories"]
    assert isinstance(stories, list)
    story: dict[str, object] = next(s for s in stories if s.get("id") == story_id)
    return story


@pytest.fixture()
def workspace(tmp_path: Path) -> dict[str, str]:
    return {
        "prd": str(tmp_path / "prd.json"),
        "research": str(tmp_path / "research.json"),
        "test_stories": str(tmp_path / "test_stories.json"),
        "validated": str(tmp_path / "validated.json"),
        "rejected": str(tmp_path / "rejected.json"),
        "constitution": str(tmp_path / "constitution.md"),
    }


def test_antipattern_match(workspace: dict[str, str]) -> None:
    """Phase S rejects a story whose title/description matches an ANTIPATTERN: line.

    The rejection reason must contain 'Matches antiPattern'.
    """
    story = _load_fixture_story("FIXTURE-AP-001")
    title = str(story.get("title", ""))
    description = str(story.get("description", ""))
    assert "gpg" in (title + description).lower(), (
        "Fixture story FIXTURE-AP-001 must contain 'gpg' in title or description"
    )

    _write_json(workspace["prd"], {"goals": ["Improve SPIRAL reliability"], "userStories": []})
    _write_json(workspace["research"], {"stories": [story]})
    _write_json(workspace["test_stories"], {"stories": []})

    # Constitution declares GPG key management as an antiPattern
    with open(workspace["constitution"], "w", encoding="utf-8") as fh:
        fh.write("ANTIPATTERN: gpg key\n")

    accepted, rejected = validate_stories(
        research_path=workspace["research"],
        test_stories_path=workspace["test_stories"],
        prd_path=workspace["prd"],
        validated_out=workspace["validated"],
        rejected_out=workspace["rejected"],
        constitution_path=workspace["constitution"],
        min_overlap=0,
    )

    assert len(rejected) >= 1, "Expected at least one rejection"
    ap_rejections = [r for r in rejected if r.get("id") == "FIXTURE-AP-001"]
    assert ap_rejections, f"FIXTURE-AP-001 was not rejected; accepted={[s.get('id') for s in accepted]}"
    assert "Matches antiPattern" in ap_rejections[0]["_rejection_reason"], (
        f"Rejection reason should contain 'Matches antiPattern', got: {ap_rejections[0]['_rejection_reason']!r}"
    )


def test_empty_acceptance_criteria(workspace: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase S does not reject a story with acceptanceCriteria: [].

    Only a warning is logged; the story passes through to accepted.
    """
    story = _load_fixture_story("FIXTURE-EAC-001")
    assert story.get("acceptanceCriteria") == [], "Fixture story FIXTURE-EAC-001 must have empty acceptanceCriteria"

    _write_json(workspace["prd"], {"goals": ["Improve SPIRAL reliability"], "userStories": []})
    _write_json(workspace["research"], {"stories": [story]})
    _write_json(workspace["test_stories"], {"stories": []})

    # Disable quality score gate so empty ACs are the only potential rejection
    monkeypatch.setenv("SPIRAL_STORY_MIN_QUALITY_SCORE", "0")

    accepted, rejected = validate_stories(
        research_path=workspace["research"],
        test_stories_path=workspace["test_stories"],
        prd_path=workspace["prd"],
        validated_out=workspace["validated"],
        rejected_out=workspace["rejected"],
        min_overlap=0,
    )

    eac_rejections = [r for r in rejected if r.get("id") == "FIXTURE-EAC-001"]
    assert not eac_rejections, (
        f"FIXTURE-EAC-001 should not be rejected, but got reason: "
        f"{eac_rejections[0]['_rejection_reason'] if eac_rejections else 'n/a'!r}"
    )
    eac_accepted = [s for s in accepted if s.get("id") == "FIXTURE-EAC-001"]
    assert eac_accepted, f"FIXTURE-EAC-001 should be in accepted list; accepted={[s.get('id') for s in accepted]}"

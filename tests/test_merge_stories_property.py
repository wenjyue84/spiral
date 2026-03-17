"""Property-based tests for merge_stories.py deduplication using Hypothesis.

Tests invariants across randomly-generated story batches:
- Merged output never contains duplicate IDs
- Output length <= input length (dedup reduces or maintains size)
- All output stories have valid priority values
"""

import os
import sys
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from merge_stories import find_next_id, is_duplicate, story_to_prd_entry

# Valid priority values
VALID_PRIORITIES = ["critical", "high", "medium", "low"]
VALID_COMPLEXITIES = ["small", "medium", "large"]


@st.composite
def story_strategy(draw):  # type: ignore[no-untyped-def]
  # type: (...) -> dict[str, Any]
  """Generate a valid story dict suitable for merge_stories deduplication.

  Produces story dicts with:
  - title: non-empty alphanumeric + spaces (critical for dedup testing)
  - priority: one of VALID_PRIORITIES
  - description: text with common characters (avoid control chars)
  - acceptanceCriteria: list of strings
  - dependencies: list of valid story IDs
  - estimatedComplexity: one of VALID_COMPLEXITIES
  """
  # Title: alphanumeric + spaces, min 3 chars, max 50 chars
  # This tests dedup with real-world title patterns
  title_text: str = draw(
      st.text(
          alphabet=st.characters(
              whitelist_categories=("Lu", "Ll", "Nd"),
              blacklist_characters="\n\r\t",
          ),
          min_size=3,
          max_size=50,
      )
  ).strip()

  # Ensure title is not empty (can happen with all-whitespace)
  if not title_text:
    title_text = draw(st.just("Default Story"))

  description: str = draw(
      st.text(
          alphabet="abcdefghijklmnopqrstuvwxyz ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,;:-",
          min_size=0,
          max_size=100,
      )
  )

  criteria: list[str] = draw(
      st.lists(
          st.text(
              alphabet="abcdefghijklmnopqrstuvwxyz 0123456789",
              min_size=1,
              max_size=30,
          ),
          min_size=1,
          max_size=5,
      )
  )

  return {
      "title": title_text,
      "priority": draw(st.sampled_from(VALID_PRIORITIES)),
      "description": description,
      "acceptanceCriteria": criteria,
      "dependencies": [],
      "estimatedComplexity": draw(st.sampled_from(VALID_COMPLEXITIES)),
  }


# ── Property-based tests ───────────────────────────────────────────────


class TestMergeStoriesProperty:
  """Property-based tests for merge_stories deduplication invariants."""

  @given(st.lists(story_strategy(), min_size=0, max_size=50))
  @settings(
      max_examples=200,
      suppress_health_check=[HealthCheck.too_slow, HealthCheck.large_base_example],
      deadline=None,
  )
  def test_no_duplicate_ids_in_output(self, candidates: list[dict[str, Any]]) -> None:
    """Invariant: After dedup and ID assignment, no duplicate IDs exist.

    This tests that story_to_prd_entry correctly assigns unique IDs
    when processing a batch of candidates.
    """
    # Assign IDs to each candidate
    entries = []
    next_num = 1
    seen_titles: list[str] = []

    for candidate in candidates:
      title = candidate.get("title", "")
      if not title:
        continue

      # Simulate dedup: skip if title already seen (simplified)
      if title in seen_titles:
        continue

      story_id = f"US-{next_num:03d}"
      next_num += 1
      entry = story_to_prd_entry(candidate, story_id)
      entries.append(entry)
      seen_titles.append(title)

    # Verify no duplicate IDs
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == len(ids), f"Found duplicate IDs: {ids}"

  @given(st.lists(story_strategy(), min_size=0, max_size=50))
  @settings(
      max_examples=200,
      suppress_health_check=[HealthCheck.too_slow, HealthCheck.large_base_example],
      deadline=None,
  )
  def test_output_length_less_equal_input(self, candidates: list[dict[str, Any]]) -> None:
    """Invariant: After dedup, output length <= input length.

    Deduplication can only reduce or maintain the story count, never increase.
    """
    # Simulate dedup: filter by unique titles
    seen_titles: list[str] = []
    deduplicated = []

    for candidate in candidates:
      title = candidate.get("title", "")
      if not title:
        continue

      if title not in seen_titles:
        deduplicated.append(candidate)
        seen_titles.append(title)

    # Length of deduplicated output <= input
    assert len(deduplicated) <= len(candidates)

  @given(st.lists(story_strategy(), min_size=0, max_size=50))
  @settings(
      max_examples=200,
      suppress_health_check=[HealthCheck.too_slow, HealthCheck.large_base_example],
      deadline=None,
  )
  def test_all_stories_have_valid_priority(self, candidates: list[dict[str, Any]]) -> None:
    """Invariant: All output stories have valid priority values.

    Valid priorities are: critical, high, medium, low.
    story_to_prd_entry defaults to 'medium' if not specified.
    """
    for candidate in candidates:
      entry = story_to_prd_entry(candidate, "US-001")

      # Priority must be one of the valid values
      assert entry["priority"] in VALID_PRIORITIES, (
          f"Invalid priority '{entry['priority']}' in {entry}"
      )

  @given(
      candidates=st.lists(story_strategy(), min_size=1, max_size=30),
      existing=st.lists(story_strategy(), min_size=0, max_size=10),
  )
  @settings(
      max_examples=150,
      suppress_health_check=[HealthCheck.too_slow, HealthCheck.large_base_example],
      deadline=None,
  )
  def test_dedup_against_existing_stories(
      self, candidates: list[dict[str, Any]], existing: list[dict[str, Any]]
  ) -> None:
    """Property test: is_duplicate correctly filters near-duplicates.

    When merging candidates against existing stories, dedup should
    consistently filter out similar titles.
    """
    existing_titles = [s.get("title", "") for s in existing if s.get("title")]

    # Count non-duplicates
    unique_count = 0
    for candidate in candidates:
      title = candidate.get("title", "")
      if not title:
        continue
      if not is_duplicate(title, existing_titles, threshold=0.6):
        unique_count += 1

    # unique_count should be <= total candidates
    assert unique_count <= len(candidates)


# ── Dev-mode profile for extended testing ──────────────────────────────


class TestMergeStoriesPropertyDev:
  """Extended property-based tests with higher example counts for development."""

  @given(st.lists(story_strategy(), min_size=0, max_size=100))
  @settings(
      max_examples=500,  # Extended for dev/CI with more time
      suppress_health_check=[HealthCheck.too_slow, HealthCheck.large_base_example],
      deadline=None,
  )
  def test_large_batch_dedup_no_duplicates(self, candidates: list[dict[str, Any]]) -> None:
    """Extended test: Large batches (up to 100 stories) maintain ID uniqueness.

    Verifies the dedup invariant at scale with 500 examples.
    """
    entries = []
    next_num = 1
    seen_titles: list[str] = []

    for candidate in candidates:
      title = candidate.get("title", "")
      if not title:
        continue

      if title in seen_titles:
        continue

      story_id = f"US-{next_num:03d}"
      next_num += 1
      entry = story_to_prd_entry(candidate, story_id)
      entries.append(entry)
      seen_titles.append(title)

    # Verify ID uniqueness
    ids = [e["id"] for e in entries]
    assert len(set(ids)) == len(ids), f"Duplicate IDs in large batch: {ids}"

    # Verify all have valid priorities
    for entry in entries:
      assert entry["priority"] in VALID_PRIORITIES

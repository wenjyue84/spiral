"""Shared @st.composite strategy generators for SPIRAL property-based tests.

Exports:
    story_strategy()         — generates a single valid story with a US-NNN ID
    prd_strategy()           — generates a list of stories with no duplicate IDs
    research_batch_strategy() — generates research candidate stories (no IDs)

Usage in tests::

    from strategies import prd_strategy, story_strategy, research_batch_strategy

    @given(prd_strategy())
    def test_invariant(stories):
        ...

    @given(story_strategy())
    def test_single_story(story):
        ...
"""

from hypothesis import assume
from hypothesis import strategies as st

SOURCES = ["test-fix", "research", "seed", "ai-example"]
PRIORITIES = ["critical", "high", "medium", "low"]
COMPLEXITIES = ["small", "medium", "large"]

_title_st = st.from_regex(r"[A-Za-z][A-Za-z0-9 _-]{2,30}", fullmatch=True)
_desc_st = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz 0123456789.,",
    min_size=0,
    max_size=60,
)
_ac_item_st = st.from_regex(r"[A-Za-z][A-Za-z0-9 ]{2,20}", fullmatch=True)
_id_st = st.from_regex(r"US-[0-9]{3,4}", fullmatch=True)


@st.composite
def story_strategy(draw, available_ids=None):
    """Generate a single valid story with a US-NNN ID.

    Args:
        available_ids: Optional list of existing story IDs to sample
                       dependencies from. Dependencies will only reference
                       IDs in this pool, ensuring referential integrity.

    Returns:
        A dict with id, title, priority, description, acceptanceCriteria,
        dependencies, estimatedComplexity, _source, and passes fields.
    """
    story_id = draw(_id_st)
    assume(len(story_id) >= 6)  # US-NNN minimum length guard

    source = draw(st.sampled_from(SOURCES))
    # test-fix stories correlate with higher urgency — model the correlation
    if source == "test-fix":
        priority = draw(st.sampled_from(["critical", "high", "medium"]))
    else:
        priority = draw(st.sampled_from(PRIORITIES))

    complexity = draw(st.sampled_from(COMPLEXITIES))

    # Dependencies must reference IDs within the same generated batch
    if available_ids:
        other_ids = [aid for aid in available_ids if aid != story_id]
        if other_ids:
            deps = draw(
                st.lists(
                    st.sampled_from(other_ids),
                    max_size=min(3, len(other_ids)),
                    unique=True,
                )
            )
        else:
            deps = []
    else:
        deps = []

    return {
        "id": story_id,
        "title": draw(_title_st),
        "priority": priority,
        "description": draw(_desc_st),
        "acceptanceCriteria": draw(st.lists(_ac_item_st, min_size=1, max_size=3)),
        "dependencies": deps,
        "estimatedComplexity": complexity,
        "_source": source,
        "passes": draw(st.booleans()),
    }


@st.composite
def prd_strategy(draw, min_size=1, max_size=20):
    """Generate a list of stories with no duplicate IDs.

    Uses sequential IDs (US-001, US-002, ...) to guarantee uniqueness
    without retry loops. Dependencies only reference earlier IDs in the
    sequence, producing a valid forward-only DAG.

    Args:
        min_size: Minimum number of stories to generate.
        max_size: Maximum number of stories to generate.

    Returns:
        A list of story dicts, each with the same fields as story_strategy().
    """
    size = draw(st.integers(min_value=min_size, max_value=max_size))
    stories = []

    for i in range(size):
        story_id = f"US-{i + 1:03d}"
        # Earlier IDs only — guarantees forward-only deps (no cycles)
        earlier_ids = [f"US-{j + 1:03d}" for j in range(i)]

        if earlier_ids:
            deps = draw(
                st.lists(
                    st.sampled_from(earlier_ids),
                    max_size=min(3, len(earlier_ids)),
                    unique=True,
                )
            )
        else:
            deps = []

        source = draw(st.sampled_from(SOURCES))
        if source == "test-fix":
            priority = draw(st.sampled_from(["critical", "high", "medium"]))
        else:
            priority = draw(st.sampled_from(PRIORITIES))

        stories.append(
            {
                "id": story_id,
                "title": draw(_title_st),
                "priority": priority,
                "description": draw(_desc_st),
                "acceptanceCriteria": draw(st.lists(_ac_item_st, min_size=1, max_size=3)),
                "dependencies": deps,
                "estimatedComplexity": draw(st.sampled_from(COMPLEXITIES)),
                "_source": source,
                "passes": draw(st.booleans()),
            }
        )

    # Guard: all IDs must be unique (belt-and-suspenders with sequential IDs)
    all_ids = [s["id"] for s in stories]
    assume(len(set(all_ids)) == len(all_ids))

    return stories


@st.composite
def research_batch_strategy(draw, min_size=1, max_size=10):
    """Generate a batch of research candidate stories (without assigned IDs).

    Research candidates are the raw output of Phase R — they haven't been
    assigned US-NNN IDs yet and carry no inter-story dependency references.

    Args:
        min_size: Minimum number of candidates to generate.
        max_size: Maximum number of candidates to generate.

    Returns:
        A list of candidate dicts with title, priority, description,
        acceptanceCriteria, dependencies, estimatedComplexity, _source.
    """
    size = draw(st.integers(min_value=min_size, max_value=max_size))

    candidates = []
    seen_titles: set = set()

    for _ in range(size):
        title = draw(_title_st)
        # Guard: no duplicate titles within the same batch
        assume(title not in seen_titles)
        seen_titles.add(title)

        source = draw(st.sampled_from(SOURCES))
        if source == "test-fix":
            priority = draw(st.sampled_from(["critical", "high", "medium"]))
        else:
            priority = draw(st.sampled_from(PRIORITIES))

        candidates.append(
            {
                "title": title,
                "priority": priority,
                "description": draw(_desc_st),
                "acceptanceCriteria": draw(st.lists(_ac_item_st, min_size=1, max_size=3)),
                "dependencies": [],
                "estimatedComplexity": draw(st.sampled_from(COMPLEXITIES)),
                "_source": source,
            }
        )

    # Guard: unique titles across the batch
    titles = [c["title"] for c in candidates]
    assume(len(set(titles)) == len(titles))

    return candidates

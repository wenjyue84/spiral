#!/usr/bin/env python3
"""Decompose stuck stories into atomic sub-stories."""
import json

with open("prd.json", encoding="utf-8") as f:
    data = json.load(f)

stories = data["userStories"]

new_stories = [
    # US-350 decomposition: episodic memory
    {
        "id": "US-432",
        "title": "Create lib/episodic_memory.py with SQLite FTS5 schema and CRUD",
        "priority": "medium",
        "estimatedComplexity": "small",
        "description": "Create lib/episodic_memory.py with init_db(db_path), write_record(db_path, record_dict), query_top3(db_path, title). SQLite FTS5, no external deps. Schema: story_id, story_type, approach_summary, outcome, iteration, timestamp.",
        "acceptanceCriteria": [
            "lib/episodic_memory.py exists with init_db, write_record, query_top3",
            "init_db() creates .spiral/episodic_memory.db with FTS5 virtual table if not exists",
            "query_top3() returns up to 3 rows ordered by FTS5 rank",
            "uv run pytest tests/test_episodic_memory.py -v passes with at least a write+query round-trip test",
        ],
        "technicalNotes": ["stdlib sqlite3 only — no external deps", "keep under 120 lines"],
        "dependencies": [],
        "passes": False,
        "_decomposedFrom": "US-350",
    },
    {
        "id": "US-433",
        "title": "Write episodic record after successful Ralph story in commit_revert.sh",
        "priority": "medium",
        "estimatedComplexity": "small",
        "description": "After a story passes, lib/impl/commit_revert.sh calls python lib/episodic_memory.py write with approach_summary from last progress.txt section for this story_id, outcome=pass. Gated by SPIRAL_EPISODIC_MEMORY=true.",
        "acceptanceCriteria": [
            "commit_revert.sh calls episodic_memory.py write after a successful commit",
            'Call is gated by [[ "${SPIRAL_EPISODIC_MEMORY:-false}" == "true" ]]',
            "approach_summary extracted from last progress.txt section matching the story id",
            "Errors from episodic_memory.py are silently ignored with || true",
        ],
        "technicalNotes": ["One bash line — python call only", "Do not break existing commit flow"],
        "dependencies": ["US-432"],
        "passes": False,
        "_decomposedFrom": "US-350",
    },
    {
        "id": "US-434",
        "title": "Inject top-3 episodic memory records into Ralph user prompt",
        "priority": "medium",
        "estimatedComplexity": "small",
        "description": "In ralph.sh, before spawning Claude, query episodic_memory.db top-3 by story title. Append as ## Episodic Memory section to RALPH_USER_PROMPT. Gated by SPIRAL_EPISODIC_MEMORY=true and db file existence.",
        "acceptanceCriteria": [
            "ralph.sh queries lib/episodic_memory.py query_top3 with STORY_TITLE",
            "Results appended to RALPH_USER_PROMPT as markdown ## Episodic Memory section",
            'Gated by SPIRAL_EPISODIC_MEMORY=true and -f "$_EPISODIC_DB" check',
            "Silently omitted when db is empty or missing",
        ],
        "technicalNotes": ["Find existing US-427 episodic injection stub in ralph.sh and extend it"],
        "dependencies": ["US-432"],
        "passes": False,
        "_decomposedFrom": "US-350",
    },
    {
        "id": "US-435",
        "title": "Add spiral memory list CLI subcommand for episodic records",
        "priority": "low",
        "estimatedComplexity": "small",
        "description": "Add memory subcommand to main.py printing 20 most recent episodic records as a table (story_id, outcome, timestamp, approach_summary truncated to 60 chars). Graceful if db missing.",
        "acceptanceCriteria": [
            "python main.py memory list prints table of up to 20 records",
            "If db missing prints 'No episodic memory found'",
            "Columns: story_id, outcome, timestamp, approach_summary (60 char truncated)",
            "python main.py --help shows memory subcommand",
        ],
        "technicalNotes": ["Add to existing argparse subcommands in main.py"],
        "dependencies": ["US-432"],
        "passes": False,
        "_decomposedFrom": "US-350",
    },
    # US-352 decomposition: velocity model
    {
        "id": "US-436",
        "title": "Create lib/velocity_model.py with results.tsv parsing and story-type classification",
        "priority": "low",
        "estimatedComplexity": "small",
        "description": "lib/velocity_model.py reads results.tsv and classifies rows into story types by title keyword: OTel->observability, test->testing, CI->ci, fix->bugfix, feat->feature, other. Returns dict of story_type -> list of records.",
        "acceptanceCriteria": [
            "lib/velocity_model.py has classify_story_type(title) -> str and load_results(tsv_path) -> dict",
            "At least 6 keyword categories: observability, testing, ci, bugfix, feature, other",
            "load_results returns {story_type: [{cost, duration, status}]} grouped by type",
            "uv run pytest tests/test_velocity_model.py -v passes with at least 3 unit tests",
        ],
        "technicalNotes": ["csv.DictReader for tsv parsing", "keep under 80 lines"],
        "dependencies": [],
        "passes": False,
        "_decomposedFrom": "US-352",
    },
    {
        "id": "US-437",
        "title": "Add --report flag to python main.py estimate with empirical velocity table",
        "priority": "low",
        "estimatedComplexity": "small",
        "description": "python main.py estimate --report prints table: story_type, samples, mean_cost, mean_duration_s, empirical_pass_rate. Types with <5 samples show n/a. Uses lib/velocity_model.py.",
        "acceptanceCriteria": [
            "python main.py estimate --report prints formatted table with the columns above",
            "Types with >=5 samples show empirical means; others show n/a (insufficient data)",
            "Missing or empty results.tsv prints 'No historical data available'",
            "Existing python main.py estimate behavior without --report is unchanged",
        ],
        "technicalNotes": ["Add --report to the estimate subparser in main.py"],
        "dependencies": ["US-436"],
        "passes": False,
        "_decomposedFrom": "US-352",
    },
    {
        "id": "US-438",
        "title": "Persist velocity model to .spiral/velocity_model.json with mtime cache",
        "priority": "low",
        "estimatedComplexity": "small",
        "description": "After computing the velocity model, save aggregated stats to .spiral/velocity_model.json. On next run, load from JSON if results.tsv mtime is unchanged. Allows offline and fast re-use.",
        "acceptanceCriteria": [
            ".spiral/velocity_model.json written after each estimate run with {story_type: {samples, mean_cost, mean_duration, pass_rate}}",
            "If json exists and results.tsv mtime unchanged, load from json without recomputing",
            "python main.py estimate --report reflects persisted model when tsv is unchanged",
            "File is written to .spiral/ (already gitignored)",
        ],
        "technicalNotes": ["os.path.getmtime() for mtime comparison", "json.dump with indent=2"],
        "dependencies": ["US-436", "US-437"],
        "passes": False,
        "_decomposedFrom": "US-352",
    },
    # US-382 decomposition: CI composite actions
    {
        "id": "US-439",
        "title": "Create .github/actions/setup-uv/action.yml composite action",
        "priority": "low",
        "estimatedComplexity": "small",
        "description": "Create .github/actions/setup-uv/action.yml composite action encapsulating: checkout, setup-python with pyproject.toml version file, astral-sh/setup-uv, and uv sync --frozen. All third-party refs pinned to full commit SHAs.",
        "acceptanceCriteria": [
            ".github/actions/setup-uv/action.yml exists with runs: using: composite",
            "Steps include: checkout, setup-python, astral-sh/setup-uv, uv sync --frozen",
            "All third-party action refs use full commit SHAs not version tags",
            "yamllint passes on the new action file with no errors",
        ],
        "technicalNotes": [
            "Copy existing SHA pins from .github/workflows/ files",
            "Composite actions use runs: using: composite with steps:",
        ],
        "dependencies": [],
        "passes": False,
        "_decomposedFrom": "US-382",
    },
    {
        "id": "US-440",
        "title": "Create lint-shell composite action and migrate all workflows to use both composites",
        "priority": "low",
        "estimatedComplexity": "small",
        "description": "Create .github/actions/lint-shell/action.yml encapsulating shellcheck and shfmt. Update all .github/workflows/*.yml files to call ./.github/actions/setup-uv and ./.github/actions/lint-shell instead of duplicated raw steps.",
        "acceptanceCriteria": [
            ".github/actions/lint-shell/action.yml exists with shellcheck and shfmt steps using pinned SHAs",
            "All workflow files that had raw shellcheck/shfmt steps now call the lint-shell composite",
            "All workflow files that had raw uv setup steps now call setup-uv composite",
            "No duplicate setup or lint step definitions remain in any workflow file",
        ],
        "technicalNotes": [
            "Check all files in .github/workflows/ for duplication",
            "Composite action path must be relative: ./.github/actions/lint-shell",
        ],
        "dependencies": ["US-439"],
        "passes": False,
        "_decomposedFrom": "US-382",
    },
]

parent_children = {
    "US-350": ["US-432", "US-433", "US-434", "US-435"],
    "US-352": ["US-436", "US-437", "US-438"],
    "US-382": ["US-439", "US-440"],
}

for s in stories:
    if s["id"] in parent_children:
        s["_decomposed"] = True
        s["_decomposedInto"] = parent_children[s["id"]]

data["userStories"].extend(new_stories)

with open("prd.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Added {len(new_stories)} sub-stories, marked {len(parent_children)} parents as decomposed.")
print("Parents:", list(parent_children.keys()))
print("New IDs:", [s["id"] for s in new_stories])

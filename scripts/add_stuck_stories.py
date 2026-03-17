#!/usr/bin/env python3
"""
Add stuck-story resolution stories and reprioritize backlog.
Run from the repo root: uv run python scripts/add_stuck_stories.py
"""

import json
import shutil
from pathlib import Path

PRD = Path("prd.json")

with open(PRD, encoding="utf-8") as f:
    prd = json.load(f)

NEW_STORIES = [
    {
        "id": "US-429",
        "title": "Add `spiral doctor --stuck` subcommand to diagnose stories with multiple retries",
        "description": (
            "Stories that have retry_count >= 2 and no _passedCommit are stuck. "
            "A dedicated `python main.py doctor --stuck` command should list them with: "
            "retry count, last failure reason, model used, and a recommended fix "
            "(decompose / skip / fix-test / manual). This surfaces actionable diagnostics."
        ),
        "priority": "critical",
        "estimatedComplexity": "small",
        "passes": False,
        "tags": ["stuck-recovery", "developer-experience"],
        "acceptanceCriteria": [
            "`python main.py doctor --stuck` exits 0 and prints a table of stories "
            "where retry-counts.json shows retries >= 2 and prd.json shows passes=false",
            "Each row shows: ID, title, retry count, _failureReason, estimated complexity",
            "Recommended action column: decompose if complexity=large, skip if external dep, retry otherwise",
            "If no stuck stories, prints 'No stuck stories found.' and exits 0",
        ],
        "filesTouch": ["main.py"],
        "technicalNotes": [
            "Read retry-counts.json to find stories with retries >= 2",
            "Cross-reference with prd.json to get failure reasons and complexity",
            "Recommended action logic: large/medium with oversized_diff -> decompose; "
            "external dep pattern in failureReason -> skip; else -> retry",
        ],
        "dependencies": [],
    },
    {
        "id": "US-430",
        "title": "Add pre-implementation scope gate: auto-decompose large stories before Ralph invocation",
        "description": (
            "Stories that are too large for a single Ralph invocation waste expensive model calls "
            "(haiku to sonnet to opus) only to fail with turn-limit or oversized-diff. "
            "Adding a lightweight pre-check that token-counts the story description + acceptance "
            "criteria before invoking Ralph, and immediately decomposes if estimatedComplexity=large "
            "and combined length > 2000 chars, prevents wasted escalation budget and reduces the "
            "stuck retry loop."
        ),
        "priority": "critical",
        "estimatedComplexity": "small",
        "passes": False,
        "tags": ["stuck-recovery", "decomposition"],
        "acceptanceCriteria": [
            "ralph.sh checks story description + acceptance criteria character count before invoking Claude",
            "If combined character count > 2000 AND estimatedComplexity is large, story is auto-decomposed "
            "without spending a Claude call",
            "A log line [pre-scope-gate] US-XXX: description too large (NNNN chars) is emitted",
            "Stories with estimatedComplexity small or medium are NOT pre-decomposed by this gate",
            "A unit test verifies the gate triggers correctly using a synthetic large-description story fixture",
        ],
        "filesTouch": ["ralph/ralph.sh"],
        "technicalNotes": [
            "Character count is a cheap proxy: 2000 chars ~= 400 words ~= 500 tokens",
            "Use echo -n combined_text | wc -c for the count in bash",
            "Only apply to estimatedComplexity=large to avoid over-decomposing medium stories",
        ],
        "dependencies": [],
    },
    {
        "id": "US-431",
        "title": "Add `spiral unstick <STORY_ID>` subcommand to reset retry counter and anti-patterns",
        "description": (
            "When a story is stuck in the retry loop (retry_count >= 2, passes=false), operators "
            "need a safe way to reset it without manually editing retry-counts.json and prd.json. "
            "`python main.py unstick US-NNN` should atomically clear the retry counter, clear "
            "_antiPatterns, clear _failureReason, and print a confirmation."
        ),
        "priority": "critical",
        "estimatedComplexity": "small",
        "passes": False,
        "tags": ["stuck-recovery", "cli"],
        "acceptanceCriteria": [
            "`python main.py unstick US-NNN` sets retry counter for US-NNN in retry-counts.json to 0",
            "Clears _antiPatterns and _failureReason from the story in prd.json",
            "Prints: [unstick] US-NNN reset: retry_count N->0, antiPatterns cleared, failureReason cleared",
            "`python main.py unstick --all` resets ALL stories with retries >= 2",
            "If story ID not found or retries already 0, prints a friendly error and exits non-zero",
        ],
        "filesTouch": ["main.py"],
        "technicalNotes": [
            "Read retry-counts.json, set the key to 0, write back atomically via .tmp rename",
            "Patch prd.json story to clear _antiPatterns=[] and _failureReason=null",
            "Both writes must be atomic (write to .tmp then rename to avoid corruption)",
        ],
        "dependencies": [],
    },
    {
        "id": "US-432",
        "title": "Add zero-progress recovery mode: halve batch size on SPIRAL_CONSECUTIVE_FAIL_ABORT instead of immediate exit",
        "description": (
            "When SPIRAL_CONSECUTIVE_FAIL_ABORT triggers (N consecutive zero-progress iterations), "
            "the system exits with code 9. This is often premature. A recovery mode should: "
            "(1) halve SPIRAL_STORY_BATCH_SIZE, (2) force model=sonnet for one recovery iteration, "
            "(3) emit a diagnostic with stuck story IDs. Only exit code 9 if recovery also fails."
        ),
        "priority": "high",
        "estimatedComplexity": "medium",
        "passes": False,
        "tags": ["stuck-recovery", "resilience"],
        "acceptanceCriteria": [
            "When consecutive zero-progress count hits SPIRAL_CONSECUTIVE_FAIL_ABORT, "
            "recovery mode activates instead of immediate exit",
            "Recovery mode: SPIRAL_STORY_BATCH_SIZE is halved (minimum 1), model forced to sonnet",
            "Log line: [recovery-mode] iter N: batch_size halved to M, model forced to sonnet",
            "If recovery iteration also produces zero progress, THEN exit code 9 is raised",
            "Recovery is counted as one iteration toward MAX_SPIRAL_ITERS",
            "A bats or pytest test verifies recovery mode activates and halves batch size",
        ],
        "filesTouch": ["spiral.sh"],
        "technicalNotes": [
            "Track recovery_attempted flag in .spiral/_checkpoint.json",
            "Recovery only triggers once per zero-progress streak to prevent infinite loops",
            "Log message must include which story IDs were stuck",
        ],
        "dependencies": [],
    },
    {
        "id": "US-433",
        "title": "Track stuck-reason category in results.tsv so Phase R can research targeted fixes",
        "description": (
            "results.tsv tracks per-story attempts but does not categorize WHY stories fail. "
            "Adding a stuck_category column (oversized_diff | turn_limit | context_overflow | "
            "test_regression | quality_gate | unknown) lets Phase R inject the most common "
            "stuck reason into the research prompt, closing the feedback loop between failures "
            "and research focus."
        ),
        "priority": "high",
        "estimatedComplexity": "small",
        "passes": False,
        "tags": ["stuck-recovery", "telemetry", "phase-r"],
        "acceptanceCriteria": [
            "results.tsv gains a stuck_category column populated when a story fails",
            "Categories: oversized_diff, turn_limit, context_overflow, test_regression, quality_gate, unknown",
            "Phase R prompt includes: Most frequent stuck category in recent runs: X (N occurrences) "
            "when category count > 2",
            "A Python helper lib/stuck_analysis.py reads results.tsv and returns the top stuck_category",
            "Unit test verifies categorization logic for each category with synthetic results.tsv rows",
        ],
        "filesTouch": ["ralph/ralph.sh", "spiral.sh", "lib/stuck_analysis.py"],
        "technicalNotes": [
            "Parse _failureReason and gate failure logs to infer category at commit/revert time",
            "Write stuck_category as the last column in results.tsv rows",
            "Phase R reads lib/stuck_analysis.py output and appends to SPIRAL_GEMINI_PROMPT",
        ],
        "dependencies": [],
    },
    {
        "id": "US-434",
        "title": "Add dependency deadlock detector to Phase M: reject story batches with circular deps",
        "description": (
            "Phase M merges new stories into prd.json but does not verify the dependency graph is "
            "acyclic at merge time. A cycle (A depends on B, B depends on A) causes both stories to "
            "remain pending forever. Adding a cycle detector at Phase M merge time prevents this "
            "silent stuck state."
        ),
        "priority": "high",
        "estimatedComplexity": "small",
        "passes": False,
        "tags": ["stuck-recovery", "dag", "phase-m"],
        "acceptanceCriteria": [
            "Phase M calls lib/dag_check.py after patching prd.json; if a cycle is detected, "
            "the merge is rejected and an error is logged",
            "`python main.py doctor` now includes a dependency cycle check",
            "A unit test with a synthetic cycle (A->B, B->A) verifies dag_check.py returns non-zero",
            "Cycles in skipped or passed stories are ignored",
        ],
        "filesTouch": ["lib/dag_check.py", "spiral.sh", "main.py"],
        "technicalNotes": [
            "lib/dag_check.py likely already exists -- verify it handles bidirectional cycles",
            "Topological sort (Kahns algorithm) is O(V+E) and sufficient",
            "Skipped/passed stories should be excluded from the cycle check",
        ],
        "dependencies": [],
    },
]

stories = prd["userStories"]
existing_ids = {s["id"] for s in stories}

for ns in NEW_STORIES:
    if ns["id"] not in existing_ids:
        stories.append(ns)
        print(f"  + Added {ns['id']}: {ns['title'][:65]}")
    else:
        print(f"  ~ Skipped {ns['id']} (already exists)")

# ── Priority updates ──────────────────────────────────────────────────────────
ELEVATE_TO_HIGH = {
    "US-379",  # PostCompact hook — context loss causes stuck
    "US-380",  # Stop hook to verify ACs before worker completes
    "US-343",  # Transactional filesystem snapshots for atomic rollback
    "US-361",  # DAG-aware worker dispatch — dep deadlocks cause stuck
    "US-339",  # Programmatic tool calling — reduces context pressure
    "US-415",  # Per-phase thinking budget — prevents OOM/timeout stuck
    "US-376",  # Sparse-checkout for worktrees — reduces timeout-causing overhead
}

DEMOTE_TO_LOW = {
    "US-382",  # Extract repeated CI steps
    "US-383",  # pytest-xdist
    "US-387",  # uv CI cache
    "US-393",  # SLSA attestation
    "US-399",  # step-security/harden-runner
    "US-418",  # Python version matrix CI
    "US-419",  # vulture dead code CI
    "US-420",  # PR comment with PRD diff
    "US-421",  # pytest-randomly
    "US-422",  # pytest-cov artifact
    "US-423",  # import-linter
    "US-424",  # py-spy flamegraph
    "US-388",  # WorktreeCreate/Remove audit log hook
    "US-389",  # ConfigChange hook
    "US-402",  # .pre-commit-config.yaml
    "US-403",  # cosine-similarity Phase R cache
    "US-352",  # velocity model
    "US-351",  # shared git fetch before parallel
    "US-386",  # asyncio.TaskGroup
    "US-385",  # prd.schema.json Draft 2020-12
    "US-397",  # OTel gen_ai content Events
    "US-401",  # OTel Resource attributes
    "US-377",  # OTel subprocess span
}

elevated = demoted = 0
for s in stories:
    sid = s["id"]
    if sid in ELEVATE_TO_HIGH and s.get("priority") not in ("high", "critical") and not s.get("passes"):
        old = s.get("priority", "?")
        s["priority"] = "high"
        print(f"  UP {sid}: {old} -> high  ({s['title'][:55]})")
        elevated += 1
    elif sid in DEMOTE_TO_LOW and s.get("priority") not in ("low",) and not s.get("passes"):
        old = s.get("priority", "?")
        s["priority"] = "low"
        print(f"  dn {sid}: {old} -> low  ({s['title'][:55]})")
        demoted += 1

print(f"\nElevated: {elevated}  Demoted: {demoted}")
print(f"Total stories: {len(stories)}")

shutil.copy(PRD, PRD.with_suffix(".json.bak"))
with open(PRD, "w", encoding="utf-8") as f:
    json.dump(prd, f, indent=2, ensure_ascii=False)
    f.write("\n")

print("\nprd.json updated. Backup at prd.json.bak")

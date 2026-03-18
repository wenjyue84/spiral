"""
lib_reorg.py -- Reorganize lib/ flat files into semantic subdirectories.

Strategy:
- Move Python files to subdirs (e.g., lib/prd/merge_stories.py)
- Create stub files at original location: exec() the real file into stub namespace
  so that ALL names (including private _names) and unittest.mock.patch() work
- Update shell script lib/xxx.py -> lib/subdir/xxx.py in binary mode (CRLF-safe)
- Leave .sh files flat (they are sourced, not imported)

Run with: uv run python scripts/lib_reorg.py [--dry-run] [--clean-stubs]
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

# -- Group definitions --------------------------------------------------------

GROUPS: dict[str, list[str]] = {
    "core": [
        "constants", "state_machine", "error_catalog", "story_helpers", "spiral_io",
    ],
    "prd": [
        "merge_stories", "validate_stories", "prd_schema", "prd_lint", "prd_lock",
        "compact_prd", "archive_prd", "search_stories", "batch_validate",
        "partition_prd", "check_dag", "check_done", "migrate_prd", "rebalance_pending",
        "slice_prd", "consistency_check", "drift_check", "check_prd_encoding",
    ],
    "research": [
        "summarize_research", "research_cache", "enrich_stories", "ai_suggest",
        "populate_hints", "generate_test_stories", "synthesize_tests",
    ],
    "routing": [
        "llm_router", "llm_models", "llm_client", "route_stories", "semantic_router",
        "cost_check", "cost_project", "record_calibration", "calibration_tracker",
        "velocity_model", "recommend_workers",
    ],
    "quality": [
        "quality_judge", "validate_code", "failure_attribution",
        "test_suite_manager", "evals_runner",
    ],
    "security": [
        "injection_detector", "llm_guard_scanner", "privacy_scrubber",
        "subprocess_policy", "sanitize_output",
    ],
    "observability": [
        "otel_spans", "otel_metrics", "otel_content_events", "otel_resource_builder",
        "otel_worker_inject", "spiral_report", "story_review_report", "generate_adr",
        "generate_job_summary", "merge_results_tsv", "prompt_cache_analysis",
        "benchmark_judge", "auto_release", "mypy_to_github_annotations",
    ],
    "ui": [
        "spiral_dashboard", "spiral_live_server",
    ],
    "importers": [
        "import_csv", "import_github", "import_jira",
    ],
    "resilience": [
        "token_guard", "cascade_skip", "work_queue", "txn_journal",
        "truncate_context", "semantic_chunker", "plan_cache", "query_embed_cache",
        "episodic_memory", "invocation_snapshot",
    ],
    "workers": [
        "decompose_story", "merge_worker_results", "conflict_preflight",
    ],
    "tools": [
        "validate_env", "setup", "detect_stack", "dependency_graph", "infer_dependencies",
    ],
}

# Build reverse: module_name -> group
MODULE_TO_GROUP: dict[str, str] = {}
for group, modules in GROUPS.items():
    for m in modules:
        MODULE_TO_GROUP[m] = group


def build_stub(module: str, group: str) -> str:
    """Python stub that exec()s the real module code into this module's namespace.

    Using exec(open(...).read(), globals()) makes ALL real names (including
    private _names) attributes of THIS stub module object, so:
    - patch("module.func") works (mock finds the attr on THIS module)
    - from module import _private works
    - No sys.modules tricks needed
    """
    return (
        '"""Backward-compat stub -- {} moved to lib/{}/{}.py"""\n'
        "import os as _os\n"
        "_here = _os.path.dirname(_os.path.abspath(__file__))\n"
        "exec(open(_os.path.join(_here, '{}', '{}.py'), encoding='utf-8').read(), globals())\n"
    ).format(module, group, module, group, module)


def update_shell_refs(raw: bytes, dry_run: bool = False) -> tuple[bytes, int]:
    """Replace lib/xxx.py -> lib/group/xxx.py in shell script bytes (binary-safe)."""
    count = 0

    def replacer(m: re.Match[bytes]) -> bytes:
        nonlocal count
        module = m.group(1).decode()
        group = MODULE_TO_GROUP.get(module)
        if group:
            count += 1
            return f"lib/{group}/{module}.py".encode()
        return m.group(0)  # not in our map, leave unchanged

    # Match lib/module_name.py -- word boundary after .py
    pattern = re.compile(rb"lib/([a-z_]+)\.py(?=\b)")
    new_raw = pattern.sub(replacer, raw)
    return new_raw, count


def main() -> None:
    parser = argparse.ArgumentParser(description="Reorganize lib/ Python files")
    parser.add_argument("--dry-run", action="store_true", help="Show plan without making changes")
    parser.add_argument("--clean-stubs", action="store_true", help="Remove backward-compat stubs")
    args = parser.parse_args()

    repo = Path(__file__).parent.parent
    lib = repo / "lib"

    if args.clean_stubs:
        removed = 0
        for module, group in MODULE_TO_GROUP.items():
            stub = lib / f"{module}.py"
            if stub.exists():
                content = stub.read_text(encoding="utf-8", errors="replace")
                if "Backward-compat stub" in content:
                    if not args.dry_run:
                        stub.unlink()
                    print(f"  rm stub: lib/{module}.py")
                    removed += 1
        print(f"\nRemoved {removed} stubs")
        return

    # -- Step 1: Create subdirectory __init__.py files -------------------------
    print("=== Step 1: Create subdir __init__.py files ===")
    for group in GROUPS:
        subdir = lib / group
        init = subdir / "__init__.py"
        if not args.dry_run:
            subdir.mkdir(exist_ok=True)
            if not init.exists():
                init.write_text(f'"""lib/{group}/ -- {group} modules"""\n', encoding="utf-8")
        print(f"  {'[dry]' if args.dry_run else 'ok'} lib/{group}/__init__.py")

    # -- Step 2: Move .py files to subdirs -------------------------------------
    print("\n=== Step 2: Move files to subdirs ===")
    moved = 0
    for module, group in sorted(MODULE_TO_GROUP.items()):
        src = lib / f"{module}.py"
        dst = lib / group / f"{module}.py"
        if not src.exists():
            # Check if it's a stub (already moved)
            content = src.read_text(encoding="utf-8", errors="replace") if src.exists() else ""
            if dst.exists():
                print(f"  skip (already there): lib/{group}/{module}.py")
            else:
                print(f"  skip (not found): lib/{module}.py")
            continue
        # Check if the existing src is a stub
        content = src.read_text(encoding="utf-8", errors="replace")
        if "Backward-compat stub" in content:
            print(f"  skip (stub at src): lib/{module}.py")
            continue
        if dst.exists():
            print(f"  skip (dst exists): lib/{group}/{module}.py")
            continue
        if not args.dry_run:
            shutil.move(str(src), str(dst))
        print(f"  {'[dry]' if args.dry_run else 'mv'} lib/{module}.py -> lib/{group}/{module}.py")
        moved += 1

    # -- Step 3: Create backward-compat stubs ----------------------------------
    print("\n=== Step 3: Create backward-compat stubs ===")
    stubs = 0
    for module, group in sorted(MODULE_TO_GROUP.items()):
        stub = lib / f"{module}.py"
        if stub.exists():
            content = stub.read_text(encoding="utf-8", errors="replace")
            if "Backward-compat stub" in content:
                print(f"  skip (stub exists): lib/{module}.py")
                continue
            print(f"  skip (real file still at): lib/{module}.py")
            continue
        stub_content = build_stub(module, group)
        if not args.dry_run:
            stub.write_text(stub_content, encoding="utf-8")
        print(f"  {'[dry]' if args.dry_run else 'stub'} lib/{module}.py -> exec lib/{group}/{module}.py")
        stubs += 1

    # -- Step 4: Update shell script references --------------------------------
    shell_files = [
        repo / "spiral.sh",
        repo / "ralph" / "ralph.sh",
        repo / "setup.sh",
        repo / "lib" / "run_parallel_ralph.sh",
        *sorted((repo / "lib" / "phases").glob("*.sh")),
        *sorted((repo / "lib" / "impl").glob("*.sh")),
        *sorted((repo / "lib" / "modes").glob("*.sh")),
    ]

    print("\n=== Step 4: Update shell script path references ===")
    total_replacements = 0
    for sh_file in shell_files:
        if not sh_file.exists():
            continue
        raw = sh_file.read_bytes()
        new_raw, count = update_shell_refs(raw)
        if count > 0:
            if not args.dry_run:
                sh_file.write_bytes(new_raw)
            print(f"  {'[dry]' if args.dry_run else 'ok'} {sh_file.relative_to(repo)}: {count} replacement(s)")
            total_replacements += count
        else:
            print(f"  no changes: {sh_file.relative_to(repo)}")

    # -- Step 5: Update Python imports in tests/ and main.py ------------------
    py_files_to_update = [
        *sorted((repo / "tests").glob("*.py")),
        repo / "main.py",
    ]

    print("\n=== Step 5: Update Python imports in tests/ and main.py ===")
    for py_file in py_files_to_update:
        if not py_file.exists():
            continue
        content = py_file.read_text(encoding="utf-8", errors="replace")
        new_content = content
        changed = 0

        for module, group in MODULE_TO_GROUP.items():
            old = f"from lib.{module} import"
            new = f"from lib.{group}.{module} import"
            if old in new_content:
                new_content = new_content.replace(old, new)
                changed += 1
            old2 = f"import lib.{module}"
            new2 = f"import lib.{group}.{module}"
            if old2 in new_content:
                new_content = new_content.replace(old2, new2)
                changed += 1

        if changed > 0:
            if not args.dry_run:
                py_file.write_text(new_content, encoding="utf-8")
            print(f"  {'[dry]' if args.dry_run else 'ok'} {py_file.relative_to(repo)}: {changed} import(s) updated")

    print(f"\n{'DRY RUN ' if args.dry_run else ''}Done:")
    print(f"  Files moved:         {moved}")
    print(f"  Stubs created:       {stubs}")
    print(f"  Shell replacements:  {total_replacements}")


if __name__ == "__main__":
    main()

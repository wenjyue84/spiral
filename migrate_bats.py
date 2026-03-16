#!/usr/bin/env python3
"""Migrate SPIRAL bats test files to use bats_require_minimum_version + common-setup + bats-assert."""
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
TESTS_DIR = REPO / "tests"

# Inline jq resolution pattern (multi-line)
JQ_BLOCK_RE = re.compile(
    r"(\n  # (?:Provide|Resolve|Prefer).*?[Jj][Qq].*?\n)?"
    r"  if command -v jq &>/dev/null; then\n"
    r"    export JQ=\"jq\"\n"
    r"  elif \[\[ -f \"ralph/jq\.exe\" \]\]; then\n"
    r"    export JQ=\"ralph/jq\.exe\"\n"
    r"(?:  elif \[\[ -f \"ralph/jq\" \]\]; then\n"
    r"    export JQ=\"ralph/jq\"\n)?"
    r"  fi\n",
    re.MULTILINE,
)

# Assertion replacements (only on lines that are exactly these patterns)
ASSERTION_REPLACEMENTS = [
    # [ "$status" -eq 0 ] → assert_success
    (re.compile(r'^(  )\[ "\$status" -eq 0 \]$', re.MULTILINE), r"\1assert_success"),
    # [ "$status" -eq N ] for N>0 → assert_failure N
    (re.compile(r'^(  )\[ "\$status" -eq ([1-9][0-9]*) \]$', re.MULTILINE), r"\1assert_failure \2"),
    # [[ "$output" == *"..."* ]] → assert_output --partial "..."
    (re.compile(r'^(  )\[\[ "\$output" == \*"(.*)"\* \]\]$', re.MULTILINE), r'\1assert_output --partial "\2"'),
    # [[ "$output" != *"..."* ]] → refute_output --partial "..."
    (re.compile(r'^(  )\[\[ "\$output" != \*"(.*)"\* \]\]$', re.MULTILINE), r'\1refute_output --partial "\2"'),
    # [ "$output" = "..." ] → assert_output "..."
    (re.compile(r'^(  )\[ "\$output" = "(.*)" \]$', re.MULTILINE), r'\1assert_output "\2"'),
]


def find_bats_files():
    """Find all SPIRAL project bats files, excluding submodule dirs."""
    exclude = {"bats-core", "bats-assert", "bats-support"}
    result = []
    for root, dirs, files in os.walk(TESTS_DIR):
        dirs[:] = [d for d in dirs if d not in exclude]
        for f in files:
            if f.endswith(".bats"):
                result.append(Path(root) / f)
    return sorted(result)


def compute_load_path(filepath: Path) -> str:
    """Determine the correct load path based on file depth."""
    rel = filepath.relative_to(TESTS_DIR)
    depth = len(rel.parts) - 1  # parts minus the filename
    if depth == 0:
        return "test_helper/common-setup"
    elif depth == 1:
        return "../test_helper/common-setup"
    else:
        return ("../" * depth) + "test_helper/common-setup"


def migrate_file(filepath: Path) -> bool:
    """Migrate a single bats file. Returns True if modified."""
    content = filepath.read_text(encoding="utf-8")
    original = content

    # Skip if already has common-setup
    if "common-setup" in content:
        return False

    load_path = compute_load_path(filepath)

    # Step 1: Add bats_require_minimum_version after the comment header
    if "bats_require_minimum_version" not in content:
        lines = content.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped == "" or stripped.startswith("#") or stripped.startswith("#!/"):
                insert_idx = i + 1
            else:
                break
        lines.insert(insert_idx, "")
        lines.insert(insert_idx + 1, "bats_require_minimum_version 1.7.0")
        content = "\n".join(lines)

    # Step 2: Remove inline jq resolution blocks
    content = JQ_BLOCK_RE.sub("\n", content)

    # Step 3: Add load common-setup + _resolve_jq to setup()
    # Find 'setup() {' and add the load line after it
    setup_re = re.compile(r"^(setup\(\) \{)\n", re.MULTILINE)
    if setup_re.search(content):
        content = setup_re.sub(
            r"\1\n  load " + load_path + "\n  _resolve_jq\n",
            content,
        )

    # Step 4: Replace raw assertions
    for pattern, replacement in ASSERTION_REPLACEMENTS:
        content = pattern.sub(replacement, content)

    # Clean up any double blank lines from jq block removal
    content = re.sub(r"\n{3,}", "\n\n", content)

    if content != original:
        filepath.write_text(content, encoding="utf-8")
        return True
    return False


def main():
    files = find_bats_files()
    migrated = 0
    skipped = 0

    for f in files:
        if migrate_file(f):
            print(f"MIGRATED: {f.relative_to(REPO)}")
            migrated += 1
        else:
            print(f"SKIP:     {f.relative_to(REPO)}")
            skipped += 1

    print(f"\nDone: migrated={migrated}, skipped={skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

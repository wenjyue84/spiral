#!/usr/bin/env python3
"""Fix bats_require_minimum_version position — move it to right after the initial file header."""

from pathlib import Path

REPO = Path(__file__).resolve().parent
TESTS_DIR = REPO / "tests"


def find_bats_files():
    exclude = {"bats-core", "bats-assert", "bats-support"}
    result = []
    for root, dirs, files in __import__("os").walk(TESTS_DIR):
        dirs[:] = [d for d in dirs if d not in exclude]
        for f in files:
            if f.endswith(".bats"):
                result.append(Path(root) / f)
    return sorted(result)


def fix_file(filepath: Path) -> bool:
    content = filepath.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Find the bats_require_minimum_version line
    version_idx = None
    for i, line in enumerate(lines):
        if line.strip() == "bats_require_minimum_version 1.7.0":
            version_idx = i
            break

    if version_idx is None:
        return False

    # Find where the "initial file header" ends.
    # The file header is: shebang, then comments/blank lines that form the file doc block.
    # We stop at the first blank line that is followed by a non-comment line,
    # or at the first line that starts a code section like "# ── " or a function.
    header_end = 0
    in_doc_block = True
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped.startswith("#!"):
            header_end = i + 1
            continue
        if stripped.startswith("bats_require_minimum_version"):
            continue  # skip existing version line
        if in_doc_block:
            if stripped == "":
                # Blank line — check if next non-blank line is still a doc comment
                # (starting with "# " but not a section header like "# ── ")
                j = i + 1
                while j < len(lines) and lines[j].strip() == "":
                    j += 1
                if j < len(lines):
                    next_line = lines[j].strip()
                    if next_line.startswith("# ── ") or not next_line.startswith("#"):
                        # End of doc block
                        header_end = i
                        break
                    else:
                        # Still in doc block (multi-paragraph doc comment)
                        header_end = i + 1
                        continue
                else:
                    header_end = i
                    break
            elif stripped.startswith("#"):
                # Check if this is a section header (not part of initial doc)
                if stripped.startswith("# ── "):
                    header_end = i
                    in_doc_block = False
                    break
                header_end = i + 1
            else:
                # Non-comment, non-blank — header ended
                header_end = i
                in_doc_block = False
                break

    # If version line is already at header_end or header_end+1, it's fine
    if abs(version_idx - header_end) <= 1:
        return False

    # Remove the version line from its current position
    # Also remove surrounding blank lines if they create a gap
    removed_lines = lines[:version_idx]
    rest = lines[version_idx + 1 :]
    # Clean up blank line before the removed line if one exists
    if removed_lines and removed_lines[-1].strip() == "" and rest and rest[0].strip() == "":
        removed_lines.pop()
    lines = removed_lines + rest

    # Recalculate header_end after removal (it may have shifted)
    header_end_new = 0
    in_doc_block = True
    for i, line in enumerate(lines):
        stripped = line.strip()
        if i == 0 and stripped.startswith("#!"):
            header_end_new = i + 1
            continue
        if in_doc_block:
            if stripped == "":
                j = i + 1
                while j < len(lines) and lines[j].strip() == "":
                    j += 1
                if j < len(lines):
                    next_line = lines[j].strip()
                    if next_line.startswith("# ── ") or not next_line.startswith("#"):
                        header_end_new = i
                        break
                    else:
                        header_end_new = i + 1
                        continue
                else:
                    header_end_new = i
                    break
            elif stripped.startswith("#"):
                if stripped.startswith("# ── "):
                    header_end_new = i
                    in_doc_block = False
                    break
                header_end_new = i + 1
            else:
                header_end_new = i
                in_doc_block = False
                break

    # Insert version line at header_end_new
    lines.insert(header_end_new, "")
    lines.insert(header_end_new + 1, "bats_require_minimum_version 1.7.0")

    new_content = "\n".join(lines)
    if new_content != content:
        filepath.write_text(new_content, encoding="utf-8")
        return True
    return False


def main():
    fixed = 0
    for f in find_bats_files():
        if fix_file(f):
            print(f"FIXED: {f.relative_to(REPO)}")
            fixed += 1
    print(f"\nFixed {fixed} files")


if __name__ == "__main__":
    main()

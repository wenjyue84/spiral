#!/usr/bin/env python3
"""Phase V: Verify new Python modules are called by spiral.sh or main.py."""

import sys
import re
import subprocess
from pathlib import Path

def get_new_python_files(story_branch: str = "HEAD") -> list[str]:
    """Get .py files added/modified in this story."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=A", f"{story_branch}^..{story_branch}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        files = [f for f in result.stdout.strip().split("\n") if f.endswith(".py")]
        return files
    except Exception:
        return []

def find_calls(entry_point_file: str, module_name: str) -> list[str]:
    """Find call sites for a module in entry point file."""
    if not Path(entry_point_file).exists():
        return []

    try:
        content = Path(entry_point_file).read_text()
    except Exception:
        return []

    # Search for patterns: "import module_name" or "python lib/module_name.py" or "from module_name"
    patterns = [
        rf"\bimport\s+{module_name}\b",
        rf"\bfrom\s+{module_name}\b",
        rf"lib/{module_name}\.py",
        rf"lib\.{module_name}",
    ]

    calls = []
    for match in re.finditer("|".join(patterns), content):
        start = max(0, match.start() - 40)
        end = min(len(content), match.end() + 40)
        calls.append(content[start:end].replace("\n", " "))

    return calls

def verify_reachability(story_title: str) -> dict:
    """Check if new Python modules are reachable from entry points."""
    # Only check Phase stories
    if not story_title.startswith("Phase"):
        return {"reachable": True, "reason": "not_a_phase_story"}

    new_files = get_new_python_files()
    if not new_files:
        return {"reachable": True, "reason": "no_new_python_files"}

    # Extract module names from lib/module_name.py
    module_names = [
        Path(f).stem for f in new_files
        if f.startswith("lib/") and f.endswith(".py")
    ]

    if not module_names:
        return {"reachable": True, "reason": "new_files_not_in_lib"}

    # Check entry points
    call_sites = {}
    for module_name in module_names:
        calls_spiral = find_calls("spiral.sh", module_name)
        calls_main = find_calls("main.py", module_name)
        calls = calls_spiral + calls_main
        call_sites[module_name] = calls if calls else None

    # All modules found = reachable
    reachable = all(call_sites.get(m) for m in module_names)

    return {
        "reachable": reachable,
        "modules_checked": module_names,
        "call_sites": call_sites
    }

if __name__ == "__main__":
    story_title = sys.argv[1] if len(sys.argv) > 1 else "Phase V"
    result = verify_reachability(story_title)

    if result["reachable"]:
        print("✓ Reachability check passed")
        sys.exit(0)
    else:
        print("✗ Reachability check failed:")
        for module, calls in result.get("call_sites", {}).items():
            if not calls:
                print(f"  - {module}: NOT FOUND in spiral.sh or main.py")
        sys.exit(1)

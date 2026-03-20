"""Phase G: Semantic Version Bumper for package.json and pyproject.toml.

Parses the semantic version from CHANGELOG.md and updates both:
- spiral-ui/package.json
- pyproject.toml

This ensures all version files stay synchronized after each release.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


def parse_version_from_changelog(changelog_path: str = "CHANGELOG.md") -> str:
    """Parse semantic version (X.Y.Z) from first CHANGELOG.md entry.

    Args:
      changelog_path: Path to CHANGELOG.md file

    Returns:
      Semantic version string in format X.Y.Z (e.g., "1.2.3")

    Raises:
      ValueError: If no version found or file doesn't exist
    """
    changelog = Path(changelog_path)
    if not changelog.exists():
        raise ValueError(f"CHANGELOG.md not found at {changelog_path}")

    with open(changelog) as f:
        content = f.read()

    # Match ## [X.Y.Z] or ## X.Y.Z format from markdown headers
    match = re.search(r"##\s+(?:\[)?(\d+\.\d+\.\d+)(?:\])?", content)
    if not match:
        raise ValueError(f"No semantic version found in {changelog_path}")

    return match.group(1)


def update_package_json(version: str, package_json_path: str = "spiral-ui/package.json") -> None:
    """Update version field in package.json.

    Args:
      version: Semantic version string (X.Y.Z)
      package_json_path: Path to package.json file

    Raises:
      ValueError: If file not found
      json.JSONDecodeError: If JSON is invalid
    """
    package_json = Path(package_json_path)
    if not package_json.exists():
        raise ValueError(f"package.json not found at {package_json_path}")

    with open(package_json) as f:
        content: dict[str, Any] = json.load(f)

    content["version"] = version

    with open(package_json, "w") as f:
        json.dump(content, f, indent=2)
        f.write("\n")


def update_pyproject_toml(version: str, pyproject_path: str = "pyproject.toml") -> None:
    """Update version field in pyproject.toml.

    Args:
      version: Semantic version string (X.Y.Z)
      pyproject_path: Path to pyproject.toml file

    Raises:
      ValueError: If file not found or [project] section missing
    """
    pyproject = Path(pyproject_path)
    if not pyproject.exists():
        raise ValueError(f"pyproject.toml not found at {pyproject_path}")

    with open(pyproject) as f:
        content = f.read()

    # Add [project] section with version if it doesn't exist
    if "[project]" not in content:
        # Insert after [build-system] section
        lines = content.split("\n")
        insert_idx = 0
        for i, line in enumerate(lines):
            if line.startswith("[") and line != "[build-system]":
                insert_idx = i
                break
        else:
            insert_idx = len(lines)

        lines.insert(insert_idx, f'\nversion = "{version}"')
        content = "\n".join(lines)
    else:
        # Update existing version in [project] section
        # Match version = "..." pattern in [project] section
        pattern = r'(version\s*=\s*)["\'].*?["\']'
        if re.search(pattern, content):
            content = re.sub(pattern, f'version = "{version}"', content)
        else:
            # Insert version field after [project] line
            content = re.sub(r"(\[project\]\n)", f'[project]\nversion = "{version}"\n', content)

    with open(pyproject, "w") as f:
        f.write(content)


def create_version_commit(version: str) -> None:
    """Create a git commit with version bump message.

    Args:
      version: Semantic version string (X.Y.Z)

    Raises:
      RuntimeError: If git commands fail
    """
    message = f"[skip ci] chore: bump to v{version}"

    # Stage the updated files
    result = subprocess.run(
        ["git", "add", "spiral-ui/package.json", "pyproject.toml"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to stage version files: {result.stderr}")

    # Create commit
    result = subprocess.run(
        ["git", "commit", "-m", message],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create version commit: {result.stderr}")


def bump_versions(
    changelog_path: str = "CHANGELOG.md",
    package_json_path: str = "spiral-ui/package.json",
    pyproject_path: str = "pyproject.toml",
) -> str:
    """Main orchestrator: parse version and update all files.

    Args:
      changelog_path: Path to CHANGELOG.md
      package_json_path: Path to package.json
      pyproject_path: Path to pyproject.toml

    Returns:
      The bumped version string (X.Y.Z)

    Raises:
      ValueError: If version parsing or file operations fail
      RuntimeError: If git operations fail
    """
    # Parse version from CHANGELOG
    version = parse_version_from_changelog(changelog_path)
    print(f"▶ Extracted version {version} from {changelog_path}")

    # Update package.json
    update_package_json(version, package_json_path)
    print(f"✓ Updated {package_json_path} to version {version}")

    # Update pyproject.toml
    update_pyproject_toml(version, pyproject_path)
    print(f"✓ Updated {pyproject_path} to version {version}")

    # Create version commit
    create_version_commit(version)
    print(f"✓ Created version commit for v{version}")

    return version


def main() -> None:
    """Entry point for version bumping."""
    try:
        version = bump_versions()
        print(f"\n✅ Version bump complete: v{version}\n")
    except (ValueError, RuntimeError) as e:
        print(f"\n❌ Version bump failed: {e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

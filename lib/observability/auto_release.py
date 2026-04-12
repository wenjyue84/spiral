"""Phase G: Auto-generate release artifacts (CHANGELOG.md and API docs).

Coordinates generation of:
1. CHANGELOG.md via git-cliff (conventional commits parsing)
2. API docs via pdoc (Python docstring extraction)
3. Detects and logs orphan commits (without US-*/UT-* story IDs)

Both artifacts are generated during the release workflow when a semver tag is pushed.
"""

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import TypedDict


def run_command(cmd: list[str], description: str) -> None:
    """Execute a shell command and raise on failure.

    Args:
      cmd: Command and arguments to execute
      description: Human-readable description for error messages

    Raises:
      RuntimeError: If the command fails with non-zero exit code
    """
    print(f"▶ {description}...")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to {description}: {' '.join(cmd)}")
    print(f"✓ {description} complete")


def generate_changelog(config: str = "cliff.toml", output: str = "CHANGELOG.md") -> None:
    """Generate CHANGELOG.md from git commits using git-cliff.

    Args:
      config: Path to cliff.toml configuration file
      output: Output file path for the generated changelog
    """
    run_command(
        ["git-cliff", "--config", config, "--output", output],
        f"Generate {output} from git history",
    )


def embed_git_frontmatter_in_docs(output_dir: str) -> None:
    """Embed git commit SHA and timestamp in YAML frontmatter of HTML files.

    Args:
      output_dir: Directory containing generated HTML files
    """
    # Get current git commit SHA
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        return  # Skip if git fails (e.g., not a git repo)

    commit_sha = result.stdout.strip()

    # Get current timestamp
    result = subprocess.run(
        ["git", "log", "-1", "--format=%aI"],
        capture_output=True,
        text=True,
        check=False,
    )

    timestamp = result.stdout.strip() if result.returncode == 0 else "unknown"

    # Add frontmatter to all HTML files in output_dir
    output_path = Path(output_dir)
    if not output_path.exists():
        return

    for html_file in output_path.rglob("*.html"):
        try:
            with open(html_file, "r", encoding="utf-8") as f:
                content = f.read()

            # Add YAML frontmatter if not already present
            if not content.startswith("---"):
                frontmatter = f"""---
generated_from_commit: {commit_sha}
generated_timestamp: {timestamp}
---
"""
                content = frontmatter + content

                with open(html_file, "w", encoding="utf-8") as f:
                    f.write(content)
        except (IOError, UnicodeDecodeError):
            pass  # Skip files that can't be read/written


def generate_api_docs(
    source_dir: str = "lib",
    output_dir: str = ".spiral/docs/api",
    title: str = "SPIRAL API Documentation",
) -> None:
    """Generate API documentation from Python docstrings using pdoc.

    Args:
      source_dir: Python package/module to document
      output_dir: Output directory for generated HTML docs
      title: Title for the documentation site
    """
    output_path = Path(output_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    run_command(
        ["pdoc", source_dir, "--docformat", "google", "--output-directory", output_dir, "--title", title],
        f"Generate API docs for {source_dir} to {output_dir}",
    )

    # Embed git commit SHA in YAML frontmatter of generated HTML files
    embed_git_frontmatter_in_docs(output_dir)


class OrphanCommit(TypedDict):
    """Schema for an orphan commit record."""

    commit_sha: str
    message: str
    timestamp: str
    reason: str


def detect_orphan_commits() -> list[OrphanCommit]:
    """Detect commits without US-*/UT-* story IDs in their messages.

    Returns:
      List of OrphanCommit records for commits without story IDs

    Raises:
      RuntimeError: If git log command fails
    """
    # Get all commits with sha, message, and author date
    result = subprocess.run(
        ["git", "log", "--format=%H%n%s%n%aI"],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to get git log: {result.stderr}")

    orphans: list[OrphanCommit] = []
    lines = result.stdout.strip().split("\n")

    i = 0
    while i < len(lines):
        if i + 2 >= len(lines):
            break

        commit_sha = lines[i].strip()
        message = lines[i + 1].strip()
        timestamp = lines[i + 2].strip()
        i += 3

        # Check if commit message contains US-### or UT-### pattern
        if not re.search(r"(US-\d+|UT-\d+)", message):
            orphans.append(
                OrphanCommit(
                    commit_sha=commit_sha,
                    message=message,
                    timestamp=timestamp,
                    reason="Missing story ID (US-*/UT-*) in commit message",
                )
            )

    return orphans


def log_orphan_commits(orphans: list[OrphanCommit]) -> None:
    """Write orphan commits to .spiral/_phase_g_orphans.json.

    Args:
      orphans: List of orphan commit records to log
    """
    spiral_dir = Path(".spiral")
    spiral_dir.mkdir(exist_ok=True)

    orphan_file = spiral_dir / "_phase_g_orphans.json"

    with open(orphan_file, "w") as f:
        json.dump(orphans, f, indent=2)


def main() -> None:
    """Orchestrate Phase G: auto-generate CHANGELOG.md and API docs."""
    try:
        print("\n📋 SPIRAL Phase G: Auto-generate release artifacts\n")

        # Detect and log orphan commits (commits without story IDs)
        orphans = detect_orphan_commits()
        log_orphan_commits(orphans)

        # Generate changelog from git history
        generate_changelog()

        # Bump semantic version in package.json and pyproject.toml
        from lib.phases.phase_g_version_bump import bump_versions

        _ = bump_versions()

        # Generate API documentation from Python modules
        generate_api_docs()

        # Print summary with orphan count
        orphan_count = len(orphans)
        orphan_msg = f" ({orphan_count} orphan commits detected)" if orphan_count > 0 else ""
        print(f"\n✅ Phase G complete: CHANGELOG.md and API docs generated{orphan_msg}\n")
    except RuntimeError as e:
        print(f"\n❌ Phase G failed: {e}\n", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

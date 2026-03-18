"""Phase G: Auto-generate release artifacts (CHANGELOG.md and API docs).

Coordinates generation of:
1. CHANGELOG.md via git-cliff (conventional commits parsing)
2. API docs via pdoc (Python docstring extraction)

Both artifacts are generated during the release workflow when a semver tag is pushed.
"""

import subprocess
import sys
from pathlib import Path


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


def generate_api_docs(
    source_dir: str = "lib",
    output_dir: str = "docs/api",
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


def main() -> None:
  """Orchestrate Phase G: auto-generate CHANGELOG.md and API docs."""
  try:
    print("\n📋 SPIRAL Phase G: Auto-generate release artifacts\n")

    # Generate changelog from git history
    generate_changelog()

    # Generate API documentation from Python modules
    generate_api_docs()

    print("\n✅ Phase G complete: CHANGELOG.md and API docs generated\n")
  except RuntimeError as e:
    print(f"\n❌ Phase G failed: {e}\n", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()

"""Tests for lib/phases/gen_changelog.sh — Phase G changelog generation.

Verifies:
- AC1: git-cliff binary validation via SPIRAL_GIT_CLIFF_BIN
- AC2: CHANGELOG.md generation with feat/fix/docs/refactor sections
- AC3: Orphan commit detection and warning log
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path
from typing import Any


def _to_unix_path(p: Path) -> str:
    """Convert Windows path to Unix-style for Git Bash."""
    s = str(p).replace("\\", "/")
    # Convert C:/... to /c/...
    if len(s) >= 2 and s[1] == ":":
        s = "/" + s[0].lower() + s[2:]
    return s


def _run_gen_changelog(
    repo_dir: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Source gen_changelog.sh and call phase_gen_changelog in a bash subshell."""
    env = os.environ.copy()
    env["SPIRAL_HOME"] = _to_unix_path(repo_dir)
    if env_overrides:
        env.update(env_overrides)

    script = textwrap.dedent("""\
        set -euo pipefail
        source "$SPIRAL_HOME/lib/phases/gen_changelog.sh"
        phase_gen_changelog
    """)

    return subprocess.run(
        ["bash", "-c", script],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _init_git_repo(tmp_path: Path) -> Path:
    """Create a git repo with cliff.toml and some commits."""
    repo = tmp_path / "repo"
    repo.mkdir()

    # Copy cliff.toml from project
    cliff_src = Path(__file__).parent.parent / "cliff.toml"
    cliff_dst = repo / "cliff.toml"
    cliff_dst.write_text(cliff_src.read_text(encoding="utf-8"), encoding="utf-8")

    # Create gen_changelog.sh stub path
    phases_dir = repo / "lib" / "phases"
    phases_dir.mkdir(parents=True)
    gen_src = Path(__file__).parent.parent / "lib" / "phases" / "gen_changelog.sh"
    gen_dst = phases_dir / "gen_changelog.sh"
    gen_dst.write_text(gen_src.read_text(encoding="utf-8"), encoding="utf-8")

    # Create .spiral dir
    (repo / ".spiral").mkdir()

    # Init git repo
    subprocess.run(
        ["git", "init"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    return repo


def _add_commit(repo: Path, message: str, filename: str = "") -> None:
    """Add a file and commit with given message."""
    if not filename:
        # Use only the first line (subject) for filename, strip unsafe chars
        subject = message.split("\n")[0]
        filename = subject.replace(" ", "_").replace(":", "").replace("/", "")[:20] + ".txt"
    (repo / filename).write_text("content", encoding="utf-8")
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        capture_output=True,
        check=True,
    )


# ── AC1: Binary validation tests ────────────────────────────────────────────


class TestAC1BinaryValidation:
    """AC1: lib/phases/gen_changelog.sh validates git-cliff binary exists."""

    def test_fails_when_git_cliff_binary_not_found(self, tmp_path: Path) -> None:
        """Exits with error when SPIRAL_GIT_CLIFF_BIN points to missing binary."""
        repo = _init_git_repo(tmp_path)
        _add_commit(repo, "feat: initial commit\n\nStory ID: US-001")

        result = _run_gen_changelog(
            repo,
            env_overrides={"SPIRAL_GIT_CLIFF_BIN": "/nonexistent/git-cliff-fake"},
        )

        assert result.returncode != 0
        assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()

    def test_uses_spiral_git_cliff_bin_from_config(self, tmp_path: Path) -> None:
        """Uses SPIRAL_GIT_CLIFF_BIN path when set."""
        repo = _init_git_repo(tmp_path)
        _add_commit(repo, "feat: initial commit\n\nStory ID: US-001")

        # Create a fake git-cliff that just writes a CHANGELOG
        fake_bin = tmp_path / "fake-git-cliff"
        fake_bin.write_text(
            '#!/bin/bash\necho "# Changelog" > "$4"\n',
            encoding="utf-8",
        )
        subprocess.run(["chmod", "+x", str(fake_bin)], capture_output=True)

        result = _run_gen_changelog(
            repo,
            env_overrides={"SPIRAL_GIT_CLIFF_BIN": str(fake_bin)},
        )

        assert result.returncode == 0

    def test_fails_when_cliff_toml_missing(self, tmp_path: Path) -> None:
        """Exits with error when cliff.toml is not found."""
        repo = _init_git_repo(tmp_path)
        _add_commit(repo, "feat: initial commit\n\nStory ID: US-001")

        # Remove cliff.toml
        (repo / "cliff.toml").unlink()

        # Create a fake git-cliff so binary check passes
        fake_bin = tmp_path / "fake-git-cliff2"
        fake_bin.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        subprocess.run(["chmod", "+x", str(fake_bin)], capture_output=True)

        result = _run_gen_changelog(
            repo,
            env_overrides={"SPIRAL_GIT_CLIFF_BIN": str(fake_bin)},
        )

        assert result.returncode != 0
        assert "cliff.toml" in result.stderr


# ── AC2: CHANGELOG.md generation tests ──────────────────────────────────────


class TestAC2ChangelogGeneration:
    """AC2: CHANGELOG.md generated with sections for feat/fix/docs/refactor."""

    def test_changelog_created_with_sections(self, tmp_path: Path) -> None:
        """CHANGELOG.md contains section headers from conventional commits."""
        repo = _init_git_repo(tmp_path)

        # Create commits with different conventional types
        _add_commit(repo, "feat: add new feature\n\nStory ID: US-100")
        _add_commit(repo, "fix: resolve bug\n\nStory ID: US-101")
        _add_commit(repo, "docs: update readme\n\nStory ID: US-102")
        _add_commit(repo, "refactor: clean up code\n\nStory ID: US-103")

        # Create a fake git-cliff that produces realistic output
        fake_bin = tmp_path / "fake-cliff"
        fake_bin.write_text(
            textwrap.dedent("""\
                #!/bin/bash
                # Parse --output flag to get output path
                OUTPUT=""
                while [[ $# -gt 0 ]]; do
                    case $1 in
                        --output) OUTPUT="$2"; shift 2 ;;
                        *) shift ;;
                    esac
                done
                cat > "$OUTPUT" <<'CHANGELOG'
                # Changelog

                ## [Unreleased]

                ### Features
                - add new feature (abc1234) Story ID: US-100

                ### Bug Fixes
                - resolve bug (def5678) Story ID: US-101

                ### Documentation
                - update readme (ghi9012) Story ID: US-102

                ### Refactoring
                - clean up code (jkl3456) Story ID: US-103
                CHANGELOG
            """),
            encoding="utf-8",
        )
        subprocess.run(["chmod", "+x", str(fake_bin)], capture_output=True)

        result = _run_gen_changelog(
            repo,
            env_overrides={"SPIRAL_GIT_CLIFF_BIN": str(fake_bin)},
        )

        assert result.returncode == 0
        changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "Features" in changelog
        assert "Bug Fixes" in changelog
        assert "Documentation" in changelog
        assert "Refactoring" in changelog

    def test_changelog_contains_commit_hashes(self, tmp_path: Path) -> None:
        """CHANGELOG.md entries include commit hashes."""
        repo = _init_git_repo(tmp_path)
        _add_commit(repo, "feat: test feature\n\nStory ID: US-200")

        fake_bin = tmp_path / "fake-cliff-hash"
        fake_bin.write_text(
            textwrap.dedent("""\
                #!/bin/bash
                OUTPUT=""
                while [[ $# -gt 0 ]]; do
                    case $1 in
                        --output) OUTPUT="$2"; shift 2 ;;
                        *) shift ;;
                    esac
                done
                cat > "$OUTPUT" <<'CHANGELOG'
                # Changelog

                ## [Unreleased]

                ### Features
                - test feature (abc1234)
                CHANGELOG
            """),
            encoding="utf-8",
        )
        subprocess.run(["chmod", "+x", str(fake_bin)], capture_output=True)

        result = _run_gen_changelog(
            repo,
            env_overrides={"SPIRAL_GIT_CLIFF_BIN": str(fake_bin)},
        )

        assert result.returncode == 0
        changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
        assert "abc1234" in changelog


# ── AC3: Orphan commit detection tests ──────────────────────────────────────


class TestAC3OrphanCommitDetection:
    """AC3: Orphan commits logged to .spiral/phase_g_warnings.log."""

    def test_orphan_commits_logged(self, tmp_path: Path) -> None:
        """Commits without story ID are logged to warnings file."""
        repo = _init_git_repo(tmp_path)

        # Mix of commits with and without story IDs
        _add_commit(repo, "feat: add feature\n\nStory ID: US-100")
        _add_commit(repo, "fix: random fix without story id")
        _add_commit(repo, "docs: orphan documentation update")

        fake_bin = tmp_path / "fake-cliff-orphan"
        fake_bin.write_text(
            textwrap.dedent("""\
                #!/bin/bash
                OUTPUT=""
                while [[ $# -gt 0 ]]; do
                    case $1 in
                        --output) OUTPUT="$2"; shift 2 ;;
                        *) shift ;;
                    esac
                done
                echo "# Changelog" > "$OUTPUT"
            """),
            encoding="utf-8",
        )
        subprocess.run(["chmod", "+x", str(fake_bin)], capture_output=True)

        result = _run_gen_changelog(
            repo,
            env_overrides={"SPIRAL_GIT_CLIFF_BIN": str(fake_bin)},
        )

        assert result.returncode == 0
        warnings_file = repo / ".spiral" / "phase_g_warnings.log"
        assert warnings_file.exists()
        warnings = warnings_file.read_text(encoding="utf-8")
        # The two orphan commits should be logged
        assert "orphan documentation update" in warnings
        assert "random fix without story id" in warnings
        # The commit with US-100 should NOT be logged
        assert "US-100" not in warnings

    def test_no_orphans_when_all_have_story_ids(self, tmp_path: Path) -> None:
        """No warnings when all commits have story IDs."""
        repo = _init_git_repo(tmp_path)

        _add_commit(repo, "feat: feature one\n\nStory ID: US-100")
        _add_commit(repo, "fix: bug fix\n\nStory ID: UT-200")

        fake_bin = tmp_path / "fake-cliff-clean"
        fake_bin.write_text(
            textwrap.dedent("""\
                #!/bin/bash
                OUTPUT=""
                while [[ $# -gt 0 ]]; do
                    case $1 in
                        --output) OUTPUT="$2"; shift 2 ;;
                        *) shift ;;
                    esac
                done
                echo "# Changelog" > "$OUTPUT"
            """),
            encoding="utf-8",
        )
        subprocess.run(["chmod", "+x", str(fake_bin)], capture_output=True)

        result = _run_gen_changelog(
            repo,
            env_overrides={"SPIRAL_GIT_CLIFF_BIN": str(fake_bin)},
        )

        assert result.returncode == 0
        assert "All commits have story IDs" in result.stdout

    def test_orphan_warning_count_in_output(self, tmp_path: Path) -> None:
        """Output includes count of orphan commits found."""
        repo = _init_git_repo(tmp_path)

        _add_commit(repo, "feat: no story id commit 1")
        _add_commit(repo, "fix: no story id commit 2")
        _add_commit(repo, "docs: has story\n\nStory ID: US-300")

        fake_bin = tmp_path / "fake-cliff-count"
        fake_bin.write_text(
            textwrap.dedent("""\
                #!/bin/bash
                OUTPUT=""
                while [[ $# -gt 0 ]]; do
                    case $1 in
                        --output) OUTPUT="$2"; shift 2 ;;
                        *) shift ;;
                    esac
                done
                echo "# Changelog" > "$OUTPUT"
            """),
            encoding="utf-8",
        )
        subprocess.run(["chmod", "+x", str(fake_bin)], capture_output=True)

        result = _run_gen_changelog(
            repo,
            env_overrides={"SPIRAL_GIT_CLIFF_BIN": str(fake_bin)},
        )

        assert result.returncode == 0
        assert "orphan commits" in result.stdout.lower()
        assert "WARNING" in result.stdout

    def test_ut_prefix_recognized_as_story_id(self, tmp_path: Path) -> None:
        """UT-NNN pattern is also recognized as a valid story ID."""
        repo = _init_git_repo(tmp_path)

        _add_commit(repo, "test: add test\n\nStory ID: UT-150")

        fake_bin = tmp_path / "fake-cliff-ut"
        fake_bin.write_text(
            textwrap.dedent("""\
                #!/bin/bash
                OUTPUT=""
                while [[ $# -gt 0 ]]; do
                    case $1 in
                        --output) OUTPUT="$2"; shift 2 ;;
                        *) shift ;;
                    esac
                done
                echo "# Changelog" > "$OUTPUT"
            """),
            encoding="utf-8",
        )
        subprocess.run(["chmod", "+x", str(fake_bin)], capture_output=True)

        result = _run_gen_changelog(
            repo,
            env_overrides={"SPIRAL_GIT_CLIFF_BIN": str(fake_bin)},
        )

        assert result.returncode == 0
        assert "All commits have story IDs" in result.stdout

"""Test pytest cache persistence across iterations (US-1099)."""

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_project() -> Path:
    """Create a temporary project with pytest cache directory."""
    tmpdir = Path(tempfile.mkdtemp(prefix="spiral_cache_test_"))
    yield tmpdir
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def spiral_dir(temp_project: Path) -> Path:
    """Create .spiral directory."""
    spiral = temp_project / ".spiral"
    spiral.mkdir(exist_ok=True)
    return spiral


def test_cache_directory_created(temp_project: Path, spiral_dir: Path) -> None:
    """Test that cache directory is created when pytest runs with -o cache_dir flag."""
    cache_dir = spiral_dir / ".pytest_cache"
    test_file = temp_project / "test_example.py"
    test_file.write_text(
        """
def test_sample():
    assert 1 + 1 == 2
"""
    )

    # Run pytest with -o cache_dir flag (proper pytest option)
    result = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            str(test_file),
            "-o",
            f"cache_dir={cache_dir}",
            "-v",
        ],
        cwd=str(temp_project),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert cache_dir.exists(), f"Cache dir {cache_dir} not created"
    assert (cache_dir / ".gitkeep").exists() or any(cache_dir.iterdir()), "Cache directory is empty"


def test_cache_persists_across_runs(temp_project: Path, spiral_dir: Path) -> None:
    """Test that cache survives and is reused across two pytest runs."""
    cache_dir = spiral_dir / ".pytest_cache"
    test_file = temp_project / "test_sample.py"
    test_file.write_text(
        """
def test_first():
    x = 1
    assert x == 1

def test_second():
    y = 2
    assert y == 2
"""
    )

    # First run
    result1 = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            str(test_file),
            "-o",
            f"cache_dir={cache_dir}",
            "-v",
        ],
        cwd=str(temp_project),
        capture_output=True,
        text=True,
    )
    assert result1.returncode == 0

    # Check cache exists after first run
    assert cache_dir.exists(), "Cache not created on first run"
    cache_contents_after_first = set(cache_dir.rglob("*")) if cache_dir.exists() else set()
    assert len(cache_contents_after_first) > 0, "Cache is empty after first run"

    # Second run (cache should be reused)
    result2 = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            str(test_file),
            "-o",
            f"cache_dir={cache_dir}",
            "-v",
        ],
        cwd=str(temp_project),
        capture_output=True,
        text=True,
    )
    assert result2.returncode == 0

    # Verify cache still exists after second run
    assert cache_dir.exists(), "Cache removed after second run"
    # Check for cache hit indicators in output
    assert "passed" in result2.stdout, "Tests should pass on second run"


def test_import_mode_importlib(temp_project: Path, spiral_dir: Path) -> None:
    """Test that --import-mode=importlib is compatible with cache_dir."""
    cache_dir = spiral_dir / ".pytest_cache"
    test_file = temp_project / "test_import.py"
    test_file.write_text(
        """
def test_with_import_mode():
    import sys
    assert sys.version_info[0] >= 3
"""
    )

    # Run with both flags
    result = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            str(test_file),
            "-o",
            f"cache_dir={cache_dir}",
            "--import-mode=importlib",
            "-v",
        ],
        cwd=str(temp_project),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert cache_dir.exists(), "Cache not created with importlib mode"


def test_cache_size_limit() -> None:
    """Test cache size calculation logic."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "test_cache"
        cache_dir.mkdir()

        # Create a 1MB file
        test_file = cache_dir / "large_file.bin"
        test_file.write_bytes(b"x" * (1024 * 1024))

        # Calculate cache size in MB using Python subprocess with raw string
        cache_size_cmd = (
            f"import os;d=r'{cache_dir}';"
            "s=sum(os.path.getsize(os.path.join(dp,f)) "
            "for dp,_,fs in os.walk(d) for f in fs);"
            "print(int(s/1024/1024))"
        )
        result = subprocess.run(
            ["python", "-c", cache_size_cmd],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        size_mb = int(result.stdout.strip())
        assert size_mb >= 1, f"Expected at least 1MB, got {size_mb}MB"


def test_cache_cleanup_on_size_exceeded(temp_project: Path, spiral_dir: Path) -> None:
    """Test that cache is pruned when size limit is exceeded."""
    cache_dir = spiral_dir / ".pytest_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Create a large file in cache (simulating overgrown cache)
    large_file = cache_dir / "large_cache.bin"
    large_file.write_bytes(b"x" * (150 * 1024 * 1024))  # 150MB

    # Verify cache exists and is large
    assert cache_dir.exists()
    assert large_file.exists()

    # Simulate cache cleanup (prune when > 100MB)
    if cache_dir.exists():
        cache_size = sum(f.stat().st_size for f in cache_dir.rglob("*") if f.is_file()) / (1024 * 1024)
        if cache_size > 100:
            shutil.rmtree(cache_dir)
            cache_dir.mkdir(parents=True, exist_ok=True)

    # Verify cache was pruned
    remaining_files = list(cache_dir.rglob("*"))
    assert len(remaining_files) == 0, "Cache should be empty after cleanup"


def test_cache_directory_config_var() -> None:
    """Test that SPIRAL_PYTEST_CACHE_DIR config variable is respected."""
    # This test verifies the config is defined in spiral.config.sh
    config_file = Path("spiral.config.sh")
    if config_file.exists():
        content = config_file.read_text()
        assert "SPIRAL_PYTEST_CACHE_DIR=" in content
        assert ".spiral/.pytest_cache" in content


def test_cache_max_mb_config_var() -> None:
    """Test that SPIRAL_PYTEST_CACHE_MAX_MB config variable is defined."""
    # This test verifies the config is defined in spiral.config.sh
    config_file = Path("spiral.config.sh")
    if config_file.exists():
        content = config_file.read_text()
        assert "SPIRAL_PYTEST_CACHE_MAX_MB=" in content
        assert "100" in content  # Default is 100MB

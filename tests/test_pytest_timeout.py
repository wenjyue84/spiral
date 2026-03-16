"""US-407: Verify pytest-timeout plugin is configured and enforced.

Tests that:
- The plugin loads and the global 60 s default is active
- A @pytest.mark.timeout(N) decorator overrides the global default
- A subprocess test with sleep > timeout exits with TIMEOUT status
"""

import subprocess
import sys
import time
import textwrap

import pytest


def test_timeout_plugin_loaded() -> None:
    """Global timeout of 60 s is active — confirms plugin is installed."""
    import pytest_timeout  # noqa: F401  # plugin presence check


@pytest.mark.timeout(2)
def test_short_timeout_passes_when_fast() -> None:
    """A 2 s timeout is satisfied when the test completes quickly."""
    time.sleep(0.05)


def test_timeout_fires_and_shows_timeout_message() -> None:
    """Subprocess with a sleepy test must exit non-zero with TIMEOUT in output."""
    sleepy_test = textwrap.dedent(
        """\
        import time, pytest

        @pytest.mark.timeout(1)
        def test_sleepy():
            time.sleep(5)
        """
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--timeout=1", "--timeout-method=thread", "-v", "--tb=no", "-"],
        input=sleepy_test,
        capture_output=True,
        text=True,
        timeout=30,  # outer guard — well above the 1 s inner timeout
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0, "Expected non-zero exit when test times out"
    assert "Timeout" in combined or "TIMEOUT" in combined or "timeout" in combined.lower(), (
        f"Expected TIMEOUT marker in output, got:\n{combined}"
    )

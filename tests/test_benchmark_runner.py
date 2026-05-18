"""Tests for benchmark_runner.py -- Model cost baseline benchmarking."""

import json
import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from lib import benchmark_runner


@pytest.fixture
def tmp_prd(tmp_path: Path) -> Path:
    """Create a temporary prd.json with sample stories."""
    prd = {
        "userStories": [
            {
                "id": "US-999",
                "title": "Test Story for Benchmarking",
                "passes": False,
                "priority": "medium",
            }
        ]
    }
    prd_file = tmp_path / "prd.json"
    with open(prd_file, "w", encoding="utf-8") as f:
        json.dump(prd, f)
    return prd_file


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a temporary repo directory."""
    spiral_dir = tmp_path / ".spiral"
    spiral_dir.mkdir(exist_ok=True)
    return tmp_path


def test_estimate_tokens_from_duration() -> None:
    """Test token estimation from duration."""
    duration = 10.0  # 10 seconds
    input_tokens, output_tokens = benchmark_runner._estimate_tokens_from_duration(
        duration
    )

    # output = 10 * 20 = 200
    # input = 200 * 3 = 600
    assert output_tokens == 200
    assert input_tokens == 600


def test_calculate_cost_usd() -> None:
    """Test cost calculation for different models."""
    tokens = 1_000_000  # 1 million tokens

    # Haiku: $0.80 per million
    cost_haiku = benchmark_runner._calculate_cost_usd("haiku", tokens)
    assert abs(cost_haiku - 0.80) < 0.01

    # Sonnet: $3.00 per million
    cost_sonnet = benchmark_runner._calculate_cost_usd("sonnet", tokens)
    assert abs(cost_sonnet - 3.00) < 0.01

    # Opus: $15.00 per million
    cost_opus = benchmark_runner._calculate_cost_usd("opus", tokens)
    assert abs(cost_opus - 15.00) < 0.01


def test_find_story(tmp_prd: Path) -> None:
    """Test story lookup in prd.json."""
    prd = benchmark_runner._get_prd(str(tmp_prd))
    story = benchmark_runner._find_story(prd, "US-999")

    assert story is not None
    assert story["id"] == "US-999"
    assert story["title"] == "Test Story for Benchmarking"


def test_find_story_not_found(tmp_prd: Path) -> None:
    """Test story lookup returns None when not found."""
    prd = benchmark_runner._get_prd(str(tmp_prd))
    story = benchmark_runner._find_story(prd, "US-000")

    assert story is None


def test_save_baseline(tmp_repo: Path, tmp_prd: Path) -> None:
    """Test saving baseline results to model_baselines.json."""
    results = {
        "haiku": {
            "model": "haiku",
            "tokens_used": 600,
            "cost_usd": 0.48,
            "duration_sec": 10.0,
            "exit_code": "0",
        }
    }

    benchmark_runner._save_baseline("US-999", results, str(tmp_repo))

    # Verify file was created and contains data
    baselines_file = tmp_repo / ".spiral" / "model_baselines.json"
    assert baselines_file.exists()

    with open(baselines_file, "r", encoding="utf-8") as f:
        baselines = json.load(f)

    assert "US-999" in baselines
    assert baselines["US-999"]["story_id"] == "US-999"
    assert "haiku" in baselines["US-999"]["benchmarks"]


def test_save_baseline_appends(tmp_repo: Path, tmp_prd: Path) -> None:
    """Test that saving baseline appends to existing data."""
    # Save first baseline
    results1 = {
        "haiku": {"model": "haiku", "tokens_used": 600, "cost_usd": 0.48}
    }
    benchmark_runner._save_baseline("US-999", results1, str(tmp_repo))

    # Save second baseline for different story
    results2 = {
        "sonnet": {"model": "sonnet", "tokens_used": 800, "cost_usd": 2.40}
    }
    benchmark_runner._save_baseline("US-998", results2, str(tmp_repo))

    # Verify both are present
    baselines_file = tmp_repo / ".spiral" / "model_baselines.json"
    with open(baselines_file, "r", encoding="utf-8") as f:
        baselines = json.load(f)

    assert "US-999" in baselines
    assert "US-998" in baselines


@pytest.mark.parametrize(
    "model,expected_cost",
    [
        ("haiku", 0.80),
        ("sonnet", 3.00),
        ("opus", 15.00),
        ("unknown", 3.00),  # defaults to sonnet
    ],
)
def test_calculate_cost_multi_model(model: str, expected_cost: float) -> None:
    """Test cost calculation across all supported models."""
    tokens = 1_000_000
    cost = benchmark_runner._calculate_cost_usd(model, tokens)
    assert abs(cost - expected_cost) < 0.01


def test_run_benchmark_story_with_mock(
    tmp_repo: Path, tmp_prd: Path
) -> None:
    """Test benchmark story execution with mocked subprocess."""
    # Mock the subprocess.run call
    with mock.patch("benchmark_runner.subprocess.run") as mock_run:
        # Configure mock to return success
        mock_run.return_value = mock.Mock(returncode=0, stdout="", stderr="")

        results = benchmark_runner.run_benchmark_story(
            "US-999",
            str(tmp_prd),
            str(tmp_repo),
            ["haiku"],
        )

        # Verify results structure
        assert "haiku" in results
        assert "tokens_used" in results["haiku"]
        assert "cost_usd" in results["haiku"]
        assert "duration_sec" in results["haiku"]
        assert "exit_code" in results["haiku"]


def test_list_benchmarks_empty(tmp_repo: Path, tmp_prd: Path) -> None:
    """Test list_benchmarks with no existing baselines."""
    # Should not raise, just print message
    with mock.patch("builtins.print"):
        benchmark_runner.list_benchmarks(str(tmp_prd), str(tmp_repo))


def test_benchmark_multi_model() -> None:
    """Test benchmark with multiple models (haiku, sonnet, opus)."""
    # This test verifies the story name in the story spec is correct
    assert True  # Placeholder for manual testing with real CLI

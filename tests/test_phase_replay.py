"""tests/test_phase_replay.py — Integration tests for lib/phase_replay.py (US-539).

Covers all three acceptance criteria:
  AC1: replay writes .spiral/replay-R-iter3.log and replay-state-R-iter3.json
  AC2: state JSON contains prd_snapshot (before/after), git_head, api_calls_count,
       tokens_used, output_files (with checksums)
  AC3: output_files checksum matches the fixture _research_output.json byte-for-byte;
       token count variance between two runs < 5%
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

# Add lib/ to path for direct import
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from phase_replay import (  # noqa: E402
    _collect_output_files,
    _parse_token_counts,
    _sha256_file,
    run_phase_replay,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fixture_runner(
    tokens: int = 1000,
    api_calls: int = 3,
    stdout_extra: str = "",
) -> Any:
    """Return a mock PhaseRunner that emits deterministic token counts."""

    def _run(
        phase: str,
        iteration: int,
        env: dict[str, str],
        cwd: Path,
    ) -> tuple[str, str, int]:
        stdout = f"tokens_used={tokens}\napi_calls={api_calls}\n{stdout_extra}"
        return stdout, "", 0

    return _run


def _make_prd(tmp_path: Path, stories: list[dict[str, Any]] | None = None) -> Path:
    prd: dict[str, Any] = {"userStories": stories or []}
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(json.dumps(prd), encoding="utf-8")
    return prd_file


# ---------------------------------------------------------------------------
# AC1 — log and state files are written to the correct paths
# ---------------------------------------------------------------------------


def test_log_file_created(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"

    run_phase_replay("R", 3, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    assert (scratch / "replay-R-iter3.log").exists(), "replay log must be created"


def test_state_file_created(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"

    run_phase_replay("R", 3, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    assert (scratch / "replay-state-R-iter3.json").exists(), "state JSON must be created"


def test_log_contains_phase_and_iteration(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"

    run_phase_replay("R", 3, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    log_content = (scratch / "replay-R-iter3.log").read_text(encoding="utf-8")
    assert "phase=R" in log_content
    assert "iteration=3" in log_content


def test_log_contains_exit_code(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"

    run_phase_replay("R", 3, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    log_content = (scratch / "replay-R-iter3.log").read_text(encoding="utf-8")
    assert "exit_code=0" in log_content


def test_phase_letter_normalised_to_upper(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"

    run_phase_replay("r", 1, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    assert (scratch / "replay-R-iter1.log").exists()
    assert (scratch / "replay-state-R-iter1.json").exists()


# ---------------------------------------------------------------------------
# AC2 — state JSON has all required fields
# ---------------------------------------------------------------------------


def test_state_json_has_required_fields(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path, stories=[{"id": "US-001", "title": "T", "passes": False}])
    scratch = tmp_path / ".spiral"

    state = run_phase_replay("R", 3, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    assert "prd_snapshot" in state
    assert "before" in state["prd_snapshot"]
    assert "after" in state["prd_snapshot"]
    assert "git_head" in state
    assert isinstance(state["api_calls_count"], int)
    assert isinstance(state["tokens_used"], int)
    assert isinstance(state["output_files"], list)


def test_prd_snapshot_before_matches_input(tmp_path: Path) -> None:
    prd_data: dict[str, Any] = {"userStories": [{"id": "US-001", "title": "Test", "passes": False}]}
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(json.dumps(prd_data), encoding="utf-8")
    scratch = tmp_path / ".spiral"

    state = run_phase_replay("R", 3, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    assert state["prd_snapshot"]["before"] == prd_data


def test_prd_snapshot_after_reflects_changes(tmp_path: Path) -> None:
    """If the phase runner modifies prd.json, prd_snapshot.after differs from before."""
    prd_data: dict[str, Any] = {"userStories": []}
    prd_file = tmp_path / "prd.json"
    prd_file.write_text(json.dumps(prd_data), encoding="utf-8")
    scratch = tmp_path / ".spiral"

    modified_prd: dict[str, Any] = {"userStories": [{"id": "US-NEW", "title": "Added"}]}

    def _mutating_runner(
        phase: str, iteration: int, env: dict[str, str], cwd: Path
    ) -> tuple[str, str, int]:
        # Simulate phase modifying prd.json
        prd_file.write_text(json.dumps(modified_prd), encoding="utf-8")
        return "tokens_used=100\napi_calls=1\n", "", 0

    state = run_phase_replay("R", 1, prd_file, scratch, tmp_path, phase_runner=_mutating_runner)

    assert state["prd_snapshot"]["before"] == prd_data
    assert state["prd_snapshot"]["after"] == modified_prd


def test_token_counts_captured_correctly(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"

    state = run_phase_replay(
        "R", 3, prd_file, scratch, tmp_path, phase_runner=_fixture_runner(tokens=2500, api_calls=7)
    )

    assert state["tokens_used"] == 2500
    assert state["api_calls_count"] == 7


def test_output_files_include_checksum(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"
    scratch.mkdir(parents=True, exist_ok=True)

    research_content = b'{"stories": [{"id": "US-999", "title": "R result"}]}'
    (scratch / "_research_output.json").write_bytes(research_content)

    state = run_phase_replay("R", 3, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    assert len(state["output_files"]) >= 1
    entry = state["output_files"][0]
    assert "path" in entry
    assert "checksum" in entry
    assert len(entry["checksum"]) == 64  # SHA-256 hex length


def test_state_json_written_to_disk(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"

    state = run_phase_replay("R", 5, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())
    state_path = scratch / "replay-state-R-iter5.json"

    on_disk = json.loads(state_path.read_text(encoding="utf-8"))
    assert on_disk["phase"] == state["phase"]
    assert on_disk["iteration"] == state["iteration"]
    assert on_disk["tokens_used"] == state["tokens_used"]


def test_git_head_is_string(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"

    state = run_phase_replay("R", 1, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    # git_head is a string (may be empty if not a git repo)
    assert isinstance(state["git_head"], str)


# ---------------------------------------------------------------------------
# AC3 — checksum matches fixture (byte-for-byte) and token variance < 5%
# ---------------------------------------------------------------------------


def test_output_checksum_matches_fixture(tmp_path: Path) -> None:
    """AC3: state output_files checksum equals the pre-existing fixture checksum."""
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"
    scratch.mkdir(parents=True, exist_ok=True)

    # Pre-create _research_output.json (fixture representing prior Phase R output)
    research_data = {"stories": [{"id": "US-100", "title": "AI agent research result"}]}
    research_content = json.dumps(research_data, indent=2).encode("utf-8")
    research_file = scratch / "_research_output.json"
    research_file.write_bytes(research_content)

    expected_checksum = _sha256_bytes(research_content)

    # Mock runner does NOT touch the output file
    state = run_phase_replay("R", 3, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    assert len(state["output_files"]) >= 1, "output_files must include _research_output.json"
    recorded_checksum = state["output_files"][0]["checksum"]

    # Byte-for-byte: checksum in state must equal fixture checksum
    assert recorded_checksum == expected_checksum, (
        f"Checksum mismatch: recorded={recorded_checksum}, expected={expected_checksum}"
    )


def test_token_variance_within_5_percent(tmp_path: Path) -> None:
    """AC3: token count variance between two deterministic replay runs < 5%."""
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"
    tokens = 1000

    state1 = run_phase_replay(
        "R", 1, prd_file, scratch, tmp_path, phase_runner=_fixture_runner(tokens=tokens)
    )
    state2 = run_phase_replay(
        "R", 2, prd_file, scratch, tmp_path, phase_runner=_fixture_runner(tokens=tokens)
    )

    t1, t2 = state1["tokens_used"], state2["tokens_used"]
    if t1 > 0:
        variance_pct = abs(t1 - t2) / t1 * 100.0
        assert variance_pct < 5.0, f"Token variance {variance_pct:.1f}% exceeds 5%"
    else:
        assert t2 == 0


def test_token_variance_5_percent_boundary(tmp_path: Path) -> None:
    """Variance exactly at the boundary: 4.9% must pass, 5.1% must fail."""
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"

    t1, t2_ok, t2_fail = 1000, 951, 949  # 4.9% and 5.1% off

    state_ok_1 = run_phase_replay(
        "R", 1, prd_file, scratch, tmp_path, phase_runner=_fixture_runner(tokens=t1)
    )
    state_ok_2 = run_phase_replay(
        "R", 2, prd_file, scratch, tmp_path, phase_runner=_fixture_runner(tokens=t2_ok)
    )
    var_ok = abs(state_ok_1["tokens_used"] - state_ok_2["tokens_used"]) / t1 * 100.0
    assert var_ok < 5.0

    state_fail_1 = run_phase_replay(
        "R", 3, prd_file, scratch, tmp_path, phase_runner=_fixture_runner(tokens=t1)
    )
    state_fail_2 = run_phase_replay(
        "R", 4, prd_file, scratch, tmp_path, phase_runner=_fixture_runner(tokens=t2_fail)
    )
    var_fail = abs(state_fail_1["tokens_used"] - state_fail_2["tokens_used"]) / t1 * 100.0
    assert var_fail >= 5.0


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------


def test_parse_token_counts_both_present() -> None:
    stdout = "tokens_used=4200\napi_calls=12\nsome other output\n"
    tokens, calls = _parse_token_counts(stdout)
    assert tokens == 4200
    assert calls == 12


def test_parse_token_counts_empty() -> None:
    tokens, calls = _parse_token_counts("")
    assert tokens == 0
    assert calls == 0


def test_parse_token_counts_partial() -> None:
    tokens, calls = _parse_token_counts("tokens_used=500\n")
    assert tokens == 500
    assert calls == 0


def test_sha256_file_correct(tmp_path: Path) -> None:
    data = b"hello world"
    f = tmp_path / "test.bin"
    f.write_bytes(data)
    assert _sha256_file(f) == hashlib.sha256(data).hexdigest()


def test_collect_output_files_missing(tmp_path: Path) -> None:
    scratch = tmp_path / ".spiral"
    scratch.mkdir()
    assert _collect_output_files("R", scratch) == []


def test_collect_output_files_present(tmp_path: Path) -> None:
    scratch = tmp_path / ".spiral"
    scratch.mkdir()
    data = b'{"stories": []}'
    (scratch / "_research_output.json").write_bytes(data)
    result = _collect_output_files("R", scratch)
    assert len(result) == 1
    assert result[0]["checksum"] == hashlib.sha256(data).hexdigest()


def test_state_json_is_serializable(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"

    state = run_phase_replay("R", 1, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    # Should not raise TypeError
    json.dumps(state)


def test_unknown_phase_returns_empty_output_files(tmp_path: Path) -> None:
    prd_file = _make_prd(tmp_path)
    scratch = tmp_path / ".spiral"

    state = run_phase_replay("X", 1, prd_file, scratch, tmp_path, phase_runner=_fixture_runner())

    assert state["output_files"] == []

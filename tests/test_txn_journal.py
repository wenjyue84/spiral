"""Tests for lib/txn_journal.py — write-ahead transaction journal."""

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from txn_journal import TxnJournal, _hash_file, rollback_orphaned, verify_all, write_entry

# ── Helpers ──────────────────────────────────────────────────────────────────


def _write_json(path, data):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── Tests ────────────────────────────────────────────────────────────────────


def test_committed_transaction_writes_both_files(tmp_path):
    """A successful transaction writes both files and marks committed."""
    journal_path = str(tmp_path / "journal.jsonl")
    file_a = str(tmp_path / "a.json")
    file_b = str(tmp_path / "b.json")
    _write_json(file_a, {"old": "a"})
    _write_json(file_b, {"old": "b"})

    journal = TxnJournal(journal_path)
    with journal.transaction("test_txn") as txn:
        txn.write_json(file_a, {"new": "a"})
        txn.write_json(file_b, {"new": "b"})

    assert _read_json(file_a) == {"new": "a"}
    assert _read_json(file_b) == {"new": "b"}

    # Journal should have pending + committed entries
    with open(journal_path, encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]
    statuses = [r["status"] for r in lines]
    assert "committed" in statuses


def test_exception_preserves_backup_files(tmp_path):
    """If an exception occurs, .bak files are preserved for recovery."""
    journal_path = str(tmp_path / "journal.jsonl")
    file_a = str(tmp_path / "a.json")
    _write_json(file_a, {"original": True})

    journal = TxnJournal(journal_path)
    with pytest.raises(ValueError):
        with journal.transaction("failing_txn") as txn:
            txn.write_json(file_a, {"corrupted": True})
            raise ValueError("crash!")

    # The file was written (the write itself succeeded before the crash)
    # but .bak should exist for recovery
    assert os.path.isfile(file_a + ".bak")
    assert _read_json(file_a + ".bak") == {"original": True}


def test_recover_rolls_back_incomplete_transaction(tmp_path):
    """Recovery restores .bak files for uncommitted transactions."""
    journal_path = str(tmp_path / "journal.jsonl")
    file_a = str(tmp_path / "a.json")
    _write_json(file_a, {"original": True})

    journal = TxnJournal(journal_path)
    # Simulate a crash mid-transaction
    with pytest.raises(ValueError):
        with journal.transaction("crash_txn") as txn:
            txn.write_json(file_a, {"corrupted": True})
            raise ValueError("simulated crash")

    # file_a is corrupted, .bak exists
    assert _read_json(file_a) == {"corrupted": True}
    assert _read_json(file_a + ".bak") == {"original": True}

    # Recovery should restore the original
    actions = journal.recover()
    assert len(actions) == 1
    assert _read_json(file_a) == {"original": True}
    assert not os.path.isfile(file_a + ".bak")


def test_recover_ignores_committed_transactions(tmp_path):
    """Recovery does not roll back committed transactions."""
    journal_path = str(tmp_path / "journal.jsonl")
    file_a = str(tmp_path / "a.json")
    _write_json(file_a, {"original": True})

    journal = TxnJournal(journal_path)
    with journal.transaction("good_txn") as txn:
        txn.write_json(file_a, {"updated": True})

    # .bak file may or may not exist — recovery should not revert
    actions = journal.recover()
    assert len(actions) == 0
    assert _read_json(file_a) == {"updated": True}


def test_recover_with_no_journal_file(tmp_path):
    """Recovery with no journal file is a no-op."""
    journal_path = str(tmp_path / "nonexistent.jsonl")
    journal = TxnJournal(journal_path)
    actions = journal.recover()
    assert actions == []


def test_journal_survives_partial_line(tmp_path):
    """A corrupt last line in the journal doesn't break recovery."""
    journal_path = str(tmp_path / "journal.jsonl")
    file_a = str(tmp_path / "a.json")
    _write_json(file_a, {"original": True})

    journal = TxnJournal(journal_path)
    # Simulate a crash that left a partial pending entry
    with pytest.raises(ValueError):
        with journal.transaction("partial_txn") as txn:
            txn.write_json(file_a, {"bad": True})
            raise ValueError("crash!")

    # Append a corrupt line to simulate truncated write
    with open(journal_path, "a", encoding="utf-8") as f:
        f.write('{"id":"xyz","status":"pend\n')

    # Recovery should still work for the valid pending entry
    actions = journal.recover()
    assert len(actions) >= 1
    assert _read_json(file_a) == {"original": True}


def test_write_json_creates_new_file(tmp_path):
    """write_json works even when the target file doesn't exist yet."""
    journal_path = str(tmp_path / "journal.jsonl")
    new_file = str(tmp_path / "new.json")

    journal = TxnJournal(journal_path)
    with journal.transaction("create_txn") as txn:
        txn.write_json(new_file, {"created": True})

    assert _read_json(new_file) == {"created": True}


# ── Tests for write_entry / verify_all / rollback_orphaned ───────────────────


def test_write_entry_stores_required_fields(tmp_path):
    """write_entry() writes all AC-required fields to the journal."""
    prd = str(tmp_path / "prd.json")
    _write_json(prd, {"userStories": []})
    journal_path = str(tmp_path / "journal.jsonl")

    pre_hash = _hash_file(prd)
    write_entry(
        "US-001",
        worker_pid=12345,
        operation="update",
        pre_hash=pre_hash,
        journal_path=journal_path,
        backup_path=prd + ".bak",
    )

    with open(journal_path, encoding="utf-8") as f:
        entry = json.loads(f.readline())

    assert entry["story_id"] == "US-001"
    assert entry["worker_pid"] == 12345
    assert entry["operation"] == "update"
    assert entry["pre_hash"] == pre_hash
    assert "timestamp" in entry
    assert entry["backup_path"] == prd + ".bak"


def test_verify_all_empty_journal(tmp_path):
    """verify_all() returns [] when journal does not exist."""
    journal_path = str(tmp_path / "nonexistent.jsonl")
    assert verify_all(journal_path) == []


def test_rollback_orphaned_restores_from_backup(tmp_path, monkeypatch):
    """rollback_orphaned() restores prd.json from backup for an orphaned entry."""
    prd = str(tmp_path / "prd.json")
    bak = prd + ".bak"
    journal_path = str(tmp_path / "journal.jsonl")

    original = {"userStories": [{"id": "US-001", "passes": False}]}
    corrupted = {"userStories": []}
    _write_json(prd, original)
    _write_json(bak, original)

    # Write entry and simulate "prd.json corrupted before commit"
    write_entry(
        "US-001",
        worker_pid=os.getpid(),
        operation="update",
        pre_hash=_hash_file(bak),
        journal_path=journal_path,
        backup_path=bak,
    )
    _write_json(prd, corrupted)

    # Patch verify_all to return the orphaned entry (no git commit exists)
    monkeypatch.setattr(
        "txn_journal.subprocess.run",
        lambda *a, **kw: type("R", (), {"stdout": "", "returncode": 1})(),
    )

    actions = rollback_orphaned(prd, journal_path=journal_path)
    assert len(actions) == 1
    assert _read_json(prd) == original
    assert not os.path.isfile(bak)


def test_sigkill_simulation(tmp_path, monkeypatch):
    """Simulate SIGKILL mid-write: recovery restores prd.json consistency."""
    prd = str(tmp_path / "prd.json")
    bak = prd + ".bak"
    journal_path = str(tmp_path / "journal.jsonl")

    original_data = {"userStories": [{"id": "US-999", "passes": False}]}
    _write_json(prd, original_data)
    _write_json(bak, original_data)

    # Subprocess writes entry + corrupts prd.json then exits cleanly
    # (simulating the state left by SIGKILL after file write but before commit)
    helper_code = f"""
import json, sys, os
sys.path.insert(0, {repr(os.path.join(os.path.dirname(__file__), "..", "lib"))})
from txn_journal import write_entry
write_entry(
    'US-999', worker_pid=os.getpid(), operation='update', pre_hash='abc',
    journal_path={repr(journal_path)}, backup_path={repr(bak)},
)
with open({repr(prd)}, 'w', encoding='utf-8') as f:
    json.dump({{'userStories': []}}, f)
"""
    result = subprocess.run(
        [sys.executable, "-c", helper_code],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr

    # prd.json is now "corrupted"; journal has an orphaned entry
    assert _read_json(prd) == {"userStories": []}

    # Patch subprocess.run inside txn_journal so verify_all returns the entry
    # (pretend no git commit found for US-999)
    monkeypatch.setattr(
        "txn_journal.subprocess.run",
        lambda *a, **kw: type("R", (), {"stdout": "", "returncode": 1})(),
    )

    actions = rollback_orphaned(prd, journal_path=journal_path)
    assert len(actions) == 1
    assert _read_json(prd) == original_data

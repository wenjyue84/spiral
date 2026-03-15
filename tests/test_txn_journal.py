"""Tests for lib/txn_journal.py — write-ahead transaction journal."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from txn_journal import TxnJournal


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

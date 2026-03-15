#!/usr/bin/env python3
"""
SPIRAL — Write-Ahead Transaction Journal

Provides crash-safe multi-file writes. Before modifying files, the journal
records intent + creates backups. After all writes succeed, the transaction
is marked committed. On startup, incomplete transactions are rolled back
by restoring .bak files.

Usage:
    from txn_journal import TxnJournal

    journal = TxnJournal(".spiral/_txn_journal.jsonl")
    with journal.transaction("phase_m_merge") as txn:
        txn.write_json("overflow.json", overflow_data)
        txn.write_json("prd.json", prd_data)

    # On startup — roll back any incomplete transactions:
    actions = journal.recover()
"""
import argparse
import os
import sys
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

sys.path.insert(0, os.path.dirname(__file__))
from spiral_io import append_jsonl, atomic_write_json, configure_utf8_stdout, safe_read_jsonl

configure_utf8_stdout()


class TxnJournal:
    def __init__(self, journal_path: str) -> None:
        self.journal_path = journal_path

    @contextmanager
    def transaction(self, label: str) -> Generator["TxnWriter", None, None]:
        """All writes in the block are journaled. Committed on normal exit,
        backup files preserved for rollback on crash."""
        txn_id = uuid.uuid4().hex[:12]
        writer = TxnWriter(txn_id, label, self.journal_path)
        try:
            yield writer
        except BaseException:
            # Exception — leave journal in pending state for recovery
            raise
        else:
            # Success — mark committed
            append_jsonl(self.journal_path, {"id": txn_id, "status": "committed"})

    def recover(self) -> list[str]:
        """Roll back incomplete transactions by restoring .bak files.
        Returns list of actions taken. Safe to call when no journal exists."""
        if not os.path.isfile(self.journal_path):
            return []

        records = safe_read_jsonl(self.journal_path)
        if not records:
            return []

        # Build transaction state: find pending entries without matching committed
        committed_ids: set[str] = set()
        pending: dict[str, dict[str, Any]] = {}

        for rec in records:
            txn_id = rec.get("id", "")
            status = rec.get("status", "")
            if status == "committed":
                committed_ids.add(txn_id)
            elif status == "pending":
                pending[txn_id] = rec

        actions: list[str] = []
        for txn_id, rec in pending.items():
            if txn_id in committed_ids:
                continue  # committed — no rollback needed
            label = rec.get("label", "unknown")
            files = rec.get("files", [])
            for f_info in files:
                backup = f_info.get("backup", "")
                target = f_info.get("path", "")
                if backup and os.path.isfile(backup) and target:
                    import shutil
                    shutil.copy2(backup, target)
                    os.unlink(backup)
                    msg = f"Rolled back {target} from {backup} (txn {txn_id}: {label})"
                    actions.append(msg)
                    print(f"[txn_journal] {msg}", file=sys.stderr)

        # Clear the journal after recovery
        if actions:
            try:
                os.unlink(self.journal_path)
            except OSError:
                pass

        return actions


class TxnWriter:
    def __init__(self, txn_id: str, label: str, journal_path: str) -> None:
        self.txn_id = txn_id
        self.label = label
        self.journal_path = journal_path
        self._files: list[dict[str, str]] = []
        self._pending_written = False

    def write_json(self, path: str, data: Any) -> None:
        """Create .bak of current file, then write new data atomically."""
        backup_path = path + ".bak"

        # Create backup of existing file
        if os.path.isfile(path):
            import shutil
            shutil.copy2(path, backup_path)

        self._files.append({"path": path, "backup": backup_path})

        # Write pending record on first write
        if not self._pending_written:
            append_jsonl(self.journal_path, {
                "id": self.txn_id,
                "label": self.label,
                "status": "pending",
                "files": self._files,
            })
            self._pending_written = True
        else:
            # Update the pending record with the new file list by re-appending
            # (JSONL: last pending entry for this ID wins during recovery)
            append_jsonl(self.journal_path, {
                "id": self.txn_id,
                "label": self.label,
                "status": "pending",
                "files": self._files,
            })

        # Write the actual file
        atomic_write_json(path, data)

    def cleanup_backups(self) -> None:
        """Remove .bak files after successful commit."""
        for f_info in self._files:
            backup = f_info.get("backup", "")
            if backup and os.path.isfile(backup):
                try:
                    os.unlink(backup)
                except OSError:
                    pass


def _cli_recover() -> int:
    """CLI entry point for transaction recovery."""
    parser = argparse.ArgumentParser(description="SPIRAL transaction journal recovery")
    parser.add_argument("action", choices=["recover"], help="Action to perform")
    parser.add_argument("--journal", required=True, help="Path to journal file")
    args = parser.parse_args()

    journal = TxnJournal(args.journal)
    actions = journal.recover()
    if actions:
        for a in actions:
            print(f"  [txn] {a}")
        print(f"  [txn] Recovered {len(actions)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(_cli_recover())

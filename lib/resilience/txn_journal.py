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
import datetime
import hashlib
import os
import shutil
import subprocess
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
            append_jsonl(
                self.journal_path,
                {
                    "id": self.txn_id,
                    "label": self.label,
                    "status": "pending",
                    "files": self._files,
                },
            )
            self._pending_written = True
        else:
            # Update the pending record with the new file list by re-appending
            # (JSONL: last pending entry for this ID wins during recovery)
            append_jsonl(
                self.journal_path,
                {
                    "id": self.txn_id,
                    "label": self.label,
                    "status": "pending",
                    "files": self._files,
                },
            )

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


_DEFAULT_JOURNAL = ".spiral/_prd_journal.jsonl"


def _hash_file(path: str) -> str:
    """Return SHA-256 hex digest of file contents, or '' if file missing."""
    if not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def write_entry(
    story_id: str,
    worker_pid: int,
    operation: str,
    pre_hash: str,
    *,
    journal_path: str = _DEFAULT_JOURNAL,
    backup_path: str = "",
) -> None:
    """Append a journal entry recording intent to mutate prd.json.

    Call this BEFORE the prd.json write. ``pre_hash`` should be the SHA-256
    of prd.json before mutation (use ``_hash_file``). ``backup_path`` points
    to a pre-mutation backup so ``rollback_orphaned`` can restore the file.
    """
    entry: dict[str, Any] = {
        "story_id": story_id,
        "worker_pid": worker_pid,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "operation": operation,
        "pre_hash": pre_hash,
        "backup_path": backup_path,
    }
    append_jsonl(journal_path, entry)


def verify_all(
    journal_path: str = _DEFAULT_JOURNAL,
) -> list[dict[str, Any]]:
    """Return journal entries that have no corresponding git commit.

    A journaled write is considered committed when a git commit exists whose
    message contains the ``story_id``. Entries with no matching commit are
    'orphaned' — the writer was killed before committing.
    """
    records = safe_read_jsonl(journal_path)
    orphaned: list[dict[str, Any]] = []
    for rec in records:
        story_id = rec.get("story_id", "")
        if not story_id:
            continue
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", f"--grep={story_id}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if story_id not in result.stdout:
                orphaned.append(rec)
        except (OSError, subprocess.TimeoutExpired):
            orphaned.append(rec)
    return orphaned


def rollback_orphaned(
    prd_path: str,
    journal_path: str = _DEFAULT_JOURNAL,
) -> list[str]:
    """Restore prd.json from backup for each orphaned journal entry.

    Calls ``verify_all`` to find uncommitted writes, then restores the
    pre-mutation backup identified in the journal entry.  Returns a list
    of human-readable action strings.
    """
    orphaned = verify_all(journal_path)
    actions: list[str] = []
    for rec in orphaned:
        backup = rec.get("backup_path", "")
        story_id = rec.get("story_id", "?")
        if backup and os.path.isfile(backup):
            shutil.copy2(backup, prd_path)
            try:
                os.unlink(backup)
            except OSError:
                pass
            msg = f"Rolled back {prd_path} (orphaned write for {story_id})"
            actions.append(msg)
            print(f"[txn_journal] {msg}", file=sys.stderr)
    if actions:
        try:
            os.unlink(journal_path)
        except OSError:
            pass
    return actions


def _cli_main() -> int:
    """CLI entry point: write-entry, verify, recover."""
    parser = argparse.ArgumentParser(description="SPIRAL prd.json transaction journal")
    parser.add_argument(
        "action",
        choices=["write-entry", "verify", "recover"],
        help="Action to perform",
    )
    parser.add_argument("--journal", default=_DEFAULT_JOURNAL, help="Path to journal file")
    # write-entry args
    parser.add_argument("--story-id", default="", help="Story ID being mutated")
    parser.add_argument("--operation", default="update", help="add|update|delete")
    parser.add_argument("--prd", default="prd.json", help="Path to prd.json (for pre-hash)")
    parser.add_argument("--backup", default="", help="Path where backup was created")
    args = parser.parse_args()

    if args.action == "write-entry":
        pre_hash = _hash_file(args.prd)
        write_entry(
            args.story_id,
            worker_pid=os.getpid(),
            operation=args.operation,
            pre_hash=pre_hash,
            journal_path=args.journal,
            backup_path=args.backup,
        )
        print(f"[txn_journal] Entry written for {args.story_id}")
        return 0

    if args.action == "verify":
        orphaned = verify_all(args.journal)
        if orphaned:
            for rec in orphaned:
                print(f"  [txn] Orphaned: {rec.get('story_id')} at {rec.get('timestamp')}")
            print(f"  [txn] {len(orphaned)} orphaned write(s) detected", file=sys.stderr)
        return 1 if orphaned else 0

    # recover — original TxnJournal recovery + new prd.json rollback
    journal = TxnJournal(args.journal)
    old_actions = journal.recover()
    new_actions = rollback_orphaned(args.prd, journal_path=args.journal)
    all_actions = old_actions + new_actions
    if all_actions:
        for a in all_actions:
            print(f"  [txn] {a}")
        print(f"  [txn] Recovered {len(all_actions)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())

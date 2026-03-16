#!/usr/bin/env python3
"""
Failure Attribution for Multi-Agent SPIRAL Runs

Tracks worker failures, identifies cascade failures (downstream failures caused by
upstream worker failures sharing resources), and provides causal chain diagnosis.

Features:
  - Records worker_id, failure_type (local|cascade), root_cause_worker_id, contended_resource
  - Cascade detection: if worker B fails within 30s of worker A and shares resource, B is cascade
  - Structured failures section in checkpoint JSON
  - 'spiral diagnose --run <run-id>' command to print causal chain
"""

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional


@dataclass
class WorkerFailure:
    """Represents a single worker failure event."""

    worker_id: int
    story_id: str
    failure_type: str  # "local" or "cascade"
    timestamp: str  # ISO8601
    error_message: str
    contended_resource: Optional[str] = None  # e.g., "worktree", "branch", "prd.json", "port:8000"
    root_cause_worker_id: Optional[int] = None  # if cascade, which worker caused this
    root_cause_timestamp: Optional[str] = None  # when root cause occurred


@dataclass
class WorkerResources:
    """Track resources allocated to a worker."""

    worker_id: int
    worktree_path: str
    branch_name: str
    port_allocated: Optional[int] = None
    docker_volume_id: Optional[str] = None


class FailureAttributor:
    """
    Detects and attributes worker failures.

    Cascade detection algorithm:
      1. Record each worker failure with timestamp
      2. For each failure, look back 30s for other worker failures
      3. If found, check if both workers share a resource
      4. If resource overlap, mark as cascade with root_cause_worker_id
    """

    CASCADE_WINDOW_SECONDS = 30

    def __init__(self, checkpoint_path: str):
        """Initialize with checkpoint file path."""
        self.checkpoint_path = Path(checkpoint_path)
        self.failures: list[WorkerFailure] = []
        self.resources: dict[int, WorkerResources] = {}
        self._load_checkpoint()

    def _load_checkpoint(self) -> None:
        """Load existing failures and resources from checkpoint."""
        if not self.checkpoint_path.exists():
            return
        try:
            with open(self.checkpoint_path, encoding="utf-8") as f:
                ckpt = json.load(f)
                if "failures" in ckpt:
                    for f_dict in ckpt["failures"]:
                        self.failures.append(WorkerFailure(**f_dict))
                if "worker_resources" in ckpt:
                    for res_dict in ckpt["worker_resources"]:
                        wid = res_dict.get("worker_id")
                        if wid is not None:
                            self.resources[wid] = WorkerResources(**res_dict)
        except (json.JSONDecodeError, ValueError):
            pass  # Corrupted checkpoint, start fresh

    def register_worker_resources(
        self,
        worker_id: int,
        worktree_path: str,
        branch_name: str,
        port: Optional[int] = None,
        docker_volume_id: Optional[str] = None,
    ) -> None:
        """Register resources allocated to a worker."""
        self.resources[worker_id] = WorkerResources(
            worker_id=worker_id,
            worktree_path=worktree_path,
            branch_name=branch_name,
            port_allocated=port,
            docker_volume_id=docker_volume_id,
        )

    def record_failure(
        self,
        worker_id: int,
        story_id: str,
        error_message: str,
        contended_resource: Optional[str] = None,
    ) -> WorkerFailure:
        """
        Record a worker failure and detect if it's a cascade.

        Returns the WorkerFailure with failure_type and root_cause_worker_id set.
        """
        timestamp = datetime.utcnow().isoformat() + "Z"
        failure_type = "local"
        root_cause_worker_id: Optional[int] = None
        root_cause_timestamp: Optional[str] = None

        # Detect cascade: look back CASCADE_WINDOW_SECONDS for upstream failures
        cascade_candidate = self._find_cascade_root(worker_id, timestamp)
        if cascade_candidate:
            failure_type = "cascade"
            root_cause_worker_id = cascade_candidate.worker_id
            root_cause_timestamp = cascade_candidate.timestamp

        failure = WorkerFailure(
            worker_id=worker_id,
            story_id=story_id,
            failure_type=failure_type,
            timestamp=timestamp,
            error_message=error_message,
            contended_resource=contended_resource or self._infer_contended_resource(worker_id, root_cause_worker_id),
            root_cause_worker_id=root_cause_worker_id,
            root_cause_timestamp=root_cause_timestamp,
        )
        self.failures.append(failure)
        return failure

    def _find_cascade_root(self, worker_id: int, current_ts: str) -> Optional[WorkerFailure]:
        """
        Look for an upstream failure within CASCADE_WINDOW_SECONDS that shares resources.
        """
        try:
            current_dt = datetime.fromisoformat(current_ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            # Fallback: treat as current time
            current_dt = datetime.utcnow()

        cutoff_dt = current_dt - timedelta(seconds=self.CASCADE_WINDOW_SECONDS)

        # Check failures in reverse chronological order (most recent first)
        for prior_failure in reversed(self.failures):
            try:
                prior_dt = datetime.fromisoformat(prior_failure.timestamp.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            if prior_dt < cutoff_dt:
                break  # Beyond window

            if prior_failure.worker_id == worker_id:
                continue  # Same worker, not cascade

            # Check for resource overlap
            if self._share_resources(prior_failure.worker_id, worker_id):
                return prior_failure

        return None

    def _share_resources(self, worker_a: int, worker_b: int) -> bool:
        """Check if two workers share any allocated resources."""
        res_a = self.resources.get(worker_a)
        res_b = self.resources.get(worker_b)
        if not res_a or not res_b:
            return False

        # Shared worktree base directory (different instances but same repo)
        if res_a.worktree_path and res_b.worktree_path:
            # Extract base path (e.g., /repo/.spiral-workers for both)
            base_a = str(Path(res_a.worktree_path).parent)
            base_b = str(Path(res_b.worktree_path).parent)
            if base_a == base_b:
                return True

        # Port conflict (only if both have ports)
        if res_a.port_allocated and res_b.port_allocated:
            if res_a.port_allocated == res_b.port_allocated:
                return True

        # Shared docker volume
        if res_a.docker_volume_id and res_b.docker_volume_id:
            if res_a.docker_volume_id == res_b.docker_volume_id:
                return True

        return False

    def _infer_contended_resource(self, worker_id: int, root_cause_id: Optional[int]) -> Optional[str]:
        """Infer which resource was contended based on worker allocation.

        Returns the most specific/important shared resource.
        """
        if not root_cause_id:
            return None

        res_a = self.resources.get(worker_id)
        res_b = self.resources.get(root_cause_id)
        if not res_a or not res_b:
            return None

        # Check which resources they share (prioritize more specific ones)
        # Check port conflict first (most explicit resource conflict)
        if res_a.port_allocated and res_b.port_allocated:
            if res_a.port_allocated == res_b.port_allocated:
                return f"port:{res_a.port_allocated}"

        # Check docker volume
        if res_a.docker_volume_id and res_b.docker_volume_id:
            if res_a.docker_volume_id == res_b.docker_volume_id:
                return f"docker_volume:{res_a.docker_volume_id}"

        # Check worktree (least specific, but still valid)
        if res_a.worktree_path and res_b.worktree_path:
            base_a = str(Path(res_a.worktree_path).parent)
            base_b = str(Path(res_b.worktree_path).parent)
            if base_a == base_b:
                return "worktree"

        return None

    def save_checkpoint(self) -> None:
        """Save failures and resources to checkpoint (preserves other checkpoint fields)."""
        ckpt = {}
        if self.checkpoint_path.exists():
            try:
                with open(self.checkpoint_path, encoding="utf-8") as f:
                    ckpt = json.load(f)
            except (json.JSONDecodeError, ValueError):
                pass

        # Add/update failures
        ckpt["failures"] = [asdict(f) for f in self.failures]

        # Add/update worker resources
        ckpt["worker_resources"] = [asdict(r) for r in self.resources.values()]

        with open(self.checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(ckpt, f, indent=2)

    def get_causal_chain(self) -> dict[str, Any]:
        """Generate a causal failure chain for diagnosis."""
        # Build a dependency graph: failure -> [downstream_failures]
        causality: dict[int, list[WorkerFailure]] = {}
        roots: list[WorkerFailure] = []

        for failure in self.failures:
            if failure.failure_type == "local":
                roots.append(failure)
            else:
                root_id = failure.root_cause_worker_id
                if root_id is not None:
                    if root_id not in causality:
                        causality[root_id] = []
                    causality[root_id].append(failure)

        # Build chains
        chains: list[list[WorkerFailure]] = []
        for root in roots:
            chain: list[WorkerFailure] = [root]
            queue: list[int] = [root.worker_id]
            while queue:
                current_id = queue.pop(0)
                if current_id in causality:
                    for downstream in causality[current_id]:
                        chain.append(downstream)
                        queue.append(downstream.worker_id)
            chains.append(chain)

        return {
            "total_failures": len(self.failures),
            "cascade_failures": sum(1 for f in self.failures if f.failure_type == "cascade"),
            "local_failures": sum(1 for f in self.failures if f.failure_type == "local"),
            "chains": [
                {
                    "root_worker": chain[0].worker_id,
                    "root_story": chain[0].story_id,
                    "root_timestamp": chain[0].timestamp,
                    "cascade_count": len(chain) - 1,
                    "failures": [asdict(c) for c in chain],
                }
                for chain in chains
            ],
        }


def main() -> int:
    """CLI interface for failure attribution."""
    parser = argparse.ArgumentParser(description="Multi-agent failure attribution")
    subparsers = parser.add_subparsers(dest="cmd", help="Command")

    # record-failure subcommand
    record = subparsers.add_parser("record-failure", help="Record a worker failure")
    record.add_argument("--checkpoint", required=True, help="Path to checkpoint.json")
    record.add_argument("--worker-id", type=int, required=True, help="Worker ID")
    record.add_argument("--story-id", required=True, help="Story ID")
    record.add_argument("--error", required=True, help="Error message")
    record.add_argument("--resource", help="Contended resource (optional)")

    # register-worker subcommand
    reg = subparsers.add_parser("register-worker", help="Register worker resources")
    reg.add_argument("--checkpoint", required=True, help="Path to checkpoint.json")
    reg.add_argument("--worker-id", type=int, required=True, help="Worker ID")
    reg.add_argument("--worktree", required=True, help="Worktree path")
    reg.add_argument("--branch", required=True, help="Branch name")
    reg.add_argument("--port", type=int, help="Port allocated (optional)")
    reg.add_argument("--docker-volume", help="Docker volume ID (optional)")

    # diagnose subcommand
    diag = subparsers.add_parser("diagnose", help="Diagnose failure chains")
    diag.add_argument("--checkpoint", required=True, help="Path to checkpoint.json")
    diag.add_argument("--format", choices=["json", "text"], default="text", help="Output format")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        return 1

    attributor = FailureAttributor(args.checkpoint)

    if args.cmd == "record-failure":
        failure = attributor.record_failure(
            worker_id=args.worker_id,
            story_id=args.story_id,
            error_message=args.error,
            contended_resource=args.resource,
        )
        attributor.save_checkpoint()
        print(json.dumps(asdict(failure), indent=2))
        return 0

    elif args.cmd == "register-worker":
        attributor.register_worker_resources(
            worker_id=args.worker_id,
            worktree_path=args.worktree,
            branch_name=args.branch,
            port=args.port,
            docker_volume_id=args.docker_volume,
        )
        attributor.save_checkpoint()
        print(f"Registered worker {args.worker_id}")
        return 0

    elif args.cmd == "diagnose":
        chain = attributor.get_causal_chain()
        if args.format == "json":
            print(json.dumps(chain, indent=2))
        else:
            total = chain.get("total_failures", 0)  # type: ignore
            local = chain.get("local_failures", 0)  # type: ignore
            cascade = chain.get("cascade_failures", 0)  # type: ignore
            print(f"Total failures: {total}")
            print(f"  Local: {local}, Cascade: {cascade}")
            chains_list = chain.get("chains", [])  # type: ignore
            for idx, chain_item in enumerate(chains_list, 1):
                root_w = chain_item.get("root_worker", "?")  # type: ignore
                root_s = chain_item.get("root_story", "?")  # type: ignore
                print(f"\nChain {idx} (root: worker {root_w}, story {root_s}):")
                failures = chain_item.get("failures", [])  # type: ignore
                for failure_item in failures:
                    f_type = failure_item.get("failure_type", "unknown")  # type: ignore
                    f_id = failure_item.get("worker_id", "?")  # type: ignore
                    s_id = failure_item.get("story_id", "?")  # type: ignore
                    f_err = failure_item.get("error_message", "")[:60]  # type: ignore
                    f_res = failure_item.get("contended_resource")  # type: ignore
                    indent = "  " if f_type == "local" else "    -> "
                    print(f"{indent}{f_type.upper()}: worker {f_id} ({s_id}) — {f_err}")
                    if f_res:
                        print(f"       Resource: {f_res}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())

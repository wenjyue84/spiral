#!/usr/bin/env python3
"""
Story compatibility matrix for Phase M — parallel batching safety.

Scores story pairs by filesTouch overlap and blockers, detects circular
dependencies, and suggests independent batches for parallel execution.
"""

from typing import Any


class CompatibilityMatrix:
    """Scores story pairs and groups them for safe parallel execution.

    Computes compatibility scores based on filesTouch overlap:
    - 0.0: stories have no shared filesTouch
    - 1.0: stories have complete overlap in filesTouch

    Validates DAG (Directed Acyclic Graph) of story dependencies to detect
    circular blockers that would prevent parallel execution.

    Suggests batches of independent stories that can run in parallel.
    """

    def __init__(self, stories: list[dict[str, Any]]) -> None:
        """Initialize the compatibility matrix.

        Args:
            stories: List of story dicts, each with 'id', 'filesTouch', and optional 'dependencies'
        """
        self.stories = stories
        # Build a lookup map: id → story
        self.story_map = {s.get("id", ""): s for s in stories if s.get("id")}

    def compute_score(self, id_a: str, id_b: str) -> float:
        """Compute compatibility score between two stories (0.0 to 1.0).

        Score is based on filesTouch overlap:
        - 0.0: no shared files between stories
        - 1.0: complete overlap (all files are shared)
        - 0.0 < score < 1.0: partial overlap

        Args:
            id_a: First story ID
            id_b: Second story ID

        Returns:
            Float score between 0.0 and 1.0
        """
        story_a = self.story_map.get(id_a)
        story_b = self.story_map.get(id_b)

        if not story_a or not story_b:
            return 0.0

        files_a = set(story_a.get("filesTouch", []))
        files_b = set(story_b.get("filesTouch", []))

        # No files = no conflict
        if not files_a or not files_b:
            return 0.0

        # Calculate Jaccard similarity as the compatibility score
        intersection = len(files_a & files_b)
        union = len(files_a | files_b)

        if union == 0:
            return 0.0

        return intersection / union

    def validate_dag(self) -> None:
        """Validate that story dependencies form a DAG (no cycles).

        Raises:
            ValueError: If a circular dependency is detected, lists all nodes in the cycle
        """
        # Build adjacency list for dependency graph
        graph: dict[str, list[str]] = {}
        for story in self.stories:
            story_id = story.get("id", "")
            if story_id:
                graph[story_id] = story.get("dependencies", [])

        # DFS-based cycle detection
        visited: set[str] = set()
        rec_stack: set[str] = set()
        cycle_path: list[str] = []

        def _dfs(node: str) -> bool:
            """DFS helper to detect cycles. Returns True if cycle found."""
            visited.add(node)
            rec_stack.add(node)
            cycle_path.append(node)

            for neighbor in graph.get(node, []):
                if neighbor not in visited:
                    if _dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    # Found cycle: extract the cycle portion
                    if neighbor in cycle_path:
                        cycle_start = cycle_path.index(neighbor)
                        cycle = cycle_path[cycle_start:] + [neighbor]
                        raise ValueError(f"Circular dependency detected: {' → '.join(cycle)}")
                    return True

            cycle_path.pop()
            rec_stack.remove(node)
            return False

        # Check all nodes for cycles
        for node in graph:
            if node not in visited:
                if _dfs(node):
                    break

    def suggest_batches(self) -> list[list[str]]:
        """Suggest independent batches of stories for parallel execution.

        Groups stories into batches where stories within a batch have no
        filesTouch overlap and no direct dependencies between them.

        Returns:
            List of batches, where each batch is a list of story IDs
        """
        # Start with all stories as ungrouped
        ungrouped = {s.get("id", "") for s in self.stories if s.get("id")}
        batches: list[list[str]] = []

        while ungrouped:
            # Start a new batch with an arbitrary ungrouped story
            batch: list[str] = [ungrouped.pop()]
            batch_files: set[str] = set(self.story_map[batch[0]].get("filesTouch", []))

            # Try to add more stories to this batch
            candidates = list(ungrouped)
            for story_id in candidates:
                story = self.story_map[story_id]
                story_files = set(story.get("filesTouch", []))
                story_deps = set(story.get("dependencies", []))

                # Can add if:
                # 1. No file overlap with batch
                # 2. No dependencies on stories in batch
                # 3. No stories in batch depend on this story
                has_file_overlap = bool(batch_files & story_files)
                has_dep_on_batch = bool(story_deps & set(batch))
                batch_depends_on_story = any(
                    story_id in self.story_map.get(b, {}).get("dependencies", []) for b in batch
                )

                if not has_file_overlap and not has_dep_on_batch and not batch_depends_on_story:
                    batch.append(story_id)
                    batch_files |= story_files
                    ungrouped.remove(story_id)

            batches.append(batch)

        return batches

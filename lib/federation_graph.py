"""lib/federation_graph.py — DAG builder and cycle detector for federated PRDs.

Builds a directed graph from prd.include relationships and detects cycles
using depth-first search (DFS).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _resolve_includes(prd_path: str, visited: set[str] | None = None) -> dict[str, list[str]]:
    """Recursively resolve prd.include paths and build adjacency graph.

    Args:
        prd_path: Path to prd.json file.
        visited: Internal set of already-visited paths (for cycle detection during traversal).

    Returns:
        Dict mapping prd_path → list of include paths (relative to prd_dir).
    """
    if visited is None:
        visited = set()

    abs_path = str(Path(prd_path).resolve())
    if abs_path in visited:
        return {}
    visited.add(abs_path)

    graph: dict[str, list[str]] = {}
    prd_dir = os.path.dirname(abs_path)

    try:
        with open(abs_path, encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    includes = data.get("prd.include", [])
    graph[abs_path] = includes

    # Recursively process each include
    for include_path in includes:
        sub_path = os.path.join(prd_dir, include_path)
        sub_graph = _resolve_includes(sub_path, visited)
        graph.update(sub_graph)

    return graph


def build_dag(root_prd_path: str) -> dict[str, list[str]]:
    """Build a directed acyclic graph (DAG) from prd.include relationships.

    Recursively resolves prd.include paths and returns a dict where keys are
    absolute paths to prd.json files and values are lists of absolute paths to
    included prd.json files.

    Args:
        root_prd_path: Path to the root prd.json file.

    Returns:
        Dict mapping prd_path → list of included prd_paths (all absolute paths).
    """
    visited: set[str] = set()
    abs_root = str(Path(root_prd_path).resolve())
    prd_dir = os.path.dirname(abs_root)

    # Load root prd.json
    try:
        with open(root_prd_path, encoding="utf-8") as f:
            root_data: dict[str, Any] = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    graph: dict[str, list[str]] = {}
    visited.add(abs_root)

    # Process root includes
    includes = root_data.get("prd.include", [])
    abs_includes: list[str] = []
    for include_path in includes:
        sub_path = os.path.join(prd_dir, include_path)
        abs_includes.append(str(Path(sub_path).resolve()))

    graph[abs_root] = abs_includes

    # Recursively process each include (DFS)
    def dfs(prd_path: str) -> None:
        abs_path = str(Path(prd_path).resolve())
        if abs_path in visited:
            return
        visited.add(abs_path)

        try:
            with open(prd_path, encoding="utf-8") as f:
                data: dict[str, Any] = json.load(f)
        except (OSError, json.JSONDecodeError):
            return

        prd_dir_local = os.path.dirname(abs_path)
        includes_local = data.get("prd.include", [])
        abs_includes_local: list[str] = []

        for include_path in includes_local:
            sub_path = os.path.join(prd_dir_local, include_path)
            abs_sub = str(Path(sub_path).resolve())
            abs_includes_local.append(abs_sub)
            dfs(sub_path)

        graph[abs_path] = abs_includes_local

    # Process all includes from root
    for include_abs_path in abs_includes:
        dfs(include_abs_path)

    return graph


def detect_cycles(graph: dict[str, list[str]]) -> tuple[bool, list[str]]:
    """Detect cycles in a directed graph using DFS.

    Args:
        graph: Dict mapping node → list of adjacent nodes.

    Returns:
        Tuple (has_cycle, cycle_nodes) where:
        - has_cycle: True if a cycle exists, False otherwise.
        - cycle_nodes: List of nodes that form a cycle, or empty list if no cycle.
    """
    visited: set[str] = set()
    rec_stack: set[str] = set()

    def dfs_detect(node: str, path: list[str]) -> tuple[bool, list[str]]:
        visited.add(node)
        rec_stack.add(node)
        path.append(node)

        neighbors = graph.get(node, [])
        for neighbor in neighbors:
            if neighbor not in visited:
                found, cycle = dfs_detect(neighbor, path[:])
                if found:
                    return (True, cycle)
            elif neighbor in rec_stack:
                # Cycle detected: from neighbor back to current path
                cycle_start_idx = path.index(neighbor) if neighbor in path else len(path)
                cycle = path[cycle_start_idx:] + [neighbor]
                return (True, cycle)

        rec_stack.remove(node)
        return (False, [])

    # Check each unvisited node as a potential starting point
    for node in graph:
        if node not in visited:
            found, cycle = dfs_detect(node, [])
            if found:
                return (True, cycle)

    return (False, [])


def render_graphviz(prd_path: str, dag: dict[str, list[str]], output_file: str) -> None:
    """Render a DAG as an SVG using Graphviz.

    Builds a directed graph with:
    - Story nodes (colored by status: pending=gray, passed=green, failed=red)
    - prd.include edges (labeled "includes")
    - Story _blockedBy edges (labeled "blocked_by")

    Args:
        prd_path: Path to root prd.json file.
        dag: Dict mapping prd_path → list of included prd_paths.
        output_file: Path to write SVG file (e.g., "spiral-deps.svg").

    Raises:
        ImportError: If graphviz Python package is not installed.
        OSError: If output file cannot be written.
    """
    try:
        import graphviz
    except ImportError as e:
        raise ImportError(
            "graphviz Python package required for render_graphviz(). Install with: pip install graphviz"
        ) from e

    # Load root prd.json to get stories and their metadata
    try:
        with open(prd_path, encoding="utf-8") as f:
            root_prd: dict[str, Any] = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"Failed to load prd.json at {prd_path}") from e

    # Create directed graph
    graph = graphviz.Digraph("prd_dependencies", format="svg")
    graph.attr(rankdir="TB")
    graph.attr("node", shape="box", style="filled")

    # Map story IDs to their status for coloring
    story_status: dict[str, str] = {}
    for story in root_prd.get("userStories", []):
        story_id = story.get("id", "")
        if story_id:
            if story.get("passes"):
                story_status[story_id] = "passed"
            elif story.get("_skipped") or story.get("_decomposed"):
                story_status[story_id] = "skipped"
            else:
                story_status[story_id] = "pending"

    # Add story nodes (from root prd.json only, with color coding)
    for story in root_prd.get("userStories", []):
        story_id = story.get("id", "")
        if story_id:
            status = story_status.get(story_id, "pending")
            title = story.get("title", story_id)[:30]  # Truncate long titles

            # Color by status
            if status == "passed":
                color = "lightgreen"
            elif status == "skipped":
                color = "lightblue"
            else:  # pending or unknown
                color = "lightgray"

            label = f"{story_id}\n{title}"
            graph.node(story_id, label=label, fillcolor=color)

    # Add edges for story _blockedBy relationships
    for story in root_prd.get("userStories", []):
        story_id = story.get("id", "")
        if story_id:
            blocked_by = story.get("_blockedBy", [])
            if isinstance(blocked_by, list):
                for blocker_id in blocked_by:
                    if blocker_id:
                        graph.edge(blocker_id, story_id, label="blocked_by", color="red")

    # Add prd.include edges (one node per prd.json file)
    for prd_src, prd_includes in dag.items():
        # Get a label for this prd (use filename)
        prd_src_name = Path(prd_src).stem
        if prd_src_name not in graph.body:  # Only add if not already present
            graph.node(prd_src_name, label=prd_src_name, fillcolor="lightyellow")

        for prd_dest in prd_includes:
            prd_dest_name = Path(prd_dest).stem
            if prd_dest_name not in graph.body:
                graph.node(prd_dest_name, label=prd_dest_name, fillcolor="lightyellow")
            graph.edge(prd_src_name, prd_dest_name, label="includes", color="blue")

    # Write SVG
    # graphviz outputs to output_file.svg by default, so strip .svg if present
    output_base = output_file.replace(".svg", "")
    graph.render(output_base, cleanup=True)

    # Ensure output file exists at the requested path
    svg_path = Path(output_base + ".svg")
    if not output_file.endswith(".svg"):
        output_file = output_file + ".svg"
    if output_base + ".svg" != output_file:
        import shutil

        shutil.move(output_base + ".svg", output_file)

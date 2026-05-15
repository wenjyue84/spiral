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

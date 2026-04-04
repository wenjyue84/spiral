"""lib/arch_validators.py — Pluggable architectural constraint validators for Phase V.

Each validator receives a CodeDiff and returns a list of Violation objects.
Built-in validators: MaxFileSize, NoCircularImports, LayerAccess.
"""

from __future__ import annotations

import ast
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class DiffFile:
    """A file included in the current code diff."""

    path: str
    size_bytes: int
    content: str = field(default="")
    is_new: bool = field(default=False)


@dataclass
class CodeDiff:
    """Snapshot of files changed in the current story implementation."""

    files: List[DiffFile]
    repo_root: str = field(default="")


@dataclass
class Violation:
    """A single architectural constraint violation."""

    validator: str  # validator class name
    file_path: str  # file that triggered the violation
    message: str  # human-readable description
    violation_type: str  # machine-readable type (e.g. "MaxFileSize")


class ArchValidator(ABC):
    """Base class for all architectural constraint validators."""

    @abstractmethod
    def validate(self, code_diff: CodeDiff) -> List[Violation]:
        """Validate the code diff and return a list of violations (empty = pass)."""
        ...


class MaxFileSize(ArchValidator):
    """Reject files that exceed MAX_FILE_SIZE bytes.

    Reads MAX_FILE_SIZE from environment (e.g. '1MB', '512KB', '1073741824').
    Default: no limit (disabled when env var not set).
    """

    def __init__(self, max_bytes: Optional[int] = None) -> None:
        if max_bytes is None:
            env = os.environ.get("MAX_FILE_SIZE", "")
            self.max_bytes: Optional[int] = _parse_size(env) if env else None
        else:
            self.max_bytes = max_bytes

    def validate(self, code_diff: CodeDiff) -> List[Violation]:
        if self.max_bytes is None:
            return []
        violations: List[Violation] = []
        for f in code_diff.files:
            if f.size_bytes > self.max_bytes:
                violations.append(
                    Violation(
                        validator="MaxFileSize",
                        file_path=f.path,
                        message=(f"{f.path} is {f.size_bytes:,} bytes, exceeds limit of {self.max_bytes:,} bytes"),
                        violation_type="MaxFileSize",
                    )
                )
        return violations


class NoCircularImports(ArchValidator):
    """Detect circular imports among Python files in the diff.

    Only analyses .py files. Builds a dependency graph from import statements
    and runs DFS cycle detection.
    """

    def validate(self, code_diff: CodeDiff) -> List[Violation]:
        py_files = [f for f in code_diff.files if f.path.endswith(".py") and f.content]
        if len(py_files) < 2:
            return []

        # Map dotted module name → set of imported module names
        imports: Dict[str, Set[str]] = {}
        for f in py_files:
            mod = _path_to_module(f.path)
            imports[mod] = _extract_imports(f.content)

        # DFS cycle detection (3-colour: WHITE=0, GRAY=1, BLACK=2)
        WHITE, GRAY, BLACK = 0, 1, 2
        colour: Dict[str, int] = defaultdict(int)
        cycles: List[List[str]] = []

        def dfs(node: str, path: List[str]) -> None:
            colour[node] = GRAY
            path.append(node)
            for dep in imports.get(node, set()):
                if dep not in imports:
                    continue  # external dependency — skip
                if colour[dep] == GRAY:
                    idx = path.index(dep)
                    cycles.append(path[idx:] + [dep])
                elif colour[dep] == WHITE:
                    dfs(dep, path)
            path.pop()
            colour[node] = BLACK

        for mod in list(imports.keys()):
            if colour[mod] == WHITE:
                dfs(mod, [])

        violations: List[Violation] = []
        for cycle in cycles:
            violations.append(
                Violation(
                    validator="NoCircularImports",
                    file_path=cycle[0].replace(".", "/") + ".py",
                    message=f"Circular import detected: {' -> '.join(cycle)}",
                    violation_type="NoCircularImports",
                )
            )
        return violations


class LayerAccess(ArchValidator):
    """Enforce architectural layer constraints.

    Reads SPIRAL_ARCH_LAYERS env var (JSON list of layer names, ordered from
    highest to lowest). Files in lower-ranked layers must not import from
    higher-ranked layers.

    Example: SPIRAL_ARCH_LAYERS='["api","service","model"]'
    means 'api' (rank 0) may import 'service' (rank 1), but 'model' (rank 2)
    must not import 'api' (rank 0).
    """

    def __init__(self, layers: Optional[List[str]] = None) -> None:
        if layers is None:
            import json

            env = os.environ.get("SPIRAL_ARCH_LAYERS", "")
            self.layers: List[str] = json.loads(env) if env else []
        else:
            self.layers = layers

    def validate(self, code_diff: CodeDiff) -> List[Violation]:
        if not self.layers:
            return []
        violations: List[Violation] = []
        layer_rank = {layer: i for i, layer in enumerate(self.layers)}

        for f in code_diff.files:
            if not f.path.endswith(".py") or not f.content:
                continue
            file_layer: Optional[str] = None
            for layer in self.layers:
                if f"/{layer}/" in f.path or f.path.startswith(f"{layer}/"):
                    file_layer = layer
                    break
            if file_layer is None:
                continue
            file_rank = layer_rank[file_layer]

            for imp in _extract_imports(f.content):
                for layer in self.layers:
                    if layer in imp and layer_rank[layer] < file_rank:
                        violations.append(
                            Violation(
                                validator="LayerAccess",
                                file_path=f.path,
                                message=(f"{f.path} (layer '{file_layer}') imports from higher layer '{layer}': {imp}"),
                                violation_type="LayerAccess",
                            )
                        )
                        break
        return violations


# ── Helpers ──────────────────────────────────────────────────────────────────


def _parse_size(s: str) -> int:
    """Parse a human-readable size string to bytes (e.g. '1MB', '512KB')."""
    s = s.strip().upper()
    for suffix, mult in (
        ("GB", 1 << 30),
        ("MB", 1 << 20),
        ("KB", 1 << 10),
        ("G", 1 << 30),
        ("M", 1 << 20),
        ("K", 1 << 10),
    ):
        if s.endswith(suffix):
            return int(s[: -len(suffix)]) * mult
    return int(s)


def _path_to_module(path: str) -> str:
    """Convert a file path to a dotted module name."""
    return path.replace("/", ".").replace("\\", ".").removesuffix(".py")


def _extract_imports(content: str) -> Set[str]:
    """Extract all imported module names from Python source."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return set()
    mods: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.add(node.module)
    return mods


def load_validators(validators_str: str) -> List[ArchValidator]:
    """Load and instantiate validators from a comma-separated string.

    E.g. 'MaxFileSize,NoCircularImports' -> [MaxFileSize(), NoCircularImports()]
    """
    if not validators_str.strip():
        return []
    registry: Dict[str, type] = {
        "MaxFileSize": MaxFileSize,
        "NoCircularImports": NoCircularImports,
        "LayerAccess": LayerAccess,
    }
    result: List[ArchValidator] = []
    for name in validators_str.split(","):
        name = name.strip()
        if not name:
            continue
        cls = registry.get(name)
        if cls is None:
            raise ValueError(f"Unknown validator: {name!r}. Available: {sorted(registry)}")
        result.append(cls())
    return result

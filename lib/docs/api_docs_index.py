"""Generate API documentation index.html from pdoc outputs."""

from __future__ import annotations

import ast
import os
from pathlib import Path

_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>SPIRAL API Docs</title>
<style>body{{font-family:sans-serif;max-width:900px;margin:2em auto}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:6px;border-bottom:1px solid #ddd}}
input{{width:100%;padding:8px;margin:1em 0;box-sizing:border-box}}</style></head>
<body><h1>SPIRAL API Documentation</h1>
<input id="s" placeholder="Search modules..." oninput="f()">
<table><thead><tr><th>Module</th><th>Description</th><th>Path</th><th>Deps</th></tr></thead>
<tbody id="t">{rows}</tbody></table>
<script>function f(){{var q=document.getElementById('s').value.toLowerCase();
document.querySelectorAll('#t tr').forEach(function(r){{
r.style.display=r.textContent.toLowerCase().includes(q)?'':'none'}})}}</script>
</body></html>"""


def _module_info(path: Path) -> dict[str, str] | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None
    doc = ast.get_docstring(tree) or ""
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[0])
    return {"doc": doc.split("\n")[0], "deps": ",".join(sorted(set(imports))[:5])}


def _collect_modules(dirs: list[Path]) -> list[dict[str, str]]:
    modules: list[dict[str, str]] = []
    for d in dirs:
        if not d.is_dir():
            continue
        for py in sorted(d.rglob("*.py")):
            if py.name.startswith("_"):
                continue
            info = _module_info(py)
            if info is None:
                continue
            name = py.stem
            rel = str(py.relative_to(d.parent))
            link = f"{name}.html"
            modules.append({"name": name, "doc": info["doc"], "path": rel, "deps": info["deps"], "link": link})
    return sorted(modules, key=lambda m: m["name"])


def generate_index(output_dir: str, scan_dirs: list[str] | None = None) -> Path:
    """Generate index.html for API docs. Returns path to the generated file."""
    base = Path(output_dir)
    base.mkdir(parents=True, exist_ok=True)
    if scan_dirs is None:
        root = Path(__file__).resolve().parent.parent.parent
        scan_dirs = [str(root / "lib")]
    modules = _collect_modules([Path(d) for d in scan_dirs])
    rows = ""
    for m in modules:
        rows += (
            f'<tr><td><a href="{m["link"]}">{m["name"]}</a></td>'
            f"<td>{m['doc']}</td><td>{m['path']}</td><td>{m['deps']}</td></tr>\n"
        )
    html = _HTML.format(rows=rows)
    out = base / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    p = generate_index(os.environ.get("SPIRAL_API_DOCS", ".spiral/api_docs"))
    print(f"Generated {p}")

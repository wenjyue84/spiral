"""lib/skills_cli.py — `spiral skills` subcommand: list and install plugins.

Commands:
    spiral skills list              — enumerate plugins/ and print metadata
    spiral skills install <url>     — fetch, validate, and extract a plugin tarball

Schema validation: plugin.toml must have [plugin] section with required fields.
"""

from __future__ import annotations

import io
import sys
import tarfile
import tempfile
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

REQUIRED_FIELDS: tuple[str, ...] = ("name", "version", "hooks")
OPTIONAL_METADATA_FIELDS: tuple[str, ...] = (
    "description",
    "inputs",
    "outputs",
    "tags",
)


def parse_plugin_toml(toml_path: Path) -> dict[str, Any]:
    """Parse a plugin.toml file and return the [plugin] section."""
    with open(toml_path, "rb") as f:
        data = tomllib.load(f)
    return dict(data.get("plugin", {}))


def validate_plugin_schema(plugin: dict[str, Any]) -> list[str]:
    """Return list of validation errors (empty = valid)."""
    errors: list[str] = []
    for field in REQUIRED_FIELDS:
        if not plugin.get(field):
            errors.append(f"Missing required field: '{field}'")
    hooks = plugin.get("hooks", [])
    if not isinstance(hooks, list):
        errors.append("'hooks' must be an array")
    return errors


def list_skills(plugins_dir: Path) -> int:
    """Print a table of installed plugins with their metadata."""
    if not plugins_dir.exists():
        print(f"[spiral skills] plugins directory not found: {plugins_dir}", file=sys.stderr)
        return 1

    entries: list[dict[str, Any]] = []
    for subdir in sorted(plugins_dir.iterdir()):
        if not subdir.is_dir():
            continue
        toml_path = subdir / "plugin.toml"
        if not toml_path.exists():
            continue
        try:
            plugin = parse_plugin_toml(toml_path)
        except Exception as exc:
            print(f"[spiral skills] WARNING: could not parse {toml_path}: {exc}", file=sys.stderr)
            plugin = {}
        entries.append(
            {
                "dir": subdir.name,
                "name": plugin.get("name", subdir.name),
                "version": plugin.get("version", "?"),
                "description": plugin.get("description", ""),
                "tags": plugin.get("tags", []),
                "inputs": plugin.get("inputs", []),
                "outputs": plugin.get("outputs", []),
                "hooks": plugin.get("hooks", []),
            }
        )

    if not entries:
        print("[spiral skills] No plugins installed.")
        return 0

    # Header
    print(f"{'NAME':<22} {'VERSION':<10} {'HOOKS':<26} DESCRIPTION")
    print("-" * 80)
    for e in entries:
        hooks_str = ", ".join(e["hooks"]) if e["hooks"] else ""
        desc = e["description"] or ""
        if len(desc) > 40:
            desc = desc[:37] + "..."
        print(f"{e['name']:<22} {e['version']:<10} {hooks_str:<26} {desc}")

    return 0


def install_skill(url: str, plugins_dir: Path) -> int:
    """Download, validate, and extract a plugin tarball."""
    print(f"[spiral skills] Fetching {url} ...")

    # Download tarball into a temp file
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310
            tarball_bytes = resp.read()
    except Exception as exc:
        print(f"[spiral skills] ERROR: download failed: {exc}", file=sys.stderr)
        return 1

    # Open as tarball
    try:
        tf = tarfile.open(fileobj=io.BytesIO(tarball_bytes))
    except tarfile.TarError as exc:
        print(f"[spiral skills] ERROR: not a valid tarball: {exc}", file=sys.stderr)
        return 1

    # Find plugin.toml inside the tarball
    toml_member: tarfile.TarInfo | None = None
    for member in tf.getmembers():
        if member.name.endswith("plugin.toml"):
            toml_member = member
            break

    if toml_member is None:
        print("[spiral skills] ERROR: plugin.toml not found in tarball — rejected.", file=sys.stderr)
        return 1

    # Extract and validate plugin.toml
    toml_file = tf.extractfile(toml_member)
    if toml_file is None:
        print("[spiral skills] ERROR: cannot read plugin.toml from tarball.", file=sys.stderr)
        return 1

    try:
        plugin_data = tomllib.load(toml_file)
        plugin = dict(plugin_data.get("plugin", {}))
    except Exception as exc:
        print(f"[spiral skills] ERROR: plugin.toml parse error: {exc} — rejected.", file=sys.stderr)
        return 1

    errors = validate_plugin_schema(plugin)
    if errors:
        for err in errors:
            print(f"[spiral skills] ERROR: schema invalid — {err}", file=sys.stderr)
        print("[spiral skills] Plugin rejected due to schema errors.", file=sys.stderr)
        return 1

    plugin_name: str = plugin.get("name", "")
    if not plugin_name:
        print("[spiral skills] ERROR: plugin 'name' is empty — rejected.", file=sys.stderr)
        return 1

    # Safe extraction: only extract members under the plugin's directory
    dest = plugins_dir / plugin_name
    dest.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        tf.extractall(tmpdir, filter="data")  # noqa: S202
        tmp_path = Path(tmpdir)
        # Find the dir containing plugin.toml and copy its contents
        toml_parent = (tmp_path / toml_member.name).parent
        for item in toml_parent.iterdir():
            target = dest / item.name
            if item.is_file():
                target.write_bytes(item.read_bytes())

    print(f"[spiral skills] Installed '{plugin_name}' v{plugin.get('version', '?')} → {dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    plugins_dir = Path("plugins")

    if not args or args[0] not in ("list", "install"):
        print("Usage: spiral skills list | spiral skills install <url>", file=sys.stderr)
        return 1

    subcommand = args[0]
    if subcommand == "list":
        return list_skills(plugins_dir)

    # install
    if len(args) < 2 or not args[1]:
        print("[spiral skills] ERROR: Usage: spiral skills install <url>", file=sys.stderr)
        return 1
    return install_skill(args[1], plugins_dir)


if __name__ == "__main__":
    sys.exit(main())

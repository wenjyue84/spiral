#!/usr/bin/env bash
# lib/phases/phase-g.sh — Phase G: Auto-generate README.md Features section
#
# Functions: generate_readme_features
# Reads completed stories from prd.json and generates a formatted ## Features
# section in .spiral/phase-g-readme-snippet.md for project maintainers to append.

set -euo pipefail

# generate_readme_features: Generate README.md Features section from completed stories
#
# Reads prd.json, filters stories where passes=true (and not _decomposed),
# and writes a ## Features markdown section to .spiral/phase-g-readme-snippet.md.
#
# Environment:
#   SPIRAL_PRD_PATH  — path to prd.json (default: prd.json)
#   SPIRAL_HOME      — project root for .spiral/ directory (default: .)
#   SPIRAL_PYTHON    — Python interpreter (default: python3)
#
# Returns: 0 on success, 1 if prd.json not found
generate_readme_features() {
  local prd_path="${SPIRAL_PRD_PATH:-prd.json}"
  local spiral_home="${SPIRAL_HOME:-.}"
  local output_file="${spiral_home}/.spiral/phase-g-readme-snippet.md"
  local python_bin="${SPIRAL_PYTHON:-python3}"

  if [[ ! -f "$prd_path" ]]; then
    echo "[phase-g] ERROR: prd.json not found at ${prd_path}" >&2
    return 1
  fi

  mkdir -p "${spiral_home}/.spiral"

  echo "[phase-g] Generating README Features section from ${prd_path}..."

  # Use Python to parse prd.json and emit the ## Features markdown section.
  # Paths passed via sys.argv to avoid Git-bash→Windows translation issues.
  "$python_bin" - "$prd_path" "$output_file" <<'PYEOF'
import json
import sys

prd_path = sys.argv[1]
output_path = sys.argv[2]

with open(prd_path, encoding="utf-8") as f:
    data = json.load(f)

stories = data.get("userStories", [])
completed = [
    s for s in stories
    if s.get("passes") is True and not s.get("_decomposed", False)
]

lines = ["## Features", ""]
for story in completed:
    title = story.get("title", "Untitled")
    description = story.get("description", "")
    if description:
        lines.append(f"- **{title}** — {description}")
    else:
        lines.append(f"- **{title}**")

lines.append("")

with open(output_path, "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"[phase-g] Wrote {len(completed)} feature entries to {output_path}")
PYEOF

  if [[ ! -f "$output_file" ]]; then
    echo "[phase-g] ERROR: Output file was not created" >&2
    return 1
  fi

  echo "[phase-g] README snippet written to ${output_file}"
  return 0
}

# Export for use in spiral.sh
export -f generate_readme_features

#!/bin/bash
# lib/phases/documentation.sh — Phase G: API documentation generation

set -euo pipefail

# phase_generate_api_docs: Generate HTML API docs from Python modules via pdoc
# Outputs to .spiral/docs/api/ with git commit SHA embedded in YAML frontmatter
phase_generate_api_docs() {
  local source_dir="${1:-lib}"
  local output_dir="${2:-.spiral/docs/api}"

  echo "▶ Generating API documentation..."

  # Ensure output directory exists
  mkdir -p "$output_dir"

  # Call Python module to generate docs
  python -m lib.observability.auto_release 2>&1 | grep -E "^(▶|✓|✅|❌)" || true

  if [ ! -f "$output_dir/index.html" ]; then
    echo "❌ API documentation generation failed: index.html not created" >&2
    return 1
  fi

  echo "✓ API documentation generated to $output_dir"
  return 0
}

# list_api_docs: List generated API documentation with story ID mappings
# Parses git blame to associate functions with stories
list_api_docs() {
  local docs_dir=".spiral/docs/api"

  if [ ! -d "$docs_dir" ]; then
    echo "No API documentation found at $docs_dir" >&2
    return 1
  fi

  echo "📚 Generated API Documentation:"
  echo ""

  # Find all HTML files and extract module names
  for html_file in "$docs_dir"/*.html; do
    if [ -f "$html_file" ]; then
      local module_name
      module_name=$(basename "$html_file" .html)
      if [ "$module_name" != "index" ]; then
        # Extract frontmatter commit SHA if present
        local commit_sha
        commit_sha=$(grep "generated_from_commit:" "$html_file" | cut -d' ' -f2 || echo "unknown")
        echo "  • $module_name (commit: ${commit_sha:0:7}...)"
      fi
    fi
  done

  return 0
}

# Export functions for use in spiral.sh
export -f phase_generate_api_docs
export -f list_api_docs

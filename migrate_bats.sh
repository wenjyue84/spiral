#!/usr/bin/env bash
# migrate_bats.sh — Add bats_require_minimum_version + common-setup to all unmigrated bats files
# Also replaces inline jq resolution with _resolve_jq from common-setup
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"

# Find all SPIRAL project bats files (exclude submodule files)
mapfile -t FILES < <(find "$REPO_ROOT/tests" -name '*.bats' \
  -not -path '*/bats-core/*' \
  -not -path '*/bats-assert/*' \
  -not -path '*/bats-support/*' | sort)

migrated=0
skipped=0

for f in "${FILES[@]}"; do
  # Skip if already has common-setup
  if grep -q 'common-setup' "$f"; then
    echo "SKIP (already migrated): $f"
    ((skipped++))
    continue
  fi

  echo "MIGRATING: $f"

  # Determine load path based on depth
  rel="${f#$REPO_ROOT/tests/}"
  depth=$(echo "$rel" | tr -cd '/' | wc -c)
  if [ "$depth" -eq 0 ]; then
    # tests/*.bats — load test_helper/common-setup
    LOAD_LINE="  load test_helper/common-setup"
  else
    # tests/lib/*.bats — need to go up one more level
    LOAD_LINE="  load ../test_helper/common-setup"
  fi

  # Step 1: Add bats_require_minimum_version after the comment header block
  # Find the line number of setup() or the first @test or first non-comment/non-blank line
  if ! grep -q 'bats_require_minimum_version' "$f"; then
    # Find the last consecutive comment/blank line at the top of the file
    insert_after=0
    while IFS= read -r line; do
      ((insert_after++))
      # Stop at first non-comment, non-blank, non-shebang line
      if [[ "$line" != "#"* && "$line" != "" && "$line" != "#!/"* ]]; then
        ((insert_after--))
        break
      fi
    done < "$f"

    # Insert bats_require_minimum_version after the comment block
    sed -i "${insert_after}a\\
\\
bats_require_minimum_version 1.7.0" "$f"
  fi

  # Step 2: Add 'load test_helper/common-setup' + '_resolve_jq' to setup()
  if grep -q '^setup()' "$f"; then
    # Remove inline jq resolution block (the common 5-7 line pattern)
    # Pattern: if command -v jq ... elif ... elif ... fi (with export JQ=...)
    sed -i '/^  # Provide a minimal JQ path$/d' "$f"
    sed -i '/^  # Provide JQ$/d' "$f"
    sed -i '/^  # Resolve jq binary.*$/d' "$f"

    # Remove the inline jq resolution block
    python3 -c "
import re, sys

with open('$f', 'r', encoding='utf-8') as fh:
    content = fh.read()

# Remove inline jq resolution blocks (multi-line if/elif/fi pattern)
# Pattern: optional comment, then if command -v jq ... export JQ=... elif ... fi
jq_block = re.compile(
    r'(\n  # (?:Provide|Resolve|Prefer).*jq.*\n)?'
    r'  if command -v jq &>/dev/null; then\n'
    r'    export JQ=\"jq\"\n'
    r'  elif \[\[ -f \"ralph/jq\.exe\" \]\]; then\n'
    r'    export JQ=\"ralph/jq\.exe\"\n'
    r'(?:  elif \[\[ -f \"ralph/jq\" \]\]; then\n'
    r'    export JQ=\"ralph/jq\"\n)?'
    r'  fi\n',
    re.MULTILINE
)
content = jq_block.sub('\n', content)

with open('$f', 'w', encoding='utf-8') as fh:
    fh.write(content)
" 2>/dev/null || true

    # Add load line right after 'setup() {'
    sed -i "/^setup() {$/a\\
$LOAD_LINE\\
  _resolve_jq" "$f"
  fi

  # Step 3: Replace raw assertions
  # [ "$status" -eq 0 ] → assert_success
  sed -i 's/^  \[ "\$status" -eq 0 \]$/  assert_success/' "$f"

  # [ "$status" -eq N ] for N>0 → assert_failure N
  sed -i 's/^  \[ "\$status" -eq \([1-9][0-9]*\) \]$/  assert_failure \1/' "$f"

  # [[ "$output" == *"..."* ]] → assert_output --partial "..."
  sed -i 's/^  \[\[ "\$output" == \*"\(.*\)"\* \]\]$/  assert_output --partial "\1"/' "$f"

  # [[ "$output" != *"..."* ]] → refute_output --partial "..."
  sed -i 's/^  \[\[ "\$output" != \*"\(.*\)"\* \]\]$/  refute_output --partial "\1"/' "$f"

  # [ "$output" = "..." ] → assert_output "..."
  sed -i 's/^  \[ "\$output" = "\(.*\)" \]$/  assert_output "\1"/' "$f"

  ((migrated++))
done

echo ""
echo "Done: migrated=$migrated, skipped=$skipped"

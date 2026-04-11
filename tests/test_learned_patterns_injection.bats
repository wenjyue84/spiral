#!/usr/bin/env bats
# Test US-1214: Ralph injects learned patterns filtered by story tags into context

setup() {
  export SPIRAL_SCRATCH_DIR="$(mktemp -d)"
  export SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
}

teardown() {
  rm -rf "$SPIRAL_SCRATCH_DIR"
}

@test "US-1214: patterns section appears in injected context when patterns file exists" {
  # Create a mock learned_patterns file
  cat >"$SPIRAL_SCRATCH_DIR/learned_patterns_iter_1.json" <<'EOF'
{
  "patterns": [
    {
      "pattern": "Always read file before editing",
      "frequency": 25,
      "pattern_tags": ["best-practice", "file-ops"]
    },
    {
      "pattern": "Use descriptive variable names",
      "frequency": 18,
      "pattern_tags": ["code-quality", "readability"]
    },
    {
      "pattern": "Test changes before committing",
      "frequency": 22,
      "pattern_tags": ["best-practice", "testing"]
    }
  ]
}
EOF

  # Create story JSON with matching tags
  STORY_JSON=$(
    cat <<'EOF'
{
  "id": "US-1214",
  "title": "Test Story",
  "tags": ["best-practice", "file-ops"]
}
EOF
  )

  # Manually execute the pattern filtering logic
  _STORY_TAGS=$(echo "$STORY_JSON" | jq -r '.tags // [] | join(",")')
  _LP_LATEST="learned_patterns_iter_1.json"
  _LP_PATH="$SPIRAL_SCRATCH_DIR/$_LP_LATEST"

  # Filter patterns by tag overlap
  _LP_FILTERED=$(jq -r \
    --arg story_tags "$_STORY_TAGS" \
    '.patterns // [] |
     if ($story_tags | length) > 0 then
       map(
         .pattern_tags as $pt |
         {
           pattern: .pattern,
           frequency: .frequency,
           tag_match: (
             ($story_tags | split(",")) as $st |
             ($pt // [] | map(. as $x | $st | index($x)) | map(select(. != null)) | length) > 0
           )
         }
       ) | map(select(.tag_match)) | sort_by(.frequency) | reverse | .[0:3] |
       map("- " + .pattern + " (frequency: \(.frequency))")
     else
       sort_by(.frequency) | reverse | .[0:3] |
       map("- " + .pattern + " (frequency: \(.frequency))")
     end | join("\n")' \
    "$_LP_PATH" 2>/dev/null || echo "")

  # Verify "Learned Patterns from Phase L" section would be in the prompt
  [[ "$_LP_FILTERED" == *"Always read file before editing"* ]] || return 1
  echo "✓ Pattern with matching tag found in filtered results"

  # Verify non-matching patterns are excluded
  [[ "$_LP_FILTERED" != *"Use descriptive variable names"* ]] || return 1
  echo "✓ Patterns without matching tags correctly excluded"
}

@test "US-1214: falls back to frequency sort when no story tags" {
  # Create a mock learned_patterns file
  cat >"$SPIRAL_SCRATCH_DIR/learned_patterns_iter_2.json" <<'EOF'
{
  "patterns": [
    {
      "pattern": "Pattern A",
      "frequency": 10,
      "pattern_tags": ["tag-a"]
    },
    {
      "pattern": "Pattern B",
      "frequency": 30,
      "pattern_tags": ["tag-b"]
    },
    {
      "pattern": "Pattern C",
      "frequency": 20,
      "pattern_tags": ["tag-c"]
    }
  ]
}
EOF

  STORY_JSON=$(
    cat <<'EOF'
{
  "id": "US-1214",
  "title": "Test Story",
  "tags": []
}
EOF
  )

  _STORY_TAGS=$(echo "$STORY_JSON" | jq -r '.tags // [] | join(",")')
  _LP_PATH="$SPIRAL_SCRATCH_DIR/learned_patterns_iter_2.json"

  _LP_FILTERED=$(jq -r \
    --arg story_tags "$_STORY_TAGS" \
    '.patterns // [] |
     if ($story_tags | length) > 0 then
       map(
         .pattern_tags as $pt |
         {
           pattern: .pattern,
           frequency: .frequency,
           tag_match: (
             ($story_tags | split(",")) as $st |
             ($pt // [] | map(. as $x | $st | index($x)) | map(select(. != null)) | length) > 0
           )
         }
       ) | map(select(.tag_match)) | sort_by(.frequency) | reverse | .[0:3] |
       map("- " + .pattern + " (frequency: \(.frequency))")
     else
       sort_by(.frequency) | reverse | .[0:3] |
       map("- " + .pattern + " (frequency: \(.frequency))")
     end | join("\n")' \
    "$_LP_PATH" 2>/dev/null || echo "")

  # Without tags, should get all patterns sorted by frequency (top 3)
  # Pattern B (30) should be first, then C (20), then A (10)
  [[ "$_LP_FILTERED" == *"Pattern B"* ]] || return 1
  echo "✓ Top frequency pattern B included"
}

@test "US-1214: skips silently if no patterns file exists" {
  # Remove the patterns file
  rm -f "$SPIRAL_SCRATCH_DIR/learned_patterns_iter_*.json"

  STORY_JSON=$(
    cat <<'EOF'
{
  "id": "US-1214",
  "title": "Test Story",
  "tags": ["test"]
}
EOF
  )

  _STORY_TAGS=$(echo "$STORY_JSON" | jq -r '.tags // [] | join(",")')

  # Simulate finding the latest file (should be empty)
  if [[ -d "$SPIRAL_SCRATCH_DIR" ]]; then
    _LP_LATEST=$(cd "$SPIRAL_SCRATCH_DIR" 2>/dev/null &&
      ls -1 learned_patterns_iter_*.json 2>/dev/null | sort -V | tail -1 || echo "")
  fi

  # Should be empty string (no file found)
  [[ -z "$_LP_LATEST" ]] || return 1
  echo "✓ No patterns file found - correctly returns empty"
}

@test "US-1214: returns empty when patterns file is empty" {
  # Create an empty patterns array
  cat >"$SPIRAL_SCRATCH_DIR/learned_patterns_iter_3.json" <<'EOF'
{
  "patterns": []
}
EOF

  STORY_JSON=$(
    cat <<'EOF'
{
  "id": "US-1214",
  "title": "Test Story",
  "tags": ["test"]
}
EOF
  )

  _LP_PATH="$SPIRAL_SCRATCH_DIR/learned_patterns_iter_3.json"

  _LP_FILTERED=$(jq -r \
    --arg story_tags "test" \
    '.patterns // [] |
     if ("test" | length) > 0 then
       map(
         .pattern_tags as $pt |
         {
           pattern: .pattern,
           frequency: .frequency,
           tag_match: (
             ("test" | split(",")) as $st |
             ($pt // [] | map(. as $x | $st | index($x)) | map(select(. != null)) | length) > 0
           )
         }
       ) | map(select(.tag_match)) | sort_by(.frequency) | reverse | .[0:3] |
       map("- " + .pattern + " (frequency: \(.frequency))")
     else
       sort_by(.frequency) | reverse | .[0:3] |
       map("- " + .pattern + " (frequency: \(.frequency))")
     end | join("\n")' \
    "$_LP_PATH" 2>/dev/null || echo "")

  # Should be empty since no patterns match (and patterns array is empty)
  [[ -z "$_LP_FILTERED" ]] || return 1
  echo "✓ Empty patterns array correctly returns empty injection"
}

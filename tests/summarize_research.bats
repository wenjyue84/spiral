#!/usr/bin/env bats
# tests/summarize_research.bats — Tests for US-254: Hierarchical summarization
#
# Run with: bats tests/summarize_research.bats
#
# Tests verify:
#   - Research output under threshold is NOT summarized
#   - Research output over threshold IS summarized
#   - Acceptance criteria are preserved in summary
#   - Technical notes are preserved in summary
#   - Source URLs are preserved in summary
#   - --check-only mode returns correct exit codes
#   - Empty stories array handled gracefully

bats_require_minimum_version 1.7.0

# ── Helpers ──────────────────────────────────────────────────────────────────

SPIRAL_HOME="$(cd "$(dirname "$BATS_TEST_FILENAME")/.." && pwd)"
PYTHON="${SPIRAL_PYTHON:-python}"

# Detect python
_detect_python() {
  if command -v "$PYTHON" &>/dev/null; then
    return 0
  elif command -v python3 &>/dev/null; then
    PYTHON="python3"
    return 0
  elif command -v python &>/dev/null; then
    PYTHON="python"
    return 0
  else
    return 1
  fi
}

# Convert path for Python on Windows (Git Bash /tmp → C:/Users/.../Temp)
_pypath() {
  if command -v cygpath &>/dev/null; then
    cygpath -m "$1"
  else
    echo "$1"
  fi
}

setup() {
  load test_helper/common-setup
  _resolve_jq
  _detect_python || skip "python not available"
  TEST_DIR="$(mktemp -d)"
  # Python-compatible path (Windows: C:/Users/.../Temp/...)
  PY_DIR="$(_pypath "$TEST_DIR")"

  # Generate fixtures via Python (avoids bash/heredoc path issues)
  "$PYTHON" -c "
import json, os, sys
d = sys.argv[1]
# Small fixture
small = {'stories': [{'id': 'US-900', 'title': 'Small story',
  'description': 'A short description.', 'acceptanceCriteria': ['AC1: works'],
  'technicalNotes': ['Note1'], 'source': 'https://example.com/small',
  'priority': 'medium', '_source': 'research'}]}
with open(os.path.join(d, 'small_research.json'), 'w') as f:
    json.dump(small, f, indent=2)

# Large fixture
desc = ' '.join(['This is sentence number %d providing detailed research context about the implementation approach and various technical considerations that need to be carefully evaluated.' % i for i in range(500)])
large = {'stories': [
  {'id': 'US-901', 'title': 'Large story with verbose research',
   'description': desc, 'acceptanceCriteria': ['AC1: must handle edge cases', 'AC2: must be backwards compatible'],
   'technicalNotes': ['TN1: Use existing patterns from lib/', 'TN2: Maintain 95% info retention'],
   'source': 'https://example.com/research', 'priority': 'high', '_source': 'research', 'dependencies': ['US-100']},
  {'id': 'US-902', 'title': 'Second verbose story', 'description': desc,
   'acceptanceCriteria': ['AC1: integrate with Phase S'], 'technicalNotes': ['TN1: Follow semconv spec'],
   'source': 'https://example.com/research2', 'priority': 'medium', '_source': 'research'}]}
with open(os.path.join(d, 'large_research.json'), 'w') as f:
    json.dump(large, f, indent=2)

# Empty fixture
with open(os.path.join(d, 'empty.json'), 'w') as f:
    json.dump({'stories': []}, f)
" "$PY_DIR"
}

teardown() {
  [[ -d "$TEST_DIR" ]] && rm -rf "$TEST_DIR"
}

# ── Tests ────────────────────────────────────────────────────────────────────

@test "US-254: small research output is not summarized" {
  run "$PYTHON" "$SPIRAL_HOME/lib/summarize_research.py" \
    --input "$PY_DIR/small_research.json" \
    --output "$PY_DIR/output.json" \
    --threshold 4000

  assert_success
  # Check story count preserved
  run "$PYTHON" -c "
import json
with open('$PY_DIR/output.json') as f:
    d = json.load(f)
assert len(d['stories']) == 1
print('OK')
"
  assert_success
  assert_output --partial "OK"
}

@test "US-254: large research output is summarized" {
  run "$PYTHON" "$SPIRAL_HOME/lib/summarize_research.py" \
    --input "$PY_DIR/large_research.json" \
    --output "$PY_DIR/output.json" \
    --threshold 4000

  assert_success
  # Output should be smaller than input
  local input_size output_size
  input_size=$(wc -c <"$TEST_DIR/large_research.json")
  output_size=$(wc -c <"$TEST_DIR/output.json")
  [ "$output_size" -lt "$input_size" ]
}

@test "US-254: acceptance criteria preserved in summary" {
  "$PYTHON" "$SPIRAL_HOME/lib/summarize_research.py" \
    --input "$PY_DIR/large_research.json" \
    --output "$PY_DIR/output.json" \
    --threshold 4000 2>/dev/null

  run "$PYTHON" -c "
import json
with open('$PY_DIR/output.json') as f:
    d = json.load(f)
for s in d['stories']:
    assert 'acceptanceCriteria' in s, f'Missing AC in {s[\"id\"]}'
    assert len(s['acceptanceCriteria']) > 0, f'Empty AC in {s[\"id\"]}'
print('OK')
"
  assert_success
  assert_output --partial "OK"
}

@test "US-254: technical notes preserved in summary" {
  "$PYTHON" "$SPIRAL_HOME/lib/summarize_research.py" \
    --input "$PY_DIR/large_research.json" \
    --output "$PY_DIR/output.json" \
    --threshold 4000 2>/dev/null

  run "$PYTHON" -c "
import json
with open('$PY_DIR/output.json') as f:
    d = json.load(f)
for s in d['stories']:
    assert 'technicalNotes' in s, f'Missing TN in {s[\"id\"]}'
    assert len(s['technicalNotes']) > 0, f'Empty TN in {s[\"id\"]}'
print('OK')
"
  assert_success
  assert_output --partial "OK"
}

@test "US-254: source URLs preserved in summary" {
  "$PYTHON" "$SPIRAL_HOME/lib/summarize_research.py" \
    --input "$PY_DIR/large_research.json" \
    --output "$PY_DIR/output.json" \
    --threshold 4000 2>/dev/null

  run "$PYTHON" -c "
import json
with open('$PY_DIR/output.json') as f:
    d = json.load(f)
for s in d['stories']:
    assert 'source' in s, f'Missing source in {s[\"id\"]}'
    assert s['source'].startswith('https://'), f'Bad source in {s[\"id\"]}'
print('OK')
"
  assert_success
  assert_output --partial "OK"
}

@test "US-254: --check-only returns 0 when under threshold" {
  run "$PYTHON" "$SPIRAL_HOME/lib/summarize_research.py" \
    --input "$PY_DIR/small_research.json" --check-only --threshold 4000
  assert_success
}

@test "US-254: --check-only returns 2 when over threshold" {
  run "$PYTHON" "$SPIRAL_HOME/lib/summarize_research.py" \
    --input "$PY_DIR/large_research.json" --check-only --threshold 4000
  assert_failure 2
}

@test "US-254: empty stories array handled gracefully" {
  run "$PYTHON" "$SPIRAL_HOME/lib/summarize_research.py" \
    --input "$PY_DIR/empty.json" \
    --output "$PY_DIR/output.json" \
    --threshold 4000

  assert_success
  run "$PYTHON" -c "
import json
with open('$PY_DIR/output.json') as f:
    d = json.load(f)
assert d['stories'] == []
print('OK')
"
  assert_success
  assert_output --partial "OK"
}

@test "US-254: stderr reports summarization stats as JSON" {
  "$PYTHON" "$SPIRAL_HOME/lib/summarize_research.py" \
    --input "$PY_DIR/large_research.json" \
    --output "$PY_DIR/output.json" \
    --threshold 4000 2>"$TEST_DIR/stderr.txt"

  run "$PYTHON" -c "
import json
with open('$PY_DIR/stderr.txt') as f:
    data = json.loads(f.read().strip())
assert data['event'] == 'research_summarized'
assert data['original_tokens'] > data['summary_tokens']
assert data['reduction_pct'] > 0
print('OK')
"
  assert_success
  assert_output --partial "OK"
}

@test "US-254: story IDs preserved after summarization" {
  "$PYTHON" "$SPIRAL_HOME/lib/summarize_research.py" \
    --input "$PY_DIR/large_research.json" \
    --output "$PY_DIR/output.json" \
    --threshold 4000 2>/dev/null

  run "$PYTHON" -c "
import json
with open('$PY_DIR/large_research.json') as f:
    orig = json.load(f)
with open('$PY_DIR/output.json') as f:
    summ = json.load(f)
orig_ids = {s['id'] for s in orig['stories']}
summ_ids = {s['id'] for s in summ['stories']}
assert orig_ids == summ_ids, f'{orig_ids} != {summ_ids}'
print('OK')
"
  assert_success
  assert_output --partial "OK"
}

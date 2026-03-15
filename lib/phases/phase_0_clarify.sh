#!/usr/bin/env bash
# lib/phases/phase_0_clarify.sh — Phase 0: CLARIFY
#
# One-time interactive session that runs BEFORE the main loop begins.
# Purpose: align the user and Spiral on session goals and constraints before
# any autonomous research or implementation starts.
#
# Sub-phases:
#   0-A  Constitution  — establish/review the project's non-negotiable rules
#   0-B  Focus         — set the theme for this spiral session
#   0-C  Clarify       — 3 targeted questions to refine scope & prevent drift
#   0-D  Stories       — enter initial story seeds (AI-suggested examples)
#   0-E  Options       — time limit and other session knobs
#
# Called once from spiral.sh after config is loaded.
# Skipped if --gate proceed or --gate skip is passed (non-interactive mode).
# Skipped on resume when .spiral/_phase_0_done marker file exists.
#
# Outputs:
#   .spiral/_clarify_output.json   — audit log of session setup
#   .spiral/_phase_0_done          — marker so resume skips Phase 0
#
# Variables set (exported to parent shell):
#   SPIRAL_FOCUS                — focus area string + clarifying context
#   TIME_LIMIT_MINS             — 0 = unlimited; >0 = stop after N minutes
#   SPIRAL_SPECKIT_CONSTITUTION — path to constitution file

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

_open_editor() {
  local file="$1"
  local editor="${EDITOR:-}"
  if [[ -n "$editor" ]] && command -v "$editor" > /dev/null 2>&1; then
    "$editor" "$file"
  elif command -v nano > /dev/null 2>&1; then
    nano "$file"
  elif command -v vi > /dev/null 2>&1; then
    vi "$file"
  elif command -v notepad > /dev/null 2>&1; then
    notepad "$file" 2>/dev/null || true
  else
    echo "  │  No editor found. Edit manually at: $file"
    printf "  │  Press Enter when done: "
    read -r _ 2>/dev/null || true
  fi
}

# ─────────────────────────────────────────────────────────────────────────────
# 0-A  CONSTITUTION
# Establish or review the project's non-negotiable rules.
# Without a constitution, Spiral drifts — each iteration picks whatever
# looks interesting rather than what actually advances project goals.
# ─────────────────────────────────────────────────────────────────────────────

_generate_constitution() {
  # Generate a suggested constitution from prd.json content + current focus.
  # Writes to $1. Returns 0 on accept/edit, 1 on skip.
  local const_path="$1"
  local prd_file="${PRD_FILE:-prd.json}"

  local _suggested
  _suggested=$("$SPIRAL_PYTHON" - "$prd_file" "${SPIRAL_FOCUS:-}" 2>/dev/null <<'_PY'
import json, sys

prd_file, focus = sys.argv[1], sys.argv[2]

try:
    with open(prd_file, encoding="utf-8") as f:
        prd = json.load(f)
except Exception:
    prd = {}

product  = prd.get("productName", "This Project")
overview = prd.get("overview", "").strip()
goals    = prd.get("goals", [])
epics    = prd.get("epics", [])

goal_lines = "\n".join(f"- {g}" for g in goals) if goals else "- (add goals to prd.json)"
epic_lines = "\n".join(
    f"- {e.get('title','')}: {e.get('description','')[:80]}"
    for e in epics if e.get("title")
)
overview_text = overview or "(update the overview field in prd.json)"
focus_section = f"\n## Session Focus\n{focus}\n" if focus else ""
epic_section  = f"\n## Epics In Scope\n{epic_lines}\n" if epic_lines else ""

print(f"""# {product} — Spiral Constitution

## What This Project Is
{overview_text}
{focus_section}
## Core Goals
{goal_lines}
{epic_section}
## Invariants (Never Break These)
1. **Phase ordering** — R → T → M → G → I → V → C must not be bypassed
2. **Git ratchet** — all existing tests must pass before a story closes
3. **Story atomicity** — each story is one independent, self-contained unit
4. **Config API** — spiral.config.sh env vars are user-facing; renames need migration
5. **No scope drift** — every story must directly advance one of the core goals above

## What Stories Must NOT Do
- NEVER break the phase ordering or bypass existing quality gates
- NOT: add features outside the stated goals without explicit approval
- AVOID: hard dependencies on tools not auto-installed by setup.sh
- FORBIDDEN: commit broken or partially-implemented intermediate states

## Acceptable Story Scope
- Directly advancing one of the core goals above
- Improving existing phases for speed, reliability, or observability
- Adding optional capabilities behind env var flags (default off)
- Fixing bugs in existing behaviour
- Expanding test coverage
- Improving documentation and onboarding""".strip())
_PY
)

  if [[ -z "$_suggested" ]]; then
    _suggested="# Project Constitution

## What This Project Is
(Describe your project here)

## Invariants (Never Break These)
1. All existing tests must pass
2. No story may bypass quality gates
3. Config API must stay backward compatible

## What Stories Must NOT Do
- NEVER break working functionality
- AVOID hard dependencies not in setup.sh
- FORBIDDEN: commit broken states

## Acceptable Story Scope
- Bug fixes and test coverage
- Performance improvements
- New features behind feature flags"
  fi

  echo ""
  echo "$_suggested" | sed 's/^/  │  /'
  echo "  │"
  printf "  │  (a)ccept  (e)dit  (s)kip  [a]: "
  local _choice
  read -r _choice 2>/dev/null || _choice="a"

  case "${_choice:-a}" in
    s|skip)
      echo "  │  [0-A] Skipped — no constitution created."
      return 1
      ;;
    e|edit)
      mkdir -p "$(dirname "$const_path")"
      printf '%s\n' "$_suggested" > "$const_path"
      _open_editor "$const_path"
      echo "  │  [0-A] Constitution saved (edited): $const_path"
      return 0
      ;;
    *)
      mkdir -p "$(dirname "$const_path")"
      printf '%s\n' "$_suggested" > "$const_path"
      echo "  │  [0-A] Constitution saved: $const_path"
      return 0
      ;;
  esac
}

_phase_0a_constitution() {
  local const_path="${SPIRAL_SPECKIT_CONSTITUTION:-.specify/memory/constitution.md}"

  echo "  ┌─ 0-A: Constitution ─────────────────────────────────────────────────"
  echo "  │  The constitution steers every story Spiral generates and implements."
  echo "  │  Without it, the loop drifts — picking interesting over important."
  echo "  │"

  if [[ -f "$const_path" ]]; then
    echo "  │  Found: $const_path"
    echo "  │"
    head -10 "$const_path" | sed 's/^/  │  /'
    echo "  │  ..."
    echo "  │"
    printf "  │  (r)euse  (e)dit  (R)eplace with generated  [r]: "
    local _choice
    read -r _choice 2>/dev/null || _choice="r"
    case "${_choice:-r}" in
      e|edit)
        _open_editor "$const_path"
        echo "  │  [0-A] Constitution updated."
        _PHASE0_CONSTITUTION_CREATED=1
        ;;
      R|replace)
        echo "  │  Generating new constitution..."
        if _generate_constitution "$const_path"; then
          _PHASE0_CONSTITUTION_CREATED=1
        fi
        ;;
      *)
        echo "  │  [0-A] Reusing existing constitution."
        ;;
    esac
  else
    echo "  │  No constitution found — generating a suggestion from prd.json..."
    if _generate_constitution "$const_path"; then
      _PHASE0_CONSTITUTION_CREATED=1
    fi
  fi

  echo "  └─────────────────────────────────────────────────────────────────────"
  echo ""

  # Export so child processes (Phase R, ralph) pick it up
  SPIRAL_SPECKIT_CONSTITUTION="$const_path"
  export SPIRAL_SPECKIT_CONSTITUTION
  _PHASE0_CONSTITUTION_PATH="$const_path"
}

# ─────────────────────────────────────────────────────────────────────────────
# 0-B  SESSION FOCUS
# Set the theme that guides which stories get researched and prioritised.
# ─────────────────────────────────────────────────────────────────────────────

_phase_0b_focus() {
  echo "  ┌─ 0-B: Session Focus ────────────────────────────────────────────────"

  if [[ -n "${SPIRAL_FOCUS:-}" ]]; then
    echo "  │  Focus already set: \"$SPIRAL_FOCUS\" (from --focus)"
  else
    echo "  │  What should Spiral focus on this session?"
    echo "  │  Example: \"Chrome DevTools integration\", \"fix test flakiness\""
    printf "  │  > "
    local _focus_input
    read -r _focus_input 2>/dev/null || _focus_input=""
    if [[ -n "$_focus_input" ]]; then
      SPIRAL_FOCUS="$_focus_input"
      export SPIRAL_FOCUS
      echo "  │  [0-B] Focus set: \"$SPIRAL_FOCUS\""
    else
      echo "  │  [0-B] No focus — running full backlog."
    fi
  fi

  echo "  └─────────────────────────────────────────────────────────────────────"
  echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# 0-C  CLARIFYING QUESTIONS
# Three targeted questions whose answers get appended to SPIRAL_FOCUS,
# giving Phase R and Ralph richer context to avoid story drift.
# ─────────────────────────────────────────────────────────────────────────────

_phase_0c_questions() {
  echo "  ┌─ 0-C: Clarifying Questions ─────────────────────────────────────────"
  echo "  │  Answers help Spiral avoid scope drift. (Enter to skip any.)"
  echo "  │"

  local _q1="" _q2="" _q3="" _any_answered=0

  printf "  │  Q1. What is the #1 outcome you want after this session?\n  │  > "
  read -r _q1 2>/dev/null || _q1=""

  printf "  │\n  │  Q2. Any files or areas that should NOT be changed?\n  │  > "
  read -r _q2 2>/dev/null || _q2=""

  printf "  │\n  │  Q3. Any hard constraints? (no new deps, bundle size, API version, etc.)\n  │  > "
  read -r _q3 2>/dev/null || _q3=""

  # Append meaningful answers to SPIRAL_FOCUS so Phase R receives the context
  local _extra=""
  [[ -n "$_q1" ]] && { _extra="${_extra:+$_extra | }Goal: $_q1"; _any_answered=1; }
  [[ -n "$_q2" ]] && { _extra="${_extra:+$_extra | }Avoid: $_q2"; _any_answered=1; }
  [[ -n "$_q3" ]] && { _extra="${_extra:+$_extra | }Constraint: $_q3"; _any_answered=1; }

  if [[ "$_any_answered" -eq 1 ]]; then
    if [[ -n "${SPIRAL_FOCUS:-}" ]]; then
      SPIRAL_FOCUS="${SPIRAL_FOCUS} | ${_extra}"
    else
      SPIRAL_FOCUS="$_extra"
    fi
    export SPIRAL_FOCUS
    echo "  │"
    echo "  │  [0-C] Context captured — appended to session focus."
  else
    echo "  │"
    echo "  │  [0-C] No answers provided — proceeding with current context."
  fi

  _PHASE0_Q1="$_q1"
  _PHASE0_Q2="$_q2"
  _PHASE0_Q3="$_q3"

  echo "  └─────────────────────────────────────────────────────────────────────"
  echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# 0-D  INITIAL STORIES
# Show AI-suggested story seeds derived from prd.json goals & epics + focus.
# User can type free-form seeds, pick suggestions by number, or skip.
# ─────────────────────────────────────────────────────────────────────────────

_phase_0d_stories() {
  local prd_file="${PRD_FILE:-prd.json}"

  echo "  ┌─ 0-D: Initial Stories ──────────────────────────────────────────────"

  # Generate story suggestions based on prd.json + focus
  local _suggestions
  _suggestions=$("$SPIRAL_PYTHON" - "$prd_file" "${SPIRAL_FOCUS:-}" 2>/dev/null <<'_PY'
import json, sys

prd_file, focus = sys.argv[1], sys.argv[2]

try:
    with open(prd_file, encoding="utf-8") as f:
        prd = json.load(f)
except Exception:
    prd = {}

epics   = prd.get("epics", [])
goals   = prd.get("goals", [])
results = []

# From epics (most concrete)
for epic in epics[:3]:
    title = epic.get("title", "").strip()
    desc  = (epic.get("description") or "").strip()
    if title:
        label = f"Implement: {title}"
        if desc:
            label += f" — {desc[:55]}{'…' if len(desc) > 55 else ''}"
        results.append(label)

# From goals
for goal in goals[:5]:
    if goal.strip() and len(results) < 5:
        results.append(f"Goal: {goal.strip()}")

# From focus keywords
if focus and len(results) < 5:
    kw = focus.split("|")[0].strip()
    results.append(f"Improve: {kw}")

for i, s in enumerate(results[:5], 1):
    print(f"    [{i}] {s}")
_PY
)

  if [[ -n "$_suggestions" ]]; then
    echo "  │  Suggested seeds based on your goals & focus:"
    echo "$_suggestions" | sed 's/^/  │/'
    echo "  │"
    echo "  │  Type seeds or enter a number from above (blank line to finish):"
  else
    echo "  │  Enter initial story seeds (blank line to finish):"
  fi
  echo "  │  Example: Add dark mode toggle to dashboard"
  echo "  │"

  # Build lookup array for numeric selection
  local _sug_arr=()
  if [[ -n "$_suggestions" ]]; then
    while IFS= read -r _sline; do
      local _text
      _text=$(echo "$_sline" | sed 's/.*\[[0-9]\] //')
      _sug_arr+=("$_text")
    done <<< "$_suggestions"
  fi

  local _seeds=()
  local _seed_line=""
  while true; do
    printf "  │  > "
    read -r _seed_line 2>/dev/null || break
    [[ -z "$_seed_line" ]] && break
    # Numeric pick
    if [[ "$_seed_line" =~ ^[0-9]+$ ]] && \
       [[ "$_seed_line" -ge 1 ]] && \
       [[ "$_seed_line" -le "${#_sug_arr[@]}" ]]; then
      local _idx=$(( _seed_line - 1 ))
      _seed_line="${_sug_arr[$_idx]}"
      echo "  │    → $_seed_line"
    fi
    _seeds+=("$_seed_line")
  done

  local _seeds_added=0
  if [[ ${#_seeds[@]} -gt 0 ]]; then
    echo "  │"
    echo "  │  [0-D] Adding ${#_seeds[@]} story seed(s) to prd.json..."

    local _max_id
    _max_id=$("$SPIRAL_PYTHON" - "$prd_file" 2>/dev/null <<'_PY'
import json, sys, re
with open(sys.argv[1], encoding="utf-8") as f:
    prd = json.load(f)
prefix = prd.get("storyIdPrefix", "US")
max_n = 0
for s in prd.get("userStories", []):
    m = re.match(rf"^{re.escape(prefix)}-(\d+)$", s.get("id", ""))
    if m:
        max_n = max(max_n, int(m.group(1)))
print(max_n)
_PY
) || _max_id=0

    local _next_id=$(( _max_id + 1 ))
    local _story_prefix
    _story_prefix=$("$SPIRAL_PYTHON" -c "
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    prd = json.load(f)
print(prd.get('storyIdPrefix', 'US'))
" "$prd_file" 2>/dev/null) || _story_prefix="US"

    for _seed in "${_seeds[@]}"; do
      local _story_id="${_story_prefix}-${_next_id}"
      local _ts
      _ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)
      "$SPIRAL_PYTHON" - "$prd_file" "$_story_id" "$_seed" "$_ts" 2>/dev/null <<'_PY' \
        || { echo "  │  WARNING: Failed to add '$_seed'" >&2; continue; }
import json, sys
prd_file, story_id, title, ts = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
with open(prd_file, encoding="utf-8") as f:
    prd = json.load(f)
new_story = {
    "id": story_id,
    "title": title,
    "priority": "medium",
    "passes": False,
    "description": title,
    "acceptanceCriteria": [],
    "seed": True,
    "added_by": "phase_0_clarify",
    "added_ts": ts,
}
prd["userStories"].append(new_story)
with open(prd_file, "w", encoding="utf-8") as f:
    json.dump(prd, f, indent=2, ensure_ascii=False)
_PY
      echo "  │  [0-D]   Added [$_story_id] $_seed"
      _next_id=$(( _next_id + 1 ))
      _seeds_added=$(( _seeds_added + 1 ))
    done
  else
    echo "  │  [0-D] No seeds added — Phase R will discover stories autonomously."
  fi

  _PHASE0_SEEDS_ADDED=$_seeds_added

  echo "  └─────────────────────────────────────────────────────────────────────"
  echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# 0-E  SESSION OPTIONS
# Time limit and other session-level knobs.
# ─────────────────────────────────────────────────────────────────────────────

_phase_0e_options() {
  echo "  ┌─ 0-E: Session Options ──────────────────────────────────────────────"

  if [[ "${TIME_LIMIT_MINS:-0}" -gt 0 ]]; then
    echo "  │  Time limit: ${TIME_LIMIT_MINS}m (from --time-limit)"
  else
    printf "  │  How many hours should Spiral run? (Enter for unlimited): "
    local _hours_input
    read -r _hours_input 2>/dev/null || _hours_input=""
    if [[ -n "$_hours_input" ]]; then
      if [[ "$_hours_input" =~ ^[0-9]+(\.[0-9]+)?$ ]] && [[ "$_hours_input" != "0" ]]; then
        TIME_LIMIT_MINS=$(python3 -c "import math; print(math.ceil(float('$_hours_input') * 60))" 2>/dev/null || \
          echo $(( ${_hours_input%%.*} * 60 )))
        export TIME_LIMIT_MINS
        echo "  │  [0-E] Time limit: ${TIME_LIMIT_MINS}m (~${_hours_input}h)"
      else
        echo "  │  [0-E] Invalid input ('$_hours_input') — running unlimited."
      fi
    else
      echo "  │  [0-E] No time limit — running unlimited."
    fi
  fi

  echo "  └─────────────────────────────────────────────────────────────────────"
  echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

run_phase_clarify() {
  local prd_file="${PRD_FILE:-prd.json}"
  local scratch="${SCRATCH_DIR:-.spiral}"
  local done_marker="$scratch/_phase_0_done"
  local output_file="$scratch/_clarify_output.json"

  # ── Skip conditions ────────────────────────────────────────────────────────
  if [[ "${GATE_DEFAULT:-}" == "proceed" || "${GATE_DEFAULT:-}" == "skip" ]]; then
    echo "  [Phase 0] Skipping (--gate ${GATE_DEFAULT})"
    return 0
  fi

  if [[ -f "$done_marker" ]]; then
    echo "  [Phase 0] Skipping (checkpoint: phase_0_complete)"
    return 0
  fi

  mkdir -p "$scratch"

  echo ""
  echo "  ╔══════════════════════════════════════════════════════════════════╗"
  echo "  ║  SPIRAL Phase 0 — Session Setup                                 ║"
  echo "  ║  Establish rules, focus, and initial stories before the loop.   ║"
  echo "  ╚══════════════════════════════════════════════════════════════════╝"
  echo ""

  # Tracking vars (globals so sub-functions can write to them)
  _PHASE0_CONSTITUTION_PATH=""
  _PHASE0_CONSTITUTION_CREATED=0
  _PHASE0_SEEDS_ADDED=0
  _PHASE0_Q1=""
  _PHASE0_Q2=""
  _PHASE0_Q3=""

  # ── Sub-phases ─────────────────────────────────────────────────────────────
  _phase_0a_constitution   # Establish ground rules (prevents drift)
  _phase_0b_focus          # Set this session's theme
  _phase_0c_questions      # Refine scope with 3 targeted questions
  _phase_0d_stories        # Add initial story seeds (with AI suggestions)
  _phase_0e_options        # Time limit & other session knobs

  # ── Write audit log ────────────────────────────────────────────────────────
  local _ts_now
  _ts_now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  "$SPIRAL_PYTHON" - \
    "$output_file" \
    "$_ts_now" \
    "${TIME_LIMIT_MINS:-0}" \
    "${SPIRAL_FOCUS:-}" \
    "${_PHASE0_SEEDS_ADDED:-0}" \
    "${_PHASE0_CONSTITUTION_CREATED:-0}" \
    "${_PHASE0_CONSTITUTION_PATH:-}" \
    "${_PHASE0_Q1:-}" \
    "${_PHASE0_Q2:-}" \
    "${_PHASE0_Q3:-}" \
    2>/dev/null <<'_PY' || true
import json, sys

(out_file, ts, time_limit, focus, seeds_added,
 const_created, const_path, q1, q2, q3) = (
    sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4],
    int(sys.argv[5]), int(sys.argv[6]), sys.argv[7],
    sys.argv[8], sys.argv[9], sys.argv[10],
)

data = {
    "phase": "0",
    "ts": ts,
    "time_limit_mins": time_limit,
    "focus": focus,
    "seeds_added": seeds_added,
    "constitution_created": bool(const_created),
    "constitution_path": const_path,
    "clarifying_answers": {
        "q1_primary_outcome": q1,
        "q2_avoid_areas":     q2,
        "q3_constraints":     q3,
    },
}
with open(out_file, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
_PY

  # ── Mark Phase 0 complete (skipped on resume) ──────────────────────────────
  echo "phase_0_complete" > "$done_marker"

  echo ""
  echo "  [Phase 0] Complete — session configured"
  [[ -n "${_PHASE0_CONSTITUTION_PATH:-}" ]] && \
    echo "  [Phase 0]   Constitution : ${_PHASE0_CONSTITUTION_PATH}"
  [[ -n "${SPIRAL_FOCUS:-}" ]] && \
    echo "  [Phase 0]   Focus        : ${SPIRAL_FOCUS:0:72}"
  [[ "${TIME_LIMIT_MINS:-0}" -gt 0 ]] && \
    echo "  [Phase 0]   Time limit   : ${TIME_LIMIT_MINS}m"
  [[ "${_PHASE0_SEEDS_ADDED:-0}" -gt 0 ]] && \
    echo "  [Phase 0]   Seeds added  : ${_PHASE0_SEEDS_ADDED}"
  echo ""
}

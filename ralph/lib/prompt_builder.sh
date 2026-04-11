#!/usr/bin/env bash
# ralph/lib/prompt_builder.sh — System + user prompt assembly for Ralph
# Extracted from ralph.sh to a standalone library (US-prompt-builder refactor).
# Sets RALPH_SYSTEM_PROMPT and RALPH_USER_PROMPT in the calling scope.
# All variables used here (PROMPT_FILE, NEXT_STORY, STORY_TITLE, STORY_JSON, etc.)
# are expected to be set by the caller (ralph.sh main loop).

build_ralph_prompts() {
  # Build prompt content — split into system prompt (cacheable) and user prompt (dynamic)
  # US-338: Cache-aware prompt structure. The system prompt MUST be identical across
  # stories/retries so Anthropic prompt caching preserves the prefix. All dynamic
  # values (story IDs, iteration numbers, masking stats) go into user prompt ONLY.
  RALPH_SYSTEM_PROMPT="$(cat "$PROMPT_FILE")"
  SPECKIT_CONST=".specify/memory/constitution.md"
  if [[ -f "$SPECKIT_CONST" ]]; then
    RALPH_SYSTEM_PROMPT="$RALPH_SYSTEM_PROMPT


## Project Constitution (Spec-Kit — non-negotiable standards)

$(cat "$SPECKIT_CONST")
"
    echo "  [speckit] Constitution loaded ($(wc -l <"$SPECKIT_CONST") lines)"
  fi
  # US-338: RALPH_FOCUS moved to user prompt to preserve cache prefix stability.
  # The system prompt must be identical across stories/retries for prompt caching.
  # Detect Chrome DevTools MCP availability
  BROWSER_TOOLS_HINT=""
  if claude --help 2>&1 | grep -q "chrome-devtools" 2>/dev/null || [[ -n "${CHROME_DEVTOOLS_MCP:-}" ]]; then
    BROWSER_TOOLS_HINT="Chrome DevTools MCP is available. Use visual verification for UI stories."
  fi
  if [[ -n "$BROWSER_TOOLS_HINT" ]]; then
    RALPH_SYSTEM_PROMPT="$RALPH_SYSTEM_PROMPT


## Browser Tools

$BROWSER_TOOLS_HINT"
    echo "  [browser] Chrome DevTools MCP detected — visual verification enabled"
  fi
  # ── US-340: Load per-tool usage examples into system prompt ──────────
  _TOOL_EXAMPLES_FILE="${SCRIPT_DIR}/tool_examples.json"
  if [[ -f "$_TOOL_EXAMPLES_FILE" ]]; then
    _TOOL_EXAMPLES_MD=$("$JQ" -r '
        .tools | to_entries[] |
        "### " + .value.description + " (" + .key + ")\n" +
        ([.value.input_examples[] |
          "- **" + .description + "**\n  ```json\n  " + (.input | tojson) + "\n  ```"
        ] | join("\n"))
      ' "$_TOOL_EXAMPLES_FILE" 2>/dev/null || true)
    if [[ -n "$_TOOL_EXAMPLES_MD" ]]; then
      RALPH_SYSTEM_PROMPT="$RALPH_SYSTEM_PROMPT


## Tool Usage Examples

$_TOOL_EXAMPLES_MD"
      echo "  [tools] Tool examples loaded ($("$JQ" '[.tools[].input_examples | length] | add' "$_TOOL_EXAMPLES_FILE") examples from $_TOOL_EXAMPLES_FILE)"
    fi
  fi

  # Minimal user prompt — the system prompt has all instructions
  # CRITICAL: Pin the story ID so Ralph cannot self-select a different story.
  RALPH_USER_PROMPT="Implement story **${NEXT_STORY}** (\"${STORY_TITLE}\") from prd.json now. This is the story assigned to you by the SPIRAL orchestrator — do NOT pick a different story. Read prd.json for the full details of ${NEXT_STORY}, read progress.txt for codebase context, then implement ${NEXT_STORY} only."

  # ── US-251: Replay hint injected into system prompt (not user prompt) ────
  # SPIRAL_REPLAY_HINT is set by spiral.sh --hint during --replay mode.
  # Placed in system prompt (not user prompt) to reduce prompt injection risk.
  if [[ -n "${SPIRAL_REPLAY_HINT:-}" ]]; then
    RALPH_SYSTEM_PROMPT="$RALPH_SYSTEM_PROMPT


## Operator Replay Hint

$SPIRAL_REPLAY_HINT"
    echo "  [replay-hint] Extra context injected into system prompt"
  fi

  # ── US-338: Focus hint injected into user prompt (not system prompt) ────
  if [[ -n "$RALPH_FOCUS" ]]; then
    RALPH_USER_PROMPT="$RALPH_USER_PROMPT


## Iteration Focus: $RALPH_FOCUS

This SPIRAL iteration is focused on **$RALPH_FOCUS**. Keep this theme in mind while implementing the assigned story. Prioritize approaches that align with this focus area."
    echo "  [focus] Focus context injected into user prompt: \"$RALPH_FOCUS\""
  fi

  # ── US-597: File-aware retry — restrict re-implementation to failed files only ──
  if [[ -n "${RALPH_FILES_ONLY:-}" ]]; then
    RALPH_USER_PROMPT="$RALPH_USER_PROMPT


## File-Aware Retry — Failed Files Only

This is a targeted retry. The previous attempt failed on specific files. **Only re-implement these files**; do not touch any other files:

$RALPH_FILES_ONLY

Skip files not in this list even if they seem related."
    echo "  [files-only] Retry restricted to failed files: $RALPH_FILES_ONLY"
  fi

  # ── US-353: Plan cache injection (suggested_approach) ──────────────────
  if [[ "${SPIRAL_PLAN_CACHE_ENABLED:-true}" == "true" && -n "${NEXT_STORY:-}" ]]; then
    _PLAN_CACHE_DIR="${SPIRAL_SCRATCH_DIR:-.spiral}/plan_cache"
    if [[ -d "$_PLAN_CACHE_DIR" ]]; then
      _PC_STORY_TMP=$(mktemp -p "${SPIRAL_SCRATCH_DIR:-.spiral}" _pc_story_XXXXXX.json 2>/dev/null || echo "${SPIRAL_SCRATCH_DIR:-.spiral}/_pc_story_$$.json")
      printf '%s' "${STORY_JSON:-{}}" >"$_PC_STORY_TMP"
      _PC_INJECT=$("${SPIRAL_PYTHON:-python3}" "$SPIRAL_HOME/lib/resilience/plan_cache.py" inject "$_PLAN_CACHE_DIR" \
        --story-json "$_PC_STORY_TMP" \
        --ttl-hours "${SPIRAL_PLAN_CACHE_TTL_HOURS:-168}" 2>/dev/null || true)
      if [[ -n "$_PC_INJECT" ]]; then
        RALPH_USER_PROMPT="$RALPH_USER_PROMPT


$_PC_INJECT"
        echo "  [plan-cache] HIT: suggested approach injected for $NEXT_STORY"
        log_ralph_event "plan_cache_hit" "\"story_id\":\"$NEXT_STORY\""
      else
        log_ralph_event "plan_cache_miss" "\"story_id\":\"$NEXT_STORY\""
      fi
      rm -f "$_PC_STORY_TMP" 2>/dev/null || true
    fi
  fi

  # ── US-649: Memory injection via --memory-inject flag ────────────────────────
  if [[ "${RALPH_MEMORY_INJECT:-false}" == "true" && -n "${STORY_TITLE:-}" ]]; then
    _MEM_PY="$SPIRAL_HOME/lib/episodic_memory.py"
    _MEM_JSONL="${SPIRAL_SCRATCH_DIR:-.spiral}/episodic_memory.jsonl"
    if [[ -f "$_MEM_PY" && -f "$_MEM_JSONL" ]]; then
      _MEM_RAW=$("${SPIRAL_PYTHON:-python3}" "$_MEM_PY" query \
        --text "$STORY_TITLE" --memory-path "$_MEM_JSONL" --top-k 3 2>/dev/null || true)
      if [[ -n "$_MEM_RAW" ]]; then
        RALPH_USER_PROMPT="$RALPH_USER_PROMPT


## Similar past implementations: [$_MEM_RAW]

(Reference only — do not copy verbatim.)"
        echo "  [memory-inject] Similar past implementations injected for $NEXT_STORY"
        log_ralph_event "memory_inject_hit" "\"story_id\":\"$NEXT_STORY\""
      else
        echo "  [memory-inject] No similar patterns found for $NEXT_STORY — skipping injection"
      fi
    fi
  fi

  # ── US-427: Episodic memory injection (top-3 similar past implementations) ──
  _EPISODIC_SCRIPT="$SPIRAL_HOME/lib/resilience/episodic_memory.py"
  _EPISODIC_DB="${SPIRAL_SCRATCH_DIR:-.spiral}/episodic_memory.db"
  if [[ "${SPIRAL_EPISODIC_MEMORY:-false}" == "true" && -f "$_EPISODIC_SCRIPT" && -f "$_EPISODIC_DB" && -n "${STORY_TITLE:-}" ]]; then
    _EPISODIC_RAW=$("${SPIRAL_PYTHON:-python3}" "$_EPISODIC_SCRIPT" query "$_EPISODIC_DB" "$STORY_TITLE" --top-k 3 2>/dev/null || true)
    if [[ -n "$_EPISODIC_RAW" && "$_EPISODIC_RAW" != "[]" ]]; then
      _EPISODIC_BLOCK="## Episodic Memory — Top 3 Similar Past Implementations

$_EPISODIC_RAW

(Reference only — do not copy verbatim.)"
      RALPH_USER_PROMPT="$RALPH_USER_PROMPT


$_EPISODIC_BLOCK"
      echo "  [episodic] Top-3 similar past implementations injected for $NEXT_STORY"
      log_ralph_event "episodic_memory_injected" "\"story_id\":\"$NEXT_STORY\""
    fi
  fi

  # ── US-1214: Phase L learned patterns injection ─────────────────────────
  # Read latest learned_patterns_iter_*.json, filter by tag overlap with current story,
  # and inject top 3 matching patterns into the user prompt.
  if [[ -n "${STORY_JSON:-}" && "${STORY_JSON:-}" != "{}" ]]; then
    # Find latest learned_patterns file (bash portable, no dependency on find)
    _LP_LATEST=""
    if [[ -d "${SPIRAL_SCRATCH_DIR:-.spiral}" ]]; then
      _LP_LATEST=$(cd "${SPIRAL_SCRATCH_DIR:-.spiral}" 2>/dev/null &&
        ls -1 learned_patterns_iter_*.json 2>/dev/null | sort -V | tail -1 || echo "")
    fi

    if [[ -n "$_LP_LATEST" ]]; then
      _LP_PATH="${SPIRAL_SCRATCH_DIR:-.spiral}/$_LP_LATEST"
      # Extract top 3 patterns by frequency and format for injection
      _LP_FILTERED=$($JQ -r '.patterns // [] | sort_by(.frequency) | reverse | .[0:3] |
        map("- Pattern: " + (.pattern // "") + " (observed \(.frequency)x)") | join("\n")' \
        "$_LP_PATH" 2>/dev/null || echo "")

      if [[ -n "$_LP_FILTERED" ]]; then
        RALPH_USER_PROMPT="$RALPH_USER_PROMPT


## Learned Patterns from Phase L

$_LP_FILTERED"
        echo "  [learned-patterns] Top 3 patterns injected from $_LP_LATEST"
        log_ralph_event "learned_patterns_injected" "\"story_id\":\"$NEXT_STORY\",\"pattern_file\":\"$_LP_LATEST\""
      fi
    fi
  fi

  # ── US-280: File context injection (diff or full) ────────────────────────
  if [[ -n "${STORY_JSON:-}" && "${STORY_JSON:-}" != "{}" ]]; then
    _FILE_CTX=$(build_files_context "$STORY_JSON" 2>/dev/null || true)
    if [[ -n "$_FILE_CTX" ]]; then
      _FC_LINES=$(printf '%s\n' "$_FILE_CTX" | wc -l)
      echo "  [context] File context injected (${SPIRAL_CONTEXT_MODE:-diff} mode, ${_FC_LINES} lines)"
      RALPH_USER_PROMPT="$RALPH_USER_PROMPT


$_FILE_CTX"
    fi
  fi

  # ── Phase X: Repo map / symbol map injection ────────────────────────────
  _REPO_MAP_FILE="${SPIRAL_SCRATCH_DIR:-.spiral}/_repo_map_${NEXT_STORY}.md"
  if [[ "${SPIRAL_REPO_MAP:-false}" == "true" && -f "$_REPO_MAP_FILE" ]]; then
    _REPO_MAP_CONTENT=$(cat "$_REPO_MAP_FILE" 2>/dev/null || true)
    if [[ -n "$_REPO_MAP_CONTENT" ]]; then
      RALPH_USER_PROMPT="$RALPH_USER_PROMPT


$_REPO_MAP_CONTENT"
      echo "  [repo-map] Symbol map injected for $NEXT_STORY"
      log_ralph_event "repo_map_injected" "\"story_id\":\"$NEXT_STORY\""
    fi
  fi

  # ── Retry context injection with observation masking (US-241) ────────────
  # On attempt 2+, prepend a concise brief so the agent doesn't need to hunt
  # through progress.txt to find what the previous attempt learned.
  # Observation masking: keep only the last SPIRAL_CONTEXT_WINDOW attempts in
  # full; replace older ones with one-line placeholders to reduce token cost.
  if [[ "${RETRY_NOW:-0}" -ge 1 ]]; then
    _PREV_ATTEMPT=$((RETRY_NOW))
    _FAIL_REASON=$($JQ -r ".userStories[] | select(.id == \"$NEXT_STORY\") | ._failureReason // \"(not recorded)\"" "$PRD_FILE" 2>/dev/null | tr -d '\r' || echo "(not recorded)")
    # Extract the last progress.txt section(s) mentioning this story
    _RETRY_NOTES=""
    if [[ -f "$PROGRESS_FILE" ]]; then
      # Grab up to 40 lines from the end of progress.txt that mention the story
      _RETRY_NOTES=$(grep -A 8 -B 2 "$NEXT_STORY" "$PROGRESS_FILE" 2>/dev/null | tail -40 || true)
    fi

    # US-241: Record this attempt as an observation in the rolling buffer
    _CUR_OBS="=== Attempt ${RETRY_NOW} ===
Failure reason: ${_FAIL_REASON}
Notes:
${_RETRY_NOTES:-  (none found)}"
    _OBS_HISTORY+=("$_CUR_OBS")

    # Apply rolling window: mask observations older than SPIRAL_CONTEXT_WINDOW
    _WINDOW=${SPIRAL_CONTEXT_WINDOW:-10}
    _OBS_COUNT=${#_OBS_HISTORY[@]}
    _MASK_COUNT=$((_OBS_COUNT > _WINDOW ? _OBS_COUNT - _WINDOW : 0))

    # Build the (possibly masked) context string
    _MASKED_CONTEXT=""
    for ((_oi = 0; _oi < _OBS_COUNT; _oi++)); do
      if ((_oi < _MASK_COUNT)); then
        # Replace with one-line placeholder — extract just the failure reason
        _SHORT_REASON=$(printf '%s' "${_OBS_HISTORY[$_oi]}" | grep "^Failure reason:" | head -1 | cut -c 1-100)
        _MASKED_CONTEXT="${_MASKED_CONTEXT}[Attempt $((_oi + 1)): omitted for brevity — ${_SHORT_REASON:-reason not recorded}]
"
      else
        _MASKED_CONTEXT="${_MASKED_CONTEXT}${_OBS_HISTORY[$_oi]}
"
      fi
    done

    # Estimate tokens (chars ÷ 4) and accumulate stats
    _FULL_CHARS=$(printf '%s' "${_OBS_HISTORY[*]}" | wc -c 2>/dev/null || echo 0)
    _MASKED_CHARS=${#_MASKED_CONTEXT}
    _FULL_TOKENS=$(((_FULL_CHARS + 3) / 4))
    _MASKED_TOKENS=$(((_MASKED_CHARS + 3) / 4))
    _OBS_TOKENS_BEFORE=$((_OBS_TOKENS_BEFORE + _FULL_TOKENS))
    _OBS_TOKENS_AFTER=$((_OBS_TOKENS_AFTER + _MASKED_TOKENS))

    # US-338: Masking note goes into user prompt (not system prompt) to preserve
    # prompt cache stability — the system prompt must be identical across stories.
    _MASKING_NOTE=""
    if ((_MASK_COUNT > 0)); then
      _REDUCTION_PCT=$(((_FULL_TOKENS - _MASKED_TOKENS) * 100 / (_FULL_TOKENS + 1)))
      _MASKING_NOTE="NOTE: ${_MASK_COUNT} earlier phase output(s) omitted for brevity (kept last ${_WINDOW} of ${_OBS_COUNT}).
"
      _CONTEXT_MGMT_NOTE="


## Context Management

Earlier phase outputs omitted for brevity (${_MASK_COUNT} of ${_OBS_COUNT} attempt(s) masked; ${_REDUCTION_PCT}% token reduction)."
      echo "  [context] Observation masking: ${_MASK_COUNT}/${_OBS_COUNT} attempts masked (${_REDUCTION_PCT}% reduction, ${_FULL_TOKENS}→${_MASKED_TOKENS} tokens)"
      log_ralph_event "context_mask" \
        "\"story_id\":\"$NEXT_STORY\",\"attempts\":$_OBS_COUNT,\"masked\":$_MASK_COUNT,\"tokens_before\":$_FULL_TOKENS,\"tokens_after\":$_MASKED_TOKENS,\"reduction_pct\":$_REDUCTION_PCT"
      # Write _contextStats to prd.json per story (US-241)
      if [[ "${_OBS_TOKENS_BEFORE:-0}" -gt 0 ]]; then
        $JQ --argjson ctxstats \
          "{\"tokensBeforeMasking\":${_OBS_TOKENS_BEFORE},\"tokensAfterMasking\":${_OBS_TOKENS_AFTER},\"reductionPct\":${_REDUCTION_PCT},\"contextWindow\":${_WINDOW}}" \
          '(.userStories[] | select(.id == "'"$NEXT_STORY"'") | ._contextStats) = $ctxstats' \
          "$PRD_FILE" >"${PRD_FILE}.tmp" && mv "${PRD_FILE}.tmp" "$PRD_FILE" || true
      fi
      # Write _context_stats.json for spiral.sh write_iter_summary to merge
      _CTX_STATS_FILE="${SPIRAL_SCRATCH_DIR}/_context_stats.json"
      _CTX_STATS_TMP="${_CTX_STATS_FILE}.tmp.$$"
      printf '{"tokensBeforeMasking":%d,"tokensAfterMasking":%d,"reductionPct":%d,"contextWindow":%d}\n' \
        "$_OBS_TOKENS_BEFORE" "$_OBS_TOKENS_AFTER" "$_REDUCTION_PCT" "$_WINDOW" \
        >"$_CTX_STATS_TMP" && mv "$_CTX_STATS_TMP" "$_CTX_STATS_FILE" 2>/dev/null || true
    fi

    _RETRY_BRIEF="RETRY CONTEXT — ATTEMPT $((RETRY_NOW + 1)) of $MAX_RETRIES

Story $NEXT_STORY (\"$STORY_TITLE\") was attempted $RETRY_NOW time(s) and did NOT pass.
${_MASKING_NOTE}Previous attempt observations:
${_MASKED_CONTEXT}
ACTION: Do NOT repeat the same approach that failed. Read progress.txt carefully for what
was tried, then implement the story differently. You are using a more powerful model this
attempt ($EFFECTIVE_MODEL) — use it."

    # Strategy 1: Anti-pattern injection — list every previously-tried approach that
    # failed so the agent cannot accidentally repeat it. Reads _antiPatterns[] from
    # prd.json (accumulated by ralph after each failed attempt).
    if [[ "${SPIRAL_ANTI_PATTERN_INJECT:-true}" == "true" ]]; then
      _AP_LIST=$($JQ -r \
        ".userStories[] | select(.id == \"$NEXT_STORY\") | ._antiPatterns // [] | to_entries[] | \"  \(.key+1). \(.value[:150])\"" \
        "$PRD_FILE" 2>/dev/null | head -5 | tr -d '\r' || true)
      if [[ -n "$_AP_LIST" ]]; then
        _AP_COUNT=$(printf '%s\n' "$_AP_LIST" | wc -l | tr -d ' ')
        _RETRY_BRIEF="${_RETRY_BRIEF}

FORBIDDEN APPROACHES — DO NOT TRY any of these (all previously failed):
${_AP_LIST}

Choose a COMPLETELY DIFFERENT implementation strategy from the ones listed above."
        echo "  [anti-pattern] $_AP_COUNT anti-pattern(s) injected for $NEXT_STORY"
        log_ralph_event "anti_pattern_injected" \
          "\"story_id\":\"$NEXT_STORY\",\"retry\":$RETRY_NOW,\"count\":$_AP_COUNT"
      fi
    fi

    RALPH_USER_PROMPT="$_RETRY_BRIEF${_CONTEXT_MGMT_NOTE:-}


$RALPH_USER_PROMPT"
    echo "  [retry] Attempt $((RETRY_NOW + 1))/$MAX_RETRIES — injected failure context ($RETRY_NOW prior attempt(s), reason: ${_FAIL_REASON:0:60})"
  fi

  # ── filesTouch diff context injection (US-280) ────────────────────────────
  # Inject a unified diff of the story's filesTouch paths so the agent has
  # precise delta context without reading full files from disk.
  _FT_BODY_TMP="${SPIRAL_SCRATCH_DIR}/_ft_ctx_$$.tmp"
  _FT_STATUS=$(build_filestouch_context "$STORY_JSON" 2>&1 1>"$_FT_BODY_TMP" || true)
  _FT_CONTEXT_BODY=$(cat "$_FT_BODY_TMP" 2>/dev/null || true)
  rm -f "$_FT_BODY_TMP"
  if [[ -n "$_FT_CONTEXT_BODY" ]]; then
    RALPH_USER_PROMPT="${RALPH_USER_PROMPT}


${_FT_CONTEXT_BODY}"
    [[ -n "$_FT_STATUS" ]] && echo "$_FT_STATUS"
  fi
}

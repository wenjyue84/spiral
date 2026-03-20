#!/usr/bin/env bash
# lib/phases/phase_r_research.sh — Phase R: RESEARCH
#
# Discovers new user story candidates by:
#   1. Running Gemini CLI for free-tier web pre-fetch (if configured)
#   2. Spawning a Claude research agent with the injected research prompt
#      (includes prd.json goals, focus directive, constitution if set)
#   3. Caching results to avoid redundant API calls on retries
#
# Inputs (globals):
#   $PRD_FILE                  — current prd.json
#   $RESEARCH_OUTPUT           — output path (set by phase_rt_parallel.sh)
#   $RESEARCH_CACHE_DIR        — cache directory for URL content
#   $SCRATCH_DIR               — runtime scratch directory
#   $REPO_ROOT                 — project repository root
#   $SPIRAL_HOME               — SPIRAL installation directory
#   $SPIRAL_ITER               — current iteration number
#   $SPIRAL_PYTHON             — Python interpreter (uv run python)
#   $JQ                        — jq binary path
#   $STREAM_FMT                — Node.js stream formatter path
#   $_phase_r_ckpt             — checkpoint file for Phase R completion
#
# Config vars (spiral.config.sh):
#   SPIRAL_RESEARCH_MODEL          — Claude model (default: sonnet)
#   SPIRAL_RESEARCH_TIMEOUT        — seconds before timeout (default: 300)
#   SPIRAL_RESEARCH_RETRIES        — retry count on missing output (default: 2)
#   SPIRAL_FIRECRAWL_ENABLED       — 1 = use Firecrawl MCP for scraping
#   SPIRAL_GEMINI_PROMPT           — Gemini web pre-research prompt
#   SPIRAL_GEMINI_FALLBACK_MODEL   — Claude model for Gemini fallback
#   SPIRAL_SPECKIT_CONSTITUTION    — constitution file path
#   SPIRAL_RESEARCH_CACHE_TTL_HOURS — cache TTL in hours
#   SPIRAL_CACHE_SIM_THRESHOLD     — query embedding similarity threshold
#
# Outputs:
#   $RESEARCH_OUTPUT               — discovered story candidates (JSON)
#   $_phase_r_ckpt                 — touched on completion
#   $SCRATCH_DIR/_phase_R_${SPIRAL_ITER}.endtime — epoch timestamp
#
# Called from phase_rt_parallel.sh inside a subshell — no scope leaks.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_research() {
  # ── Research cache: prune expired entries ──────────────────────────────
  if [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]]; then
    mkdir -p "$RESEARCH_CACHE_DIR"
    PRUNED=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research/research_cache.py" prune "$RESEARCH_CACHE_DIR" --ttl-hours "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" 2>/dev/null | grep -oP '\d+' || echo "0")
    [[ "$PRUNED" -gt 0 ]] && echo "  [R] Cache: pruned $PRUNED expired entries (TTL=${SPIRAL_RESEARCH_CACHE_TTL_HOURS}h)"
  fi

  # ── Topic-level research cache (US-520): lookup cached result for this topic ──
  GEMINI_RESEARCH=""
  _PHASE_R_PRE_MODEL="none" # US-206: track which model served Phase R pre-research
  _RESEARCH_TOPIC_CACHED=""
  if [[ -n "$SPIRAL_GEMINI_PROMPT" ]]; then
    # Derive research topic from SPIRAL_GEMINI_PROMPT (or use a default)
    _RESEARCH_TOPIC="${SPIRAL_GEMINI_PROMPT:0:100}"  # First 100 chars as topic identifier
    _TOPIC_CACHE_RESULT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/phases/research_cache.py" --lookup "$_RESEARCH_TOPIC" 2>/dev/null || echo "")
    if [[ -n "$_TOPIC_CACHE_RESULT" ]]; then
      # Cache hit: extract gemini_research from cached dict
      echo "  [R] Topic-level cache hit — reusing cached Gemini research (US-520)"
      GEMINI_RESEARCH=$("$JQ" -r '.gemini_research // .content // .' <<< "$_TOPIC_CACHE_RESULT" 2>/dev/null || echo "$_TOPIC_CACHE_RESULT")
      _RESEARCH_TOPIC_CACHED=1
    fi
  fi

  # ── Gemini web research (optional, configured via SPIRAL_GEMINI_PROMPT) ──
  if command -v gemini &>/dev/null && [[ -n "$SPIRAL_GEMINI_PROMPT" ]] && [[ -z "$_RESEARCH_TOPIC_CACHED" ]]; then
    echo "  [R] Running Gemini 2.5 Pro web research (-y web search enabled)..."
    GEMINI_ERR_TMP=$(mktemp)
    GEMINI_RESEARCH=$(gemini \
      -m gemini-2.5-pro \
      -p "$SPIRAL_GEMINI_PROMPT" \
      -y --output-format text 2>"$GEMINI_ERR_TMP" || true)
    if [[ -n "$GEMINI_RESEARCH" ]]; then
      echo "  [R] Gemini web research complete ($(echo "$GEMINI_RESEARCH" | wc -l) lines)"
      _PHASE_R_PRE_MODEL="gemini-2.5-pro"
    else
      # Diagnose failure reason from stderr
      if grep -qi '503\|Service Unavailable\|UNAVAILABLE' "$GEMINI_ERR_TMP" 2>/dev/null; then
        # ── US-206: Gemini 503 — retry once after backoff, then fall back to Claude ──
        echo "  [R] Gemini returned 503 — retrying once after 10s backoff..."
        sleep 10
        rm -f "$GEMINI_ERR_TMP"
        GEMINI_ERR_TMP=$(mktemp)
        GEMINI_RESEARCH=$(gemini \
          -m gemini-2.5-pro \
          -p "$SPIRAL_GEMINI_PROMPT" \
          -y --output-format text 2>"$GEMINI_ERR_TMP" || true)
        if [[ -n "$GEMINI_RESEARCH" ]]; then
          echo "  [R] Gemini web research complete after retry ($(echo "$GEMINI_RESEARCH" | wc -l) lines)"
          _PHASE_R_PRE_MODEL="gemini-2.5-pro"
        else
          # Still failing — fall back to Claude simplified research
          echo "  [R] Gemini still unavailable after retry — falling back to Claude (${SPIRAL_GEMINI_FALLBACK_MODEL})"
          log_spiral_event "gemini_fallback" \
            "\"event_type\":\"gemini_fallback\",\"fallback_model\":\"${SPIRAL_GEMINI_FALLBACK_MODEL}\",\"reason\":\"503\",\"iteration\":$SPIRAL_ITER"
          _GEMINI_FB_ERR=$(mktemp)
          _GEMINI_FB_PROMPT="You are a research assistant. Based on the following prompt, provide a concise research summary in plain text (no JSON needed): ${SPIRAL_GEMINI_PROMPT}"
          GEMINI_RESEARCH=$(
            unset CLAUDECODE
            claude -p "$_GEMINI_FB_PROMPT" \
              --model "${SPIRAL_GEMINI_FALLBACK_MODEL}" \
              --allowedTools "WebSearch,WebFetch" \
              --max-turns 5 \
              --dangerously-skip-permissions \
              </dev/null 2>"$_GEMINI_FB_ERR" || true
          )
          if [[ -n "$GEMINI_RESEARCH" ]]; then
            echo "  [R] Claude fallback research complete (${SPIRAL_GEMINI_FALLBACK_MODEL}, $(echo "$GEMINI_RESEARCH" | wc -l) lines)"
            _PHASE_R_PRE_MODEL="${SPIRAL_GEMINI_FALLBACK_MODEL}"
          else
            _GEMINI_FB_ERR_MSG=$(head -1 "$_GEMINI_FB_ERR" 2>/dev/null || echo "unknown error")
            echo "  [R] Gemini and Claude fallback both failed — $_GEMINI_FB_ERR_MSG — Phase R will proceed without pre-research"
            log_spiral_event "gemini_fallback_failed" \
              "\"reason\":\"both_failed\",\"gemini_error\":\"503\",\"claude_error\":\"${_GEMINI_FB_ERR_MSG}\",\"iteration\":$SPIRAL_ITER"
          fi
          rm -f "$_GEMINI_FB_ERR"
        fi
      elif grep -qi '429\|RESOURCE_EXHAUSTED\|rate.limit\|quota' "$GEMINI_ERR_TMP" 2>/dev/null; then
        echo "  [R] Gemini rate-limited — Claude will browse URLs directly"
      elif grep -qi 'PERMISSION_DENIED\|API.key\|api_key\|UNAUTHENTICATED' "$GEMINI_ERR_TMP" 2>/dev/null; then
        echo "  [R] Gemini auth error — check GEMINI_API_KEY"
      elif [[ -s "$GEMINI_ERR_TMP" ]]; then
        GEMINI_ERR_FIRST=$(head -1 "$GEMINI_ERR_TMP")
        echo "  [R] Gemini web research returned empty — $GEMINI_ERR_FIRST"
      else
        echo "  [R] Gemini web research returned empty — Claude will browse URLs directly"
      fi
    fi
    rm -f "$GEMINI_ERR_TMP"

    # ── Topic-level cache store (US-520): cache the research result if successful ──
    if [[ -n "$GEMINI_RESEARCH" ]] && [[ -z "$_RESEARCH_TOPIC_CACHED" ]]; then
      # Wrap GEMINI_RESEARCH in a dict for caching
      _RESEARCH_RESULT_JSON=$("$JQ" -n --arg content "$GEMINI_RESEARCH" '{gemini_research: $content}')
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/phases/research_cache.py" --store "$_RESEARCH_TOPIC" --result "$_RESEARCH_RESULT_JSON" 2>/dev/null || true
      echo "  [R] Cached Gemini research result for topic (US-520)"
    fi
  fi

  INJECTED_PROMPT=$(build_research_prompt "$SPIRAL_ITER" "$RESEARCH_OUTPUT")
  # Prepend Gemini research context so Claude skips URL browsing and writes JSON faster
  if [[ -n "$GEMINI_RESEARCH" ]]; then
    # ── US-198: LLM Guard scan of Gemini web-fetched content ──────────
    scan_web_content GEMINI_RESEARCH "gemini_research"
    INJECTED_PROMPT="## Pre-Research Context (Gemini 2.5 Pro — web search enabled)

The following compliance research was pre-fetched. Use this as your primary source.
You do NOT need to browse URLs already covered below. Focus on synthesizing this
into the required story JSON format as quickly as possible.

$GEMINI_RESEARCH

---

$INJECTED_PROMPT"
  fi

  # ── Inject cached URL content so agent skips re-fetching ──────────────
  if [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]]; then
    CACHE_CONTEXT=$("$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research/research_cache.py" inject "$RESEARCH_CACHE_DIR" --ttl-hours "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" 2>/dev/null || true)
    if [[ -n "$CACHE_CONTEXT" ]]; then
      # ── US-198: LLM Guard scan of cached URL content ──────────────────
      scan_web_content CACHE_CONTEXT "research_cache"
      CACHE_COUNT=$(ls "$RESEARCH_CACHE_DIR"/*.json 2>/dev/null | wc -l)
      echo "  [R] Cache: injecting $CACHE_COUNT cached URL responses into prompt"
      INJECTED_PROMPT="$CACHE_CONTEXT

---

$INJECTED_PROMPT"
    fi

  fi

  # Inject spec-kit constitution so research respects project standards
  if [[ -n "$SPIRAL_SPECKIT_CONSTITUTION" && -f "$REPO_ROOT/$SPIRAL_SPECKIT_CONSTITUTION" ]]; then
    CONSTITUTION_CONTENT=$(cat "$REPO_ROOT/$SPIRAL_SPECKIT_CONSTITUTION")
    INJECTED_PROMPT="## Project Constitution (Spec-Kit)

The following constitution defines non-negotiable project standards.
All new stories MUST comply with these principles. Do NOT suggest stories
that would violate these standards.

$CONSTITUTION_CONTENT

---

$INJECTED_PROMPT"
    echo "  [R] Spec-Kit constitution injected into research prompt"
  fi

  # Resolve research model: CLI override > config
  RESEARCH_MODEL="${SPIRAL_RESEARCH_MODEL:-haiku}"
  [[ -n "$SPIRAL_CLI_MODEL" ]] && RESEARCH_MODEL="$SPIRAL_CLI_MODEL"

  # Build allowed tools: prefer Firecrawl MCP when configured
  if [[ "${SPIRAL_FIRECRAWL_ENABLED:-0}" -eq 1 ]]; then
    RESEARCH_TOOLS="WebSearch,mcp__firecrawl__scrape,mcp__firecrawl__search,mcp__firecrawl__crawl,Write,Read"
    echo "  [R] Firecrawl MCP enabled — using clean markdown scraping"
  else
    RESEARCH_TOOLS="WebSearch,WebFetch,Write,Read"
  fi

  # ── Retry loop for Phase R ─────────────────────────────────────────────
  _R_ATTEMPT=0
  _R_MAX_ATTEMPTS=$((SPIRAL_RESEARCH_RETRIES + 1))
  _R_SUCCESS=0
  _R_RESULT_TMP="${SCRATCH_DIR}/_r_result_$$.tmp"

  while [[ "$_R_ATTEMPT" -lt "$_R_MAX_ATTEMPTS" ]]; do
    if [[ "$_R_ATTEMPT" -gt 0 ]]; then
      echo "  [R] Research output missing or invalid — retrying (attempt $_R_ATTEMPT/$SPIRAL_RESEARCH_RETRIES)"
    fi

    echo "  [R] Spawning Claude research agent (max 30 turns, model: $RESEARCH_MODEL)..."
    echo "  ─────── Research Agent Start ─────────────────────────"

    _R_EXIT=0
    _R_START=$(date +%s)
    rm -f "$_R_RESULT_TMP"
    if [[ "${SPIRAL_RESEARCH_TIMEOUT:-300}" -gt 0 ]] && command -v timeout &>/dev/null; then
      if command -v node &>/dev/null && [[ -f "$STREAM_FMT" ]]; then
        (
          unset CLAUDECODE
          timeout --kill-after=30 "${SPIRAL_RESEARCH_TIMEOUT}" \
            claude -p "$INJECTED_PROMPT" \
            --model "$RESEARCH_MODEL" \
            --allowedTools "$RESEARCH_TOOLS" \
            --max-turns 30 \
            --verbose \
            --output-format stream-json \
            --betas prompt-caching-2024-07-31 \
            --dangerously-skip-permissions \
            </dev/null 2>&1 | tee "$_R_RESULT_TMP" | node "$STREAM_FMT"
        ) || _R_EXIT=$?
      else
        (
          unset CLAUDECODE
          timeout --kill-after=30 "${SPIRAL_RESEARCH_TIMEOUT}" \
            claude -p "$INJECTED_PROMPT" \
            --model "$RESEARCH_MODEL" \
            --allowedTools "$RESEARCH_TOOLS" \
            --max-turns 30 \
            --betas prompt-caching-2024-07-31 \
            --dangerously-skip-permissions \
            </dev/null 2>&1
        ) || _R_EXIT=$?
      fi
    else
      if command -v node &>/dev/null && [[ -f "$STREAM_FMT" ]]; then
        (
          unset CLAUDECODE
          claude -p "$INJECTED_PROMPT" \
            --model "$RESEARCH_MODEL" \
            --allowedTools "$RESEARCH_TOOLS" \
            --max-turns 30 \
            --verbose \
            --output-format stream-json \
            --betas prompt-caching-2024-07-31 \
            --dangerously-skip-permissions \
            </dev/null 2>&1 | tee "$_R_RESULT_TMP" | node "$STREAM_FMT"
        ) || _R_EXIT=$?
      else
        (
          unset CLAUDECODE
          claude -p "$INJECTED_PROMPT" \
            --model "$RESEARCH_MODEL" \
            --allowedTools "$RESEARCH_TOOLS" \
            --max-turns 30 \
            --betas prompt-caching-2024-07-31 \
            --dangerously-skip-permissions \
            </dev/null 2>&1
        ) || _R_EXIT=$?
      fi
    fi
    # ── Parse Phase R cache tokens (stream-json variants only) ────────────
    if [[ -f "$_R_RESULT_TMP" ]]; then
      _R_RESULT_LINE=$(grep -m1 '"type":"result"' "$_R_RESULT_TMP" 2>/dev/null || true)
      if [[ -n "$_R_RESULT_LINE" && -n "$JQ" ]]; then
        _R_CC=$("$JQ" -r '.usage.cache_creation_input_tokens // 0' <<<"$_R_RESULT_LINE" 2>/dev/null || echo 0)
        _R_CR=$("$JQ" -r '.usage.cache_read_input_tokens // 0' <<<"$_R_RESULT_LINE" 2>/dev/null || echo 0)
        [[ "$_R_CC" =~ ^[0-9]+$ ]] || _R_CC=0
        [[ "$_R_CR" =~ ^[0-9]+$ ]] || _R_CR=0
        if [[ "$_R_CC" -gt 0 || "$_R_CR" -gt 0 ]]; then
          echo "  [cache] Phase R — creation=${_R_CC} read=${_R_CR}"
          log_spiral_event "phase_cache_hit" \
            "\"phase\":\"R\",\"cache_creation_tokens\":${_R_CC},\"cache_read_tokens\":${_R_CR},\"cache_hit\":$([ "$_R_CR" -gt 0 ] && echo true || echo false)"
        fi
      fi
      rm -f "$_R_RESULT_TMP"
    fi
    _R_ELAPSED=$(($(date +%s) - _R_START))
    if [[ "$_R_EXIT" -eq 124 ]]; then
      echo ""
      echo "  [Phase R] WARNING: Research agent timed out after ${_R_ELAPSED}s (limit: ${SPIRAL_RESEARCH_TIMEOUT}s)"
      log_spiral_event "phase_timeout" "\"phase\":\"R\",\"story_id\":\"research\",\"iteration\":$SPIRAL_ITER,\"duration_ms\":$((_R_ELAPSED * 1000)),\"timeout_s\":${SPIRAL_RESEARCH_TIMEOUT}"
    fi

    echo "  ─────── Research Agent End ───────────────────────────"

    # Validate output: file must exist and be valid JSON
    if [[ -f "$RESEARCH_OUTPUT" ]] && "$SPIRAL_PYTHON" -c "import json; json.load(open('$RESEARCH_OUTPUT'))" 2>/dev/null; then
      _R_SUCCESS=1
      break
    fi

    ((_R_ATTEMPT++)) || true
  done

  if [[ "$_R_SUCCESS" -eq 0 ]]; then
    echo "  [R] WARNING: Research output missing or invalid after all retries — using empty"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
  fi

  if [[ ! -f "$RESEARCH_OUTPUT" ]]; then
    echo "  [R] WARNING: Research agent did not write $RESEARCH_OUTPUT — using empty"
    echo '{"stories":[]}' >"$RESEARCH_OUTPUT"
  else
    RESEARCH_COUNT=$("$JQ" '.stories | length' "$RESEARCH_OUTPUT" 2>/dev/null || echo "?")
    echo "  [R] Research complete — $RESEARCH_COUNT story candidates found"

    # ── US-520: Add _cached marker if we used topic-level cache ──────────
    if [[ -n "$_RESEARCH_TOPIC_CACHED" && "$_RESEARCH_TOPIC_CACHED" -eq 1 ]]; then
      _R_CACHED_OUTPUT=$(mktemp)
      "$JQ" '. + {_cached: true}' "$RESEARCH_OUTPUT" >"$_R_CACHED_OUTPUT" 2>/dev/null || true
      if [[ -f "$_R_CACHED_OUTPUT" ]] && "$SPIRAL_PYTHON" -c "import json; json.load(open('$_R_CACHED_OUTPUT'))" 2>/dev/null; then
        mv "$_R_CACHED_OUTPUT" "$RESEARCH_OUTPUT"
        echo "  [R] Marked research output as cached (topic-level cache hit, US-520)"
      fi
      rm -f "$_R_CACHED_OUTPUT"
    fi

    # ── Cache source URLs from research output ─────────────────────────
    if [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]]; then
      CACHED_URLS=0
      while IFS= read -r src_url; do
        [[ -z "$src_url" ]] && continue
        # Extract story content referencing this source for cache value
        STORY_CONTENT=$("$JQ" -r --arg url "$src_url" \
          '[.stories[] | select(.source == $url)] | map(.title + ": " + .description) | join("\n")' \
          "$RESEARCH_OUTPUT" 2>/dev/null || true)
        if [[ -n "$STORY_CONTENT" ]]; then
          echo "$STORY_CONTENT" | "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/research/research_cache.py" store "$RESEARCH_CACHE_DIR" "$src_url" - >/dev/null 2>&1 && ((CACHED_URLS++)) || true
        fi
      done < <("$JQ" -r '[.stories[].source // empty] | unique | .[]' "$RESEARCH_OUTPUT" 2>/dev/null || true)
      [[ "$CACHED_URLS" -gt 0 ]] && echo "  [R] Cache: stored $CACHED_URLS source URLs for future iterations"
    fi

    # ── US-403: Store query embedding so future similar queries hit cache ──
    if [[ -n "$SPIRAL_GEMINI_PROMPT" ]] && [[ "$SPIRAL_RESEARCH_CACHE_TTL_HOURS" -gt 0 ]]; then
      "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/resilience/query_embed_cache.py" store \
        "$RESEARCH_CACHE_DIR" "$SPIRAL_GEMINI_PROMPT" "$RESEARCH_OUTPUT" >/dev/null 2>&1 || true
    fi
  fi

  # Mark Phase R complete and record end time for duration calculation
  touch "$_phase_r_ckpt"
  date +%s >"$SCRATCH_DIR/_phase_R_${SPIRAL_ITER}.endtime"
}

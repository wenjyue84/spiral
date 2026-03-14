#!/usr/bin/env bash
# lib/phases/phase_r_research.sh — Phase R: RESEARCH
#
# Discovers new user story candidates by:
#   1. Running Gemini CLI for free-tier web pre-fetch (if configured)
#   2. Spawning a Claude research agent with the injected research prompt
#      (includes prd.json goals, focus directive, constitution if set)
#   3. Caching results to avoid redundant API calls on retries
#
# Inputs:
#   $PRD_FILE                  — current prd.json
#   $SPIRAL_RESEARCH_PROMPT    — prompt template (with placeholders)
#   $SPIRAL_SPECKIT_CONSTITUTION — optional constitution file path
#   $SPIRAL_FOCUS              — optional focus directive
#
# Outputs:
#   .spiral/_research_output.json   — discovered story candidates
#
# Config vars (spiral.config.sh):
#   SPIRAL_RESEARCH_MODEL          — Claude model (default: sonnet)
#   SPIRAL_RESEARCH_TIMEOUT        — seconds before timeout (default: 300)
#   SPIRAL_RESEARCH_RETRIES        — retry count on missing output (default: 2)
#   SPIRAL_FIRECRAWL_ENABLED       — 1 = use Firecrawl MCP for scraping
#   SKIP_RESEARCH                  — 1 = skip this phase entirely
#
# TODO: extract Phase R block from spiral.sh (lines 1478–1721) into this file.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_research() {
  local iter="$1"
  echo "[Phase R] RESEARCH — iteration $iter"
  # TODO: implement (migrated from spiral.sh lines 1478–1721)
  :
}

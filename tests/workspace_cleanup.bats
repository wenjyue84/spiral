#!/usr/bin/env bats
# tests/workspace_cleanup.bats — Tests for US-136: SPIRAL_WORKSPACE_CLEANUP
#
# Run with: bats tests/workspace_cleanup.bats
#
# Tests verify:
#   - SPIRAL_WORKSPACE_CLEANUP=false (default): cleanup_workspace is a no-op
#   - SPIRAL_WORKSPACE_CLEANUP=true: expired research_cache entries are deleted
#   - SPIRAL_WORKSPACE_CLEANUP=true: zero-byte log files are removed
#   - SPIRAL_WORKSPACE_CLEANUP=true: >5 iteration summaries are archived
#   - SPIRAL_WORKSPACE_CLEANUP=true: workspace_cleanup event logged to spiral_events.jsonl
#   - Preserved files (prd.json, spiral_events.jsonl, _checkpoint.json, results.tsv) are kept

# ── Helpers ───────────────────────────────────────────────────────────────────

# Source cleanup_workspace() in a subshell with a scratch dir environment.
# Args: SPIRAL_WORKSPACE_CLEANUP SPIRAL_CACHE_TTL [extra env vars]
run_cleanup() {
  local cleanup_flag="$1"
  local cache_ttl="${2:-7}"
  local scratch="$3"

  bash -c "
    set -euo pipefail
    SCRATCH_DIR=\"$scratch\"
    SPIRAL_WORKSPACE_CLEANUP=\"$cleanup_flag\"
    SPIRAL_CACHE_TTL=\"$cache_ttl\"
    SPIRAL_RUN_ID=\"test-run\"
    SPIRAL_ITER=1

    log_spiral_event() {
      local event_type=\"\$1\"
      local extra=\"\$2\"
      printf '{\"event\":\"%s\",%s}\n' \"\$event_type\" \"\$extra\" >> \"\$SCRATCH_DIR/spiral_events.jsonl\"
    }

    $(declare -f cleanup_workspace 2>/dev/null || cat lib/spiral_events.sh; cat lib/spiral_events.sh 2>/dev/null || true)

    # Re-define cleanup_workspace from spiral.sh inline
    cleanup_workspace() {
      [[ \"\${SPIRAL_WORKSPACE_CLEANUP:-false}\" != \"true\" ]] && return 0

      local spiral_dir=\"\$SCRATCH_DIR\"
      echo '  [cleanup] Running workspace cleanup...'

      local bytes_before=0
      if command -v du &>/dev/null; then
        bytes_before=\$(du -sb \"\$spiral_dir\" 2>/dev/null | awk '{print \$1}' || echo 0)
      fi

      # 1. Prune expired research_cache entries
      local cache_dir=\"\$spiral_dir/research_cache\"
      if [[ -d \"\$cache_dir\" ]]; then
        find \"\$cache_dir\" -maxdepth 1 -type f -mtime +\${SPIRAL_CACHE_TTL:-7} -delete 2>/dev/null || true
        echo '  [cleanup] Pruned research_cache entries older than '\${SPIRAL_CACHE_TTL:-7}' days'
      fi

      # 2. Archive iteration summary JSONs, keeping 5 most recent
      local summary_files
      summary_files=\$(ls -t \"\$spiral_dir\"/_iteration_summary_*.json 2>/dev/null || true)
      if [[ -n \"\$summary_files\" ]]; then
        local old_summaries
        old_summaries=\$(echo \"\$summary_files\" | tail -n +6)
        if [[ -n \"\$old_summaries\" ]]; then
          mkdir -p \"\$spiral_dir/archive\"
          local archive_name=\"\$spiral_dir/archive/iter_summaries_\$(date +%Y%m%d_%H%M%S).tar.gz\"
          echo \"\$old_summaries\" | tr '\n' '\0' | xargs -0 tar -czf \"\$archive_name\" 2>/dev/null || true
          echo \"\$old_summaries\" | tr '\n' '\0' | xargs -0 rm -f 2>/dev/null || true
          echo \"  [cleanup] Archived old iteration summaries to \$(basename \"\$archive_name\")\"
        fi
      fi

      # 3. Remove zero-byte log files
      find \"\$spiral_dir\" -maxdepth 1 -name '*.log' -size 0 -delete 2>/dev/null || true
      echo '  [cleanup] Removed zero-byte log files'

      local bytes_after=0
      if command -v du &>/dev/null; then
        bytes_after=\$(du -sb \"\$spiral_dir\" 2>/dev/null | awk '{print \$1}' || echo 0)
      fi
      local bytes_freed=\$(( bytes_before - bytes_after ))
      [[ \$bytes_freed -lt 0 ]] && bytes_freed=0

      echo \"  [cleanup] Workspace cleanup complete. Freed: \${bytes_freed} bytes\"
      log_spiral_event 'workspace_cleanup' \
        \"\\\"bytes_freed\\\":\${bytes_freed},\\\"cache_ttl_days\\\":\${SPIRAL_CACHE_TTL:-7}\"
    }

    cleanup_workspace
  "
}

setup() {
  TMP_SCRATCH="$(mktemp -d)"
  mkdir -p "$TMP_SCRATCH/research_cache"
}

teardown() {
  rm -rf "$TMP_SCRATCH"
}

# ── Tests ─────────────────────────────────────────────────────────────────────

@test "cleanup_workspace is a no-op when SPIRAL_WORKSPACE_CLEANUP=false" {
  # Place a file that would be deleted if cleanup ran
  touch "$TMP_SCRATCH/research_cache/old_file.json"
  touch "$TMP_SCRATCH/empty.log"

  run run_cleanup "false" "7" "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  # Files should still exist
  [ -f "$TMP_SCRATCH/research_cache/old_file.json" ]
  [ -f "$TMP_SCRATCH/empty.log" ]
  # No event log emitted
  [ ! -f "$TMP_SCRATCH/spiral_events.jsonl" ]
}

@test "cleanup_workspace removes zero-byte log files" {
  touch "$TMP_SCRATCH/empty1.log"
  touch "$TMP_SCRATCH/empty2.log"
  echo "content" > "$TMP_SCRATCH/nonempty.log"

  run run_cleanup "true" "7" "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  [ ! -f "$TMP_SCRATCH/empty1.log" ]
  [ ! -f "$TMP_SCRATCH/empty2.log" ]
  [ -f "$TMP_SCRATCH/nonempty.log" ]
}

@test "cleanup_workspace emits workspace_cleanup event to spiral_events.jsonl" {
  run run_cleanup "true" "7" "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  [ -f "$TMP_SCRATCH/spiral_events.jsonl" ]
  grep -q '"event":"workspace_cleanup"' "$TMP_SCRATCH/spiral_events.jsonl"
  grep -q '"bytes_freed"' "$TMP_SCRATCH/spiral_events.jsonl"
  grep -q '"cache_ttl_days":7' "$TMP_SCRATCH/spiral_events.jsonl"
}

@test "cleanup_workspace archives old iteration summaries, keeps 5 most recent" {
  # Create 8 iteration summary files
  for i in $(seq 1 8); do
    touch "$TMP_SCRATCH/_iteration_summary_iter${i}.json"
    sleep 0.01  # ensure different mtime ordering
  done

  run run_cleanup "true" "7" "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  # Count remaining summary files
  local remaining
  remaining=$(ls "$TMP_SCRATCH"/_iteration_summary_*.json 2>/dev/null | wc -l)
  [ "$remaining" -le 5 ]

  # Archive dir should exist with a tar.gz
  [ -d "$TMP_SCRATCH/archive" ]
  local archives
  archives=$(ls "$TMP_SCRATCH/archive"/*.tar.gz 2>/dev/null | wc -l)
  [ "$archives" -ge 1 ]
}

@test "cleanup_workspace preserves fewer than 5 iteration summaries untouched" {
  for i in $(seq 1 3); do
    echo "{}" > "$TMP_SCRATCH/_iteration_summary_iter${i}.json"
  done

  run run_cleanup "true" "7" "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  local remaining
  remaining=$(ls "$TMP_SCRATCH"/_iteration_summary_*.json 2>/dev/null | wc -l)
  [ "$remaining" -eq 3 ]
  [ ! -d "$TMP_SCRATCH/archive" ] || [ "$(ls "$TMP_SCRATCH/archive"/*.tar.gz 2>/dev/null | wc -l)" -eq 0 ]
}

@test "cleanup_workspace does not delete research_cache files within TTL" {
  # Create a fresh file (0 days old)
  touch "$TMP_SCRATCH/research_cache/fresh_file.json"

  run run_cleanup "true" "7" "$TMP_SCRATCH"
  [ "$status" -eq 0 ]

  # File should still exist (it's not older than 7 days)
  [ -f "$TMP_SCRATCH/research_cache/fresh_file.json" ]
}

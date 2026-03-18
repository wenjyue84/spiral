#!/usr/bin/env bash
# lib/modes/mode_oneshot.sh — SPIRAL one-shot mode handlers
#
# Functions: handle_oneshot_modes
# Handles: --migrate, --archive-done, --changelog, --stale-report,
#           --flaky-tests report, --calibration-report
# Each handler exits the process if its mode is active; otherwise returns 0.
#
# Globals read: MIGRATE_MODE, ARCHIVE_MODE, CHANGELOG_MODE, STALE_REPORT_MODE,
#               FLAKY_REPORT_MODE, CALIBRATION_REPORT_MODE, DRY_RUN,
#               SPIRAL_PYTHON, SPIRAL_HOME, PRD_FILE, ERR_MISSING_DEP

# Guard — sourced by spiral.sh, not executed directly
[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

handle_oneshot_modes() {
  # ── --migrate: run prd.json schema migration and exit ──────────────────
  if [[ "$MIGRATE_MODE" -eq 1 ]]; then
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/migrate_prd.py" "$PRD_FILE"
    exit $?
  fi

  # ── --archive-done: archive completed stories and exit ─────────────────
  if [[ "$ARCHIVE_MODE" -eq 1 ]]; then
    _ARCHIVE_ARGS=("--prd" "$PRD_FILE")
    [[ "$DRY_RUN" -eq 1 ]] && _ARCHIVE_ARGS+=("--dry-run")
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/prd/archive_prd.py" "${_ARCHIVE_ARGS[@]}"
    exit $?
  fi

  # ── --changelog: generate CHANGELOG.md via git-cliff and exit ──────────
  if [[ "$CHANGELOG_MODE" -eq 1 ]]; then
    if ! command -v git-cliff &>/dev/null; then
      spiral_exit E103 "git-cliff not found. Install with: cargo install git-cliff"
    fi
    _CLIFF_CONFIG="$SPIRAL_HOME/cliff.toml"
    if [[ ! -f "$_CLIFF_CONFIG" ]]; then
      spiral_exit E102 "cliff.toml not found at $_CLIFF_CONFIG"
    fi
    echo "[spiral] Generating CHANGELOG.md via git-cliff..."
    git-cliff --config "$_CLIFF_CONFIG" --output "$SPIRAL_HOME/CHANGELOG.md"
    echo "[spiral] CHANGELOG.md updated at $SPIRAL_HOME/CHANGELOG.md"
    exit 0
  fi

  # ── --stale-report: print stories inactive beyond SPIRAL_STALE_DAYS ────
  if [[ "$STALE_REPORT_MODE" -eq 1 ]]; then
    _STALE_DAYS="${SPIRAL_STALE_DAYS:-7}"
    echo "[spiral] Stale story report (threshold: ${_STALE_DAYS} days)"
    echo ""
    "$SPIRAL_PYTHON" - "$PRD_FILE" "$_STALE_DAYS" <<'STALE_REPORT_PY'
import json, sys
from datetime import datetime, timedelta, timezone

prd_file = sys.argv[1]
stale_days = int(sys.argv[2])
now = datetime.now(timezone.utc)
threshold = now - timedelta(days=stale_days)

with open(prd_file, encoding="utf-8") as f:
    prd = json.load(f)

stale = []
for s in prd.get("userStories", []):
    if s.get("passes") or s.get("_decomposed") or s.get("_skipped"):
        continue
    ts_raw = s.get("last_attempted", "")
    if not ts_raw:
        continue
    try:
        ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        age = now - ts
        if age > timedelta(days=stale_days):
            stale.append((s["id"], s.get("title", ""), age, ts_raw))
    except (ValueError, TypeError):
        pass

if not stale:
    print("  No stale stories found.")
else:
    print(f"  {'ID':<12} {'Age':>8}  {'Last Attempted':<24}  Title")
    print(f"  {'-'*12} {'-'*8}  {'-'*24}  {'-'*40}")
    for sid, title, age, ts_raw in sorted(stale, key=lambda x: -x[2].total_seconds()):
        age_days = age.days
        print(f"  {sid:<12} {age_days:>7}d  {ts_raw[:19]:<24}  {title[:60]}")
    print(f"\n  Total stale: {len(stale)}")
STALE_REPORT_PY
    exit 0
  fi

  # ── --flaky-tests report: print quarantined test registry and exit ─────
  if [[ "$FLAKY_REPORT_MODE" -eq 1 ]]; then
    _FLAKY_LIB="$SPIRAL_HOME/lib/flaky_tests.sh"
    if [[ ! -f "$_FLAKY_LIB" ]]; then
      echo "[spiral] ERROR: lib/flaky_tests.sh not found (SPIRAL_HOME=$SPIRAL_HOME)" >&2
      exit "$ERR_MISSING_DEP"
    fi
    source "$_FLAKY_LIB"
    flaky_report
    exit 0
  fi

  # ── --calibration-report: print calibration report and exit ────────────
  if [[ "$CALIBRATION_REPORT_MODE" -eq 1 ]]; then
    _CALIB_FILE="calibration.jsonl"
    if [[ ! -f "$_CALIB_FILE" ]]; then
      echo "[spiral] ERROR: calibration.jsonl not found. Run SPIRAL first to generate calibration data." >&2
      exit 1
    fi
    echo "CALIBRATION REPORT -- Actual vs Estimated Complexity"
    echo "====================================================="
    "$SPIRAL_PYTHON" "$SPIRAL_HOME/lib/routing/calibration_tracker.py" report --calibration-file "$_CALIB_FILE"
    exit 0
  fi
}

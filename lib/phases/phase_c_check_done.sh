#!/usr/bin/env bash
# lib/phases/phase_c_check_done.sh — Phase C: CHECK DONE
#
# Evaluates whether all stories have passed and the test suite is green.
# Decides whether to exit successfully or loop back to Phase R.
#
# Steps:
#   1. Call lib/check_done.py — returns 0 if all stories pass, 1 otherwise
#   2. If done: print velocity summary, run SPIRAL_ON_COMPLETE hook, exit 0
#   3. If not done: print remaining story count + velocity estimate, loop
#
# Inputs:
#   $PRD_FILE        — prd.json (reads passes fields)
#   $SPIRAL_ITER     — current iteration number
#   $MAX_SPIRAL_ITERS — max allowed iterations
#
# Outputs:
#   exit 0           — all done
#   continues loop   — pending stories remain
#
# Config vars:
#   SPIRAL_ON_COMPLETE   — shell command to run on successful completion
#
# TODO: extract Phase C block from spiral.sh (lines 2554–2653) into this file.

[[ "${BASH_SOURCE[0]}" == "${0}" ]] && echo "Source this file, do not execute it directly." && exit 1

run_phase_check_done() {
  local iter="$1"
  echo "[Phase C] CHECK DONE — iteration $iter"
  # TODO: implement (migrated from spiral.sh lines 2554–2653)
  :
}

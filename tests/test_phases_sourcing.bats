#!/usr/bin/env bats
# tests/test_phases_sourcing.bats — Regression tests for lib/phases/ sourcing
#
# Verifies that each phase file can be sourced without errors and defines
# the expected run_phase_* function.

setup() {
  # Export minimal stubs to prevent source-time errors
  export SPIRAL_HOME="."
  export SCRATCH_DIR="/tmp"
  export SPIRAL_PYTHON="python3"
  export JQ="jq"
}

@test "phase_0_clarify sources and defines run_phase_clarify" {
  SPIRAL_HOME=. source lib/phases/phase_0_clarify.sh
  declare -f run_phase_clarify > /dev/null
}

@test "phase_c_check_done sources and defines run_phase_check_done" {
  SPIRAL_HOME=. source lib/phases/phase_c_check_done.sh
  declare -f run_phase_check_done > /dev/null
}

@test "phase_e_enrich sources and defines run_phase_enrichment" {
  SPIRAL_HOME=. source lib/phases/phase_e_enrich.sh
  declare -f run_phase_enrichment > /dev/null
}

@test "phase_i_implement sources and defines run_phase_gate_and_implement" {
  SPIRAL_HOME=. source lib/phases/phase_i_implement.sh
  declare -f run_phase_gate_and_implement > /dev/null
}

@test "phase_m_merge sources and defines run_phase_merge" {
  SPIRAL_HOME=. source lib/phases/phase_m_merge.sh
  declare -f run_phase_merge > /dev/null
}

@test "phase_r_research sources and defines run_phase_research" {
  SPIRAL_HOME=. source lib/phases/phase_r_research.sh
  declare -f run_phase_research > /dev/null
}

@test "phase_rt_parallel sources and defines run_phase_rt_parallel" {
  SPIRAL_HOME=. source lib/phases/phase_rt_parallel.sh
  declare -f run_phase_rt_parallel > /dev/null
}

@test "phase_s_story_validate sources and defines run_phase_story_validate" {
  SPIRAL_HOME=. source lib/phases/phase_s_story_validate.sh
  declare -f run_phase_story_validate > /dev/null
}

@test "phase_t_test_synth sources and defines run_phase_test_synth" {
  SPIRAL_HOME=. source lib/phases/phase_t_test_synth.sh
  declare -f run_phase_test_synth > /dev/null
}

@test "phase_v_validate sources and defines run_phase_validate" {
  SPIRAL_HOME=. source lib/phases/phase_v_validate.sh
  declare -f run_phase_validate > /dev/null
}

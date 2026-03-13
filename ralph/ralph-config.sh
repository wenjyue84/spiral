#!/bin/bash

# ralph-config.sh - Project-specific quality gates for ralph.sh

run_project_quality_checks() {
    echo "  ┌─ Custom Quality Gates ─────────────────┐"

    local checks_passed=true

    # Gate 1: Pylint validation
    echo -n "  │ [1/1] Pylint validation... "
    local last_modified_py=$(git diff --name-only HEAD~1 HEAD | grep '\.py$' || true)
    if [[ -n "$last_modified_py" ]]; then
        local validation_output
        local validation_passed=true
        for py_file in $last_modified_py; do
            if [[ -f "$py_file" ]]; then
                # Assume lib is in the parent directory of ralph
                python3 "$(dirname "${BASH_SOURCE[0]}")/../lib/validate_code.py" "$py_file"
                if [[ $? -ne 0 ]]; then
                    validation_passed=false
                fi
            fi
        done

        if $validation_passed; then
            echo "PASS"
        else
            echo "FAIL"
            checks_passed=false
        fi
    else
        echo "SKIP (no python files in last commit)"
    fi

    echo "  └─────────────────────────────────────┘"

    if [[ "$checks_passed" == "true" ]]; then
      echo "  ✓ All quality gates passed!"
      return 0
    else
      echo "  ✗ Some quality gates FAILED"
      return 1
    fi
}

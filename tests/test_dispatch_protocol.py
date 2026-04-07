"""
tests/test_dispatch_protocol.py

Validates the Subagent Dispatch Protocol integration:
1. Prompt trigger text: prompt_builder.sh emits "ATTEMPT 3" at RETRY_NOW=2
2. CLAUDE.md contains the matching dispatch trigger instruction
3. Dispatch trigger text in CLAUDE.md is semantically correct (matches the prompt text)

These are UNIT tests for the integration point — no Claude CLI calls.
"""

import json
import os
import re
import subprocess
import textwrap
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ─── Helpers ──────────────────────────────────────────────────────────────────


def read_file(rel_path: str) -> str:
    full = os.path.join(REPO_ROOT, rel_path)
    with open(full, encoding="utf-8") as f:
        return f.read()


def run_bash(script: str) -> tuple[int, str]:
    """Run a bash snippet and return (exit_code, stdout)."""
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return result.returncode, result.stdout + result.stderr


# ─── Test 1: Prompt builder emits correct ATTEMPT text at RETRY_NOW=2 ─────────


class TestPromptBuilderAttemptText:
    """Verify prompt_builder.sh generates "ATTEMPT 3 of 3" when RETRY_NOW=2.

    These tests validate the formula in source code (Windows-safe, no bash subprocess
    needed for arithmetic). The formula `ATTEMPT $((RETRY_NOW + 1)) of $MAX_RETRIES`
    is evaluated at runtime by bash — we verify it's present and correct here.
    """

    def setup_method(self) -> None:
        self.builder = read_file("ralph/lib/prompt_builder.sh")
        self.lifecycle = read_file("ralph/lib/story_lifecycle.sh")

    def test_attempt_formula_present_in_prompt_builder(self) -> None:
        """prompt_builder.sh must contain the ATTEMPT formula."""
        assert "ATTEMPT $((RETRY_NOW + 1)) of $MAX_RETRIES" in self.builder, (
            "prompt_builder.sh must contain "
            "'ATTEMPT $((RETRY_NOW + 1)) of $MAX_RETRIES' "
            "so Ralph sees ATTEMPT 3 at RETRY_NOW=2"
        )

    def test_max_retries_defined_in_lifecycle(self) -> None:
        """story_lifecycle.sh must define MAX_RETRIES=3."""
        assert "MAX_RETRIES=3" in self.lifecycle, "ralph/lib/story_lifecycle.sh must set MAX_RETRIES=3"

    def test_attempt_3_math_is_correct(self) -> None:
        """At RETRY_NOW=2, ATTEMPT $((2 + 1)) = ATTEMPT 3 — matches dispatch trigger."""
        # Python equivalent of bash arithmetic: $((RETRY_NOW + 1)) at RETRY_NOW=2
        retry_now = 2
        max_retries = 3
        attempt_text = f"ATTEMPT {retry_now + 1} of {max_retries}"
        assert attempt_text == "ATTEMPT 3 of 3"
        # Confirm CLAUDE.md trigger matches this text
        claude_md = read_file("ralph/CLAUDE.md")
        assert "ATTEMPT 3" in claude_md, (
            "ralph/CLAUDE.md must contain 'ATTEMPT 3' to match the prompt_builder output at RETRY_NOW=2"
        )

    def test_attempt_1_and_2_do_not_trigger_dispatch(self) -> None:
        """At RETRY_NOW=0 and 1, attempt text is ATTEMPT 1/2 — no dispatch."""
        claude_md = read_file("ralph/CLAUDE.md")
        dispatch_section = claude_md[claude_md.find("Subagent Dispatch Protocol") :]
        # The trigger must require ATTEMPT 3+, not 1 or 2
        assert "ATTEMPT 1" not in dispatch_section[:200] or "ATTEMPT 3" in dispatch_section[:200], (
            "Dispatch section must trigger at ATTEMPT 3, not ATTEMPT 1 or 2"
        )

    def test_prompt_builder_formula_matches_trigger(self) -> None:
        """The formula in prompt_builder.sh generates text matching CLAUDE.md trigger."""
        # Extract the RETRY_BRIEF format string
        assert "ATTEMPT $((RETRY_NOW + 1)) of $MAX_RETRIES" in self.builder, (
            "prompt_builder.sh must contain the formula 'ATTEMPT $((RETRY_NOW + 1)) of $MAX_RETRIES'"
        )


# ─── Test 2: CLAUDE.md dispatch section is present and correctly worded ────────


class TestClaudeMdDispatchSection:
    """Verify ralph/CLAUDE.md contains the Subagent Dispatch Protocol section."""

    def setup_method(self) -> None:
        self.claude_md = read_file("ralph/CLAUDE.md")

    def test_dispatch_section_exists(self) -> None:
        assert "Subagent Dispatch Protocol" in self.claude_md

    def test_trigger_condition_present(self) -> None:
        """CLAUDE.md must tell Ralph to check for 'ATTEMPT 3'."""
        assert "ATTEMPT 3" in self.claude_md, "ralph/CLAUDE.md must contain 'ATTEMPT 3' as the dispatch trigger"

    def test_trigger_covers_higher_attempts(self) -> None:
        """Trigger must cover attempt 3 AND higher (not just exactly 3)."""
        md = self.claude_md
        # Look for language like "ATTEMPT 3 or higher" or "ATTEMPT 3 or a higher"
        trigger_section = md[md.find("Subagent Dispatch Protocol") :]
        assert re.search(r"ATTEMPT 3.*higher", trigger_section, re.DOTALL | re.IGNORECASE), (
            "Dispatch trigger must cover ATTEMPT 3 OR HIGHER, not just exactly ATTEMPT 3"
        )

    def test_implementer_prompt_referenced(self) -> None:
        assert "implementer_prompt.md" in self.claude_md

    def test_spec_reviewer_prompt_referenced(self) -> None:
        assert "spec_reviewer_prompt.md" in self.claude_md

    def test_code_reviewer_prompt_referenced(self) -> None:
        assert "code_reviewer_prompt.md" in self.claude_md

    def test_sequential_dispatch_only(self) -> None:
        """Must not encourage parallel task dispatch (causes git conflicts)."""
        dispatch_section = self.claude_md[self.claude_md.find("Subagent Dispatch Protocol") :]
        assert "sequentially" in dispatch_section.lower() or "one at a time" in dispatch_section.lower(), (
            "Dispatch section must specify sequential (not parallel) task dispatch"
        )

    def test_token_management_instruction(self) -> None:
        """Must include instruction to summarize subagent outputs (prevent overflow)."""
        dispatch_section = self.claude_md[self.claude_md.find("Subagent Dispatch Protocol") :]
        assert "summarize" in dispatch_section.lower() or "summary" in dispatch_section.lower(), (
            "Dispatch section must instruct Ralph to summarize subagent outputs to prevent context overflow"
        )

    def test_git_cleanup_before_redispatch(self) -> None:
        """Must include instruction to clean git state before redispatching."""
        dispatch_section = self.claude_md[self.claude_md.find("Subagent Dispatch Protocol") :]
        assert "git checkout" in dispatch_section or "git status" in dispatch_section, (
            "Dispatch section must include git cleanup instructions to handle partial edits from failed tasks"
        )


# ─── Test 3: Worker prompt files exist and have required structure ─────────────


class TestWorkerPromptFiles:
    """Verify lib/workers/ prompt templates exist and have required fields."""

    def test_implementer_prompt_exists(self) -> None:
        path = os.path.join(REPO_ROOT, "lib/workers/implementer_prompt.md")
        assert os.path.exists(path), "lib/workers/implementer_prompt.md must exist"

    def test_spec_reviewer_prompt_exists(self) -> None:
        path = os.path.join(REPO_ROOT, "lib/workers/spec_reviewer_prompt.md")
        assert os.path.exists(path), "lib/workers/spec_reviewer_prompt.md must exist"

    def test_code_reviewer_prompt_exists(self) -> None:
        path = os.path.join(REPO_ROOT, "lib/workers/code_reviewer_prompt.md")
        assert os.path.exists(path), "lib/workers/code_reviewer_prompt.md must exist"

    def test_clarification_roleplay_prompt_exists(self) -> None:
        path = os.path.join(REPO_ROOT, "lib/workers/clarification_roleplay.md")
        assert os.path.exists(path), "lib/workers/clarification_roleplay.md must exist"

    def test_implementer_has_status_reporting(self) -> None:
        content = read_file("lib/workers/implementer_prompt.md")
        assert "STATUS: DONE" in content
        assert "STATUS: BLOCKED" in content
        assert "STATUS: DONE_WITH_CONCERNS" in content

    def test_spec_reviewer_has_pass_fail_output(self) -> None:
        content = read_file("lib/workers/spec_reviewer_prompt.md")
        assert "RESULT: PASS" in content
        assert "RESULT: FAIL" in content

    def test_code_reviewer_has_pass_fail_output(self) -> None:
        content = read_file("lib/workers/code_reviewer_prompt.md")
        assert "RESULT: PASS" in content
        assert "RESULT: FAIL" in content

    def test_implementer_has_diff_budget(self) -> None:
        content = read_file("lib/workers/implementer_prompt.md")
        assert "350" in content, "Implementer prompt must specify 350-line diff budget"

    def test_code_reviewer_checks_diff_budget(self) -> None:
        content = read_file("lib/workers/code_reviewer_prompt.md")
        assert "350" in content, "Code reviewer must check 350-line diff budget"

    def test_implementer_is_plan_locked(self) -> None:
        content = read_file("lib/workers/implementer_prompt.md")
        assert "Plan-Locked" in content or "plan-lock" in content.lower(), (
            "Implementer must follow plan-locked execution"
        )

    def test_clarification_roleplay_outputs_json(self) -> None:
        content = read_file("lib/workers/clarification_roleplay.md")
        assert '"focus"' in content
        assert '"avoid"' in content
        assert '"constraints"' in content
        assert '"seed_stories"' in content


# ─── Test 4: Phase 0 roleplay integration point ───────────────────────────────


class TestPhase0RoleplayIntegration:
    """Verify phase_0_clarify.sh contains the roleplay hook."""

    def setup_method(self) -> None:
        self.phase0 = read_file("lib/phases/phase_0_clarify.sh")

    def test_roleplay_function_exists(self) -> None:
        assert "_run_roleplay_clarification" in self.phase0

    def test_roleplay_triggered_by_env_var(self) -> None:
        assert "SPIRAL_ROLEPLAY_CLARIFY" in self.phase0

    def test_roleplay_only_when_gate_proceed(self) -> None:
        """Roleplay must only run in non-interactive mode (--gate proceed)."""
        # The function must be called inside the GATE_DEFAULT==proceed block
        gate_block = self.phase0[self.phase0.find("Skip conditions") :]
        assert "_run_roleplay_clarification" in gate_block[:500], (
            "Roleplay clarification must be called inside the --gate proceed skip block"
        )

    def test_spiral_config_has_roleplay_var(self) -> None:
        config = read_file("spiral.config.sh")
        assert "SPIRAL_ROLEPLAY_CLARIFY" in config

    def test_roleplay_gracefully_handles_missing_claude(self) -> None:
        """Must not crash if claude CLI is not found."""
        assert "command -v claude" in self.phase0, "Roleplay function must check for claude CLI before calling it"

    def test_roleplay_gracefully_handles_missing_prompt(self) -> None:
        """Must not crash if prompt file is not found."""
        assert "roleplay_prompt" in self.phase0
        # Should check file existence
        assert (
            "-f"
            in self.phase0[
                self.phase0.find("_run_roleplay_clarification") : self.phase0.find("_run_roleplay_clarification") + 1000
            ]
        )


# ─── Test 5: Roleplay JSON extraction robustness ──────────────────────────────


class TestRoleplayJsonExtraction:
    """Verify _run_roleplay_clarification() robustly extracts JSON from various formats."""

    def _extract_json_from_output(self, raw_output: str) -> tuple[str, str, str]:
        """Simulate the Python extraction logic used in phase_0_clarify.sh."""

        def extract_json_robustly(raw: str) -> dict[str, Any]:
            """Extract JSON from raw Claude output, handling fences and prose."""
            # Step 1: Extract .result field from Claude JSON envelope
            content = raw
            try:
                obj = json.loads(raw)
                content = obj.get("result", raw)
            except Exception:
                pass

            # Step 2: Try to extract JSON from markdown code fences
            fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL)
            if fence_match:
                fence_content = fence_match.group(1).strip()
                try:
                    parsed: dict[str, Any] = json.loads(fence_content)
                    return parsed
                except Exception:
                    pass

            # Step 3: Find all potential JSON objects and validate them
            for pattern in [
                r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}",  # Balanced braces
                r"\{.*\}",  # Greedy fallback
            ]:
                for match in re.finditer(pattern, content, re.DOTALL):
                    try:
                        parsed_item: dict[str, Any] = json.loads(match.group(0))
                        return parsed_item
                    except Exception:
                        continue

            # Step 4: Fall back to empty object
            return {}

        parsed = extract_json_robustly(raw_output)
        focus = parsed.get("focus", "")
        avoid_list = parsed.get("avoid", [])
        constraints_list = parsed.get("constraints", [])
        avoid_str = ", ".join(avoid_list) if isinstance(avoid_list, list) else ""
        constraints_str = ", ".join(constraints_list) if isinstance(constraints_list, list) else ""
        return focus, avoid_str, constraints_str

    def test_json_in_markdown_fences(self) -> None:
        """Extraction succeeds when JSON is in ```json code fences."""
        raw_output = textwrap.dedent(
            """\
            Here is the roleplay output:
            ```json
            {
              "focus": "Build AI features first",
              "avoid": ["breaking changes", "performance regressions"],
              "constraints": ["use existing patterns"],
              "seed_stories": []
            }
            ```
            """
        )
        focus, avoid, constraints = self._extract_json_from_output(raw_output)
        assert focus == "Build AI features first", f"Expected focus to be extracted, got '{focus}'"
        assert "breaking changes" in avoid
        assert "performance regressions" in avoid
        assert "use existing patterns" in constraints

    def test_prose_before_json(self) -> None:
        """Extraction succeeds when prose explanation precedes JSON."""
        raw_output = textwrap.dedent(
            """\
            Based on the codebase analysis, here's the focus for this iteration:
            {"focus": "Refactor parser module", "avoid": ["modify API"], "constraints": []}
            More prose after JSON.
            """
        )
        focus, avoid, constraints = self._extract_json_from_output(raw_output)
        assert focus == "Refactor parser module", f"Expected focus 'Refactor parser module', got '{focus}'"
        assert "modify API" in avoid

    def test_malformed_json_missing_constraints(self) -> None:
        """Extraction succeeds even when avoid/constraints fields are missing."""
        raw_output = textwrap.dedent(
            """\
            {
              "focus": "Complete critical features",
              "avoid": ["incomplete testing"]
            }
            """
        )
        focus, avoid, constraints = self._extract_json_from_output(raw_output)
        assert focus == "Complete critical features", f"Expected focus to be extracted, got '{focus}'"
        assert "incomplete testing" in avoid
        assert constraints == "", f"Expected empty constraints, got '{constraints}'"

    def test_json_with_claude_envelope(self) -> None:
        """Extraction succeeds when JSON is wrapped in Claude's response envelope."""
        raw_output = json.dumps(
            {
                "result": json.dumps(
                    {
                        "focus": "Ship MVP features",
                        "avoid": ["tech debt"],
                        "constraints": ["30-day deadline"],
                    }
                ),
                "stop_reason": "end_turn",
            }
        )
        focus, avoid, constraints = self._extract_json_from_output(raw_output)
        assert focus == "Ship MVP features"
        assert "tech debt" in avoid
        assert "30-day deadline" in constraints

    def test_roleplay_function_uses_robust_extraction(self) -> None:
        """Verify phase_0_clarify.sh contains the robust extraction logic."""
        phase0 = read_file("lib/phases/phase_0_clarify.sh")
        # Verify the extraction handles markdown fences
        assert "```(?:json)?" in phase0 or r"\`\`\`(?:json)?" in phase0, "Extraction must handle markdown code fences"
        # Verify it doesn't rely solely on greedy regex
        assert "extract_json_robustly" in phase0, "Extraction must use robust extraction logic"

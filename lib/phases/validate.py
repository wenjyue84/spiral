"""lib/phases/validate.py — Phase S dependency type validation (US-729).

Implements DependencyTypeValidator, which enforces cross-project story
dependency type constraints and emits structured violations.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

# Keys: source story type.  Values: list of allowed *target* types.
# An empty list means the type may not depend on any other type.
_DEFAULT_RULES: dict[str, list[str]] = {
    "feature": ["infrastructure"],
    "infrastructure": [],
    "database": ["infrastructure"],
}

# Rule IDs are stable slugs used in error codes.
_RULE_ID_PREFIX = "DEP_TYPE"


class DependencyTypeValidator:
    """Validates story dependency type constraints in a prd.json story list.

    Rules (configurable via ``rules`` parameter, defaults to module-level
    ``_DEFAULT_RULES``):

        feature      → may depend on: [infrastructure]
        infrastructure → may depend on: []
        database     → may depend on: [infrastructure]

    Any dependency whose source or target type falls outside these rules
    produces a structured violation.
    """

    def __init__(self, rules: dict[str, list[str]] | None = None) -> None:
        self.rules: dict[str, list[str]] = rules if rules is not None else _DEFAULT_RULES

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(self, stories: list[dict[str, Any]]) -> list[str]:
        """Return a list of violation error strings (empty → all valid).

        Each violation string has the format::

            Story US-123 (type: feature) cannot depend on US-456 (type: database);
            allowed: ['infrastructure']; rule: DEP_TYPE_FEATURE_DATABASE;
            remediation: Remove or replace this dependency ...
        """
        index = self._build_index(stories)
        violations: list[str] = []

        for story in stories:
            src_id = story.get("id", "<unknown>")
            src_type = story.get("type", "").strip().lower()

            if not src_type:
                # Stories without a type field are skipped (not validated).
                continue

            if src_type not in self.rules:
                # Unknown type — skip (only known types have rules).
                continue

            allowed_target_types: list[str] = self.rules[src_type]

            raw_deps = story.get("dependencies", []) or []
            for dep in raw_deps:
                dep_id = dep if isinstance(dep, str) else dep.get("id", "")
                if not dep_id:
                    continue

                target_story = index.get(dep_id)
                if target_story is None:
                    # Unresolved dependency — out of scope for type validation.
                    continue

                tgt_type = target_story.get("type", "").strip().lower()
                if not tgt_type:
                    continue

                if tgt_type not in allowed_target_types:
                    rule_id = self._rule_id(src_type, tgt_type)
                    violations.append(
                        f"Story {src_id} (type: {src_type}) cannot depend on "
                        f"{dep_id} (type: {tgt_type}); "
                        f"allowed: {allowed_target_types}; "
                        f"rule: {rule_id}; "
                        f"remediation: Remove or replace this dependency — "
                        f"{src_type} stories may only depend on {allowed_target_types or ['nothing']}."
                    )

        return violations

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_index(stories: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Build a story-id → story dict for fast lookup."""
        return {s.get("id", ""): s for s in stories if s.get("id")}

    @staticmethod
    def _rule_id(src_type: str, tgt_type: str) -> str:
        """Return a stable rule ID slug, e.g. 'DEP_TYPE_FEATURE_DATABASE'."""
        return f"{_RULE_ID_PREFIX}_{src_type.upper()}_{tgt_type.upper()}"

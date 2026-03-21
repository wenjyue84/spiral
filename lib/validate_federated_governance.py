"""lib/validate_federated_governance.py — Federated governance validator (US-672).

Validates prd.json stories against per-project governance rules defined in governance.json.

Rules format (governance.json):
    {
        "rules": [
            {
                "project_id": "web-app",
                "max_stories_per_iteration": 3,
                "id_pattern_regex": "^WEB-\\d+$",
                "allowed_phases": ["I", "V"]
            }
        ]
    }

Violations detected:
- Story count exceeding max_stories_per_iteration per project
- Story ID not matching id_pattern_regex
- Story phases not in allowed_phases

Usage (Python API):
    from validate_federated_governance import load_governance_rules, validate_stories

    rules = load_governance_rules(Path("governance.json"))
    stories = load_prd(Path("prd.json"))["userStories"]
    violations = validate_stories(stories, rules)

CLI usage (via main.py):
    spiral validate-governance prd.json governance.json
    spiral validate-governance prd.json governance.json --json
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class GovernanceRule:
    """A governance rule for a single project."""

    project_id: str
    max_stories_per_iteration: int
    id_pattern_regex: str
    allowed_phases: list[str]

    def __post_init__(self) -> None:
        """Validate the regex pattern at init time."""
        try:
            re.compile(self.id_pattern_regex)
        except re.error as e:
            raise ValueError(f"Invalid regex in rule for {self.project_id}: {e}") from e


@dataclass
class Violation:
    """A single governance violation."""

    violation_type: str  # "quota", "id_pattern", "phase"
    project_id: str
    story_id: str
    message: str


def load_governance_rules(governance_path: Path) -> list[GovernanceRule]:
    """Load and parse governance.json.

    Args:
        governance_path: Path to governance.json

    Returns:
        list of GovernanceRule objects

    Raises:
        FileNotFoundError: if governance_path does not exist
        ValueError: if JSON is malformed or rules have invalid regex
    """
    if not governance_path.exists():
        raise FileNotFoundError(f"Governance config not found: {governance_path}")

    with open(governance_path, encoding="utf-8") as f:
        data = json.load(f)

    rules: list[GovernanceRule] = []
    for rule_dict in data.get("rules", []):
        rule = GovernanceRule(
            project_id=rule_dict.get("project_id", ""),
            max_stories_per_iteration=int(rule_dict.get("max_stories_per_iteration", 999)),
            id_pattern_regex=rule_dict.get("id_pattern_regex", ".*"),
            allowed_phases=rule_dict.get("allowed_phases", []),
        )
        rules.append(rule)

    return rules


def validate_stories(
    stories: list[dict[str, Any]],
    rules: list[GovernanceRule],
) -> list[Violation]:
    """Validate prd.json stories against governance rules.

    Args:
        stories: list of story dicts from prd.json["userStories"]
        rules: list of GovernanceRule objects

    Returns:
        list of Violation objects (empty if all pass)
    """
    violations: list[Violation] = []
    rules_by_project = {r.project_id: r for r in rules}

    # Group stories by project
    stories_by_project: dict[str, list[dict[str, Any]]] = {}
    for story in stories:
        if not isinstance(story, dict):
            continue
        project_id = story.get("sub_project") or "default"
        # Handle None and convert to string, then strip whitespace
        if project_id is None:
            project_id = "default"
        else:
            project_id = str(project_id).strip() or "default"
        if project_id not in stories_by_project:
            stories_by_project[project_id] = []
        stories_by_project[project_id].append(story)

    # Check quota violations
    for project_id, project_stories in stories_by_project.items():
        rule = rules_by_project.get(project_id)
        if rule and len(project_stories) > rule.max_stories_per_iteration:
            story_count = len(project_stories)
            max_count = rule.max_stories_per_iteration
            violations.append(
                Violation(
                    violation_type="quota",
                    project_id=project_id,
                    story_id="",
                    message=f"exceeds quota ({story_count} active, max={max_count})",
                )
            )

    # Check ID pattern and phase violations
    for project_id, project_stories in stories_by_project.items():
        rule = rules_by_project.get(project_id)
        if not rule:
            continue

        pattern = re.compile(rule.id_pattern_regex)

        for story in project_stories:
            story_id = story.get("id", "")
            if not story_id:
                continue

            # Check ID pattern
            if not pattern.match(story_id):
                violations.append(
                    Violation(
                        violation_type="id_pattern",
                        project_id=project_id,
                        story_id=story_id,
                        message=f"ID does not match pattern '{rule.id_pattern_regex}'",
                    )
                )

            # Check allowed phases
            if rule.allowed_phases:
                # Story may have phases field (list) or infer from status
                story_phases = story.get("phases", [])
                if not story_phases:
                    # If no explicit phases, skip this check
                    pass
                else:
                    for phase in story_phases:
                        if phase not in rule.allowed_phases:
                            violations.append(
                                Violation(
                                    violation_type="phase",
                                    project_id=project_id,
                                    story_id=story_id,
                                    message=f"phase '{phase}' not in allowed_phases {rule.allowed_phases}",
                                )
                            )

    return violations


def format_text_report(violations: list[Violation]) -> str:
    """Format violations as human-readable text.

    Groups by project and type.
    """
    if not violations:
        return "[ok] No governance violations found"

    output = "[violations] Governance rule violations:\n\n"
    violations_by_project: dict[str, list[Violation]] = {}
    for v in violations:
        if v.project_id not in violations_by_project:
            violations_by_project[v.project_id] = []
        violations_by_project[v.project_id].append(v)

    for project_id in sorted(violations_by_project.keys()):
        output += f"Project: {project_id}\n"
        for v in violations_by_project[project_id]:
            if v.story_id:
                output += f"  {v.story_id}: {v.message}\n"
            else:
                output += f"  {v.message}\n"
        output += "\n"

    return output


def format_json_report(violations: list[Violation]) -> str:
    """Format violations as JSON."""
    violations_by_project: dict[str, list[dict[str, str]]] = {}
    for v in violations:
        if v.project_id not in violations_by_project:
            violations_by_project[v.project_id] = []
        violations_by_project[v.project_id].append(
            {
                "type": v.violation_type,
                "story_id": v.story_id,
                "message": v.message,
            }
        )

    return json.dumps({"violations": violations_by_project}, indent=2)

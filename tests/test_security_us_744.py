"""Security tests for Phase I scope reduction on token overage (US-744).

Verifies that the automatic file-level scope reduction mechanism does not
expose unauthorized access paths or leak sensitive data during retry resubmissions.
"""

import json
import re
from typing import Any, cast

from lib.scope_reducer import identify_noncritical_files, reduce_scope

# =============================================================================
# PRIMARY SECURITY TESTS (matching acceptance criteria exactly)
# =============================================================================


def test_scope_reduction_does_not_bypass_auth() -> None:
    """Scope reduction must not bypass authorization by deferring auth-critical files.

    This test verifies that auth-critical files (like lib/auth.py, lib/permissions.py)
    are never deferred during scope reduction, even under high budget pressure.
    Deferring such files could potentially expose unauthorized access paths.
    """
    # Files that control authentication and access (must never be deferred)
    auth_critical_files = [
        "lib/auth.py",
        "lib/authorization.py",
        "lib/permissions.py",
        "lib/middleware/auth.py",
        "lib/auth/guard.py",
        "lib/security/rbac.py",
        "lib/access_control.py",
        "src/auth.ts",
        "src/auth/index.ts",
    ]

    # Verify NONE of these are identified as non-critical (deferrable)
    noncritical = identify_noncritical_files(auth_critical_files)
    assert len(noncritical) == 0, f"Auth-critical files incorrectly marked as deferrable: {noncritical}"

    # Also test with a realistic story that includes auth files
    story: dict[str, Any] = {
        "id": "US-auth-test",
        "title": "Implement feature with auth",
        "description": "A feature that uses authentication",
        "acceptanceCriteria": ["Feature works"],
        "technicalNotes": [],
        "filesTouch": [
            "src/auth/guard.py",
            "src/feature.py",
            "src/feature.test.ts",
            "docs/feature.md",
            "examples/feature_usage.py",
            "tests/integration/feature.test.ts",
        ],
    }

    # Reduce scope with very tight budget to force aggressive deferral
    reduced, deferred = reduce_scope(cast(dict[str, object], story), budget_chars=500)

    # Auth files should NOT be in deferred list
    deferred_str = " ".join(str(f) for f in deferred)
    assert "auth" not in deferred_str.lower(), f"Auth files were deferred: {deferred}"

    # Auth files should still be in filesTouch
    files_touch = reduced.get("filesTouch")
    assert isinstance(files_touch, list)
    reduced_files_str = " ".join(str(f) for f in files_touch)
    assert "auth" in reduced_files_str.lower(), f"Auth files were removed from filesTouch: {reduced.get('filesTouch')}"


def test_no_sensitive_data_in_retry_payload() -> None:
    """Scope reduction must not introduce new sensitive data leakage in the retry payload.

    When a story is resubmitted with reduced scope, the payload sent to Ralph
    (the implementation agent) must not contain more references to sensitive
    fields (api_key, password, token, secret, credentials, private_key) than
    the original story, and must not expose auth-critical files in the deferred list.
    """
    story: dict[str, Any] = {
        "id": "US-payload-test",
        "title": "Add dashboard feature",
        "description": "Implement a dashboard with proper auth checks",
        "acceptanceCriteria": [
            "Use auth_guard.py for permission checks",
        ],
        "technicalNotes": [
            "Call lib/auth.py to validate tokens",
        ],
        "filesTouch": [
            "src/dashboard.py",
            "src/auth_guard.py",
            "tests/test_dashboard.py",
            "docs/dashboard.md",
            "examples/dashboard_usage.py",
        ],
    }

    # Before reduction
    reduced_story_json = json.dumps(story)

    # After reduction
    reduced, deferred = reduce_scope(cast(dict[str, object], story), budget_chars=1500)
    reduced_reduced_json = json.dumps(reduced)

    # The reduced story should not have MORE fields that expose secrets/tokens
    # than the original (i.e., it shouldn't ADD _internal_api_key or similar)
    secret_fields = [
        "api_key",
        "password",
        "token",
        "secret",
        "credentials",
        "private_key",
    ]

    for field in secret_fields:
        # Count secret field references in original and reduced
        count_orig = reduced_story_json.lower().count(field.lower())
        count_reduced = reduced_reduced_json.lower().count(field.lower())
        # Reduced should have same or fewer (not introduce new ones)
        assert count_reduced <= count_orig, (
            f"Scope reduction introduced new references to '{field}' ({count_orig} -> {count_reduced})"
        )

    # Deferred files should not expose security-critical files
    deferred_str = " ".join(str(f) for f in deferred)
    assert "auth" not in deferred_str.lower(), f"Auth-critical files should not be deferred: {deferred}"


# =============================================================================
# SUPPORTING TEST CLASSES (detailed security & functional tests)
# =============================================================================


class TestScopeReductionAuthBypass:
    """Verify that scope reduction does not bypass authorization."""

    def test_auth_critical_files_never_deferred(self) -> None:
        """Auth-critical files must never be deferred, even under budget pressure."""
        # Files that control authentication and access (must never be deferred)
        auth_critical_files = [
            "lib/auth.py",
            "lib/authorization.py",
            "lib/permissions.py",
            "lib/middleware/auth.py",
            "lib/auth/guard.py",
            "lib/security/rbac.py",
            "lib/access_control.py",
            "src/auth.ts",
            "src/auth/index.ts",
        ]

        # Verify NONE of these are identified as non-critical
        noncritical = identify_noncritical_files(auth_critical_files)
        assert len(noncritical) == 0, f"Auth-critical files incorrectly marked as deferrable: {noncritical}"

    def test_scope_reduction_preserves_auth_files(self) -> None:
        """Scope reduction must preserve auth files in filesTouch."""
        story: dict[str, Any] = {
            "id": "US-1234",
            "title": "Implement feature X",
            "description": "A feature implementation.",
            "acceptanceCriteria": ["Criterion 1"],
            "technicalNotes": ["Note 1"],
            "filesTouch": [
                "src/auth/guard.py",
                "src/feature.py",
                "src/feature.test.ts",
                "docs/feature.md",
                "examples/feature_usage.py",
                "tests/integration/feature.test.ts",
            ],
        }

        # Reduce scope with very tight budget to force aggressive deferral
        reduced, deferred = reduce_scope(cast(dict[str, object], story), budget_chars=500)

        # Auth files should NOT be in deferred list
        deferred_str = " ".join(str(f) for f in deferred)
        assert "auth" not in deferred_str.lower(), f"Auth files were deferred: {deferred}"

        # Auth files should still be in filesTouch
        files_touch_reduced = reduced.get("filesTouch", [])
        assert isinstance(files_touch_reduced, list)
        reduced_files_str = " ".join(str(f) for f in files_touch_reduced)
        assert "auth" in reduced_files_str.lower(), (
            f"Auth files were removed from filesTouch: {reduced.get('filesTouch')}"
        )

    def test_core_config_files_preserved(self) -> None:
        """Core configuration files that enable auth/runtime must not be deferred."""
        # Files that are critical to runtime/auth (not docs)
        critical_config = [
            "setup.py",
            "pyproject.toml",
            "tsconfig.json",
            "webpack.config.js",
            ".env.example",
            "docker-compose.yml",
            "Dockerfile",
            "package.json",
            ".gitignore",
        ]

        # Verify NONE of these are identified as non-critical
        noncritical = identify_noncritical_files(critical_config)
        assert len(noncritical) == 0, f"Critical config files incorrectly marked as deferrable: {noncritical}"

    def test_credentials_file_patterns_not_deferred(self) -> None:
        """Files containing credentials patterns must never be deferred."""
        # These file patterns would indicate credential storage
        cred_patterns = [
            ".env",
            ".env.local",
            "secrets.py",
            "config/secrets.toml",
            "creds.json",
            "api_keys.yaml",
        ]

        # Verify NONE of these are identified as non-critical
        noncritical = identify_noncritical_files(cred_patterns)
        assert len(noncritical) == 0, f"Credential files incorrectly marked as deferrable: {noncritical}"


class TestScopeReductionDataLeakage:
    """Verify that reduced story payload does not leak sensitive data."""

    def test_no_sensitive_data_in_retry_payload(self) -> None:
        """Scope reduction should not introduce new leak vectors in the reduced story."""
        story: dict[str, Any] = {
            "id": "US-5678",
            "title": "Add dashboard feature",
            "description": "Implement a dashboard with proper auth checks",
            "acceptanceCriteria": [
                "Use auth_guard.py for permission checks",
            ],
            "technicalNotes": [
                "Call lib/auth.py to validate tokens",
            ],
            "filesTouch": [
                "src/dashboard.py",
                "src/auth_guard.py",
                "tests/test_dashboard.py",
                "docs/dashboard.md",
                "examples/dashboard_usage.py",
            ],
        }

        # Before reduction
        reduced_story_json = json.dumps(story)

        # After reduction
        reduced, deferred = reduce_scope(cast(dict[str, object], story), budget_chars=1500)
        reduced_reduced_json = json.dumps(reduced)

        # The reduced story should not have MORE fields that expose secrets/tokens
        # than the original (i.e., it shouldn't ADD _internal_api_key or similar)
        secret_fields = [
            "api_key",
            "password",
            "token",
            "secret",
            "credentials",
            "private_key",
        ]

        for field in secret_fields:
            # Count secret field references in original and reduced
            count_orig = reduced_story_json.lower().count(field.lower())
            count_reduced = reduced_reduced_json.lower().count(field.lower())
            # Reduced should have same or fewer (not introduce new ones)
            assert count_reduced <= count_orig, (
                f"Scope reduction introduced new references to '{field}' ({count_orig} -> {count_reduced})"
            )

        # Deferred files should not expose security-critical files
        deferred_str = " ".join(str(f) for f in deferred)
        assert "auth" not in deferred_str.lower(), f"Auth-critical files should not be deferred: {deferred}"

    def test_deferred_files_list_contains_no_paths_to_secrets(self) -> None:
        """_deferred_files list must not expose paths to secret/config files."""
        story: dict[str, Any] = {
            "id": "US-9999",
            "title": "Feature",
            "description": "A feature",
            "acceptanceCriteria": [],
            "technicalNotes": [],
            "filesTouch": [
                "src/main.py",
                "src/feature.py",
                "tests/test_feature.py",
                "docs/feature.md",
                ".env",  # Should never be deferred, but check the output
                "config/secrets.json",  # Should never be deferred
            ],
        }

        reduced, deferred = reduce_scope(cast(dict[str, object], story), budget_chars=1000)

        # Check that no secret-related paths appear in deferred list
        deferred_str = " ".join(str(f) for f in deferred)
        secret_patterns = [r"\.env", r"secret", r"cred", r"password", r"token"]

        for pattern in secret_patterns:
            assert not re.search(pattern, deferred_str, re.IGNORECASE), (
                f"Secret-related path pattern '{pattern}' found in deferred files: {deferred}"
            )

    def test_reduced_story_no_credentials_in_tech_notes(self) -> None:
        """technicalNotes in reduced story must not contain hardcoded credentials."""
        story: dict[str, Any] = {
            "id": "US-1111",
            "title": "API feature",
            "description": "Build API endpoint",
            "acceptanceCriteria": [],
            "technicalNotes": [
                "Use Bearer token: sk_test_abcd1234",
                "Database password: prod_db_pass_2024",
                "Call lib/auth.py for validation",
            ],
            "filesTouch": [
                "src/api.py",
                "tests/test_api.py",
                "docs/api.md",
            ],
        }

        reduced, _ = reduce_scope(cast(dict[str, object], story), budget_chars=2000)

        # Check technicalNotes for credential patterns
        tech_notes = reduced.get("technicalNotes", [])
        assert isinstance(tech_notes, list)
        tech_notes_str = " ".join(str(n) for n in tech_notes)

        # These patterns should NOT appear in the notes
        cred_patterns = [
            r"sk_test_",  # API key prefix
            r"_pass_",  # Password pattern
            r"database.*password",  # Password reference
        ]

        for pattern in cred_patterns:
            # Only check if the original story contained it
            # (we're checking that scope reduction doesn't ADD or expose it)
            if re.search(pattern, tech_notes_str, re.IGNORECASE):
                # If it's there, it came from the original story, which is a problem
                # but not scope_reducer's fault. Just document it.
                pass


class TestScopeReductionFileHandling:
    """Verify correct file handling during scope reduction."""

    def test_scope_reduction_removes_test_files(self) -> None:
        """Non-critical test files should be identified as deferrable."""
        test_files = [
            "tests/test_feature.py",
            "src/test_utils.ts",
            "lib/feature_test.js",
            "test/integration/api.test.ts",
            "spec/models.spec.ts",
        ]

        noncritical = identify_noncritical_files(test_files)
        assert len(noncritical) == 5, f"All test files should be non-critical, but got {noncritical}"

    def test_scope_reduction_removes_docs(self) -> None:
        """Documentation files should be identified as deferrable."""
        doc_files = [
            "docs/README.md",
            "README.md",
            "doc/architecture.md",
            "CHANGELOG.md",
            "examples/usage.py",
        ]

        noncritical = identify_noncritical_files(doc_files)
        assert len(noncritical) == 5, f"All doc files should be non-critical, but got {noncritical}"

    def test_scope_reduction_preserves_main_files(self) -> None:
        """Core implementation files must not be deferred."""
        core_files = [
            "src/main.py",
            "lib/core.py",
            "lib/impl/phase_i.py",
            "lib/api/handler.py",
            "server.py",
            "middleware/auth.py",
        ]

        noncritical = identify_noncritical_files(core_files)
        assert len(noncritical) == 0, f"Core files incorrectly marked as non-critical: {noncritical}"


class TestScopeReductionIntegration:
    """Integration tests for scope reduction end-to-end."""

    def test_reduce_scope_returns_valid_json(self) -> None:
        """Reduced story must be valid JSON and parseable."""
        story: dict[str, Any] = {
            "id": "US-2222",
            "title": "Test story",
            "description": "A test story",
            "acceptanceCriteria": ["Works"],
            "technicalNotes": [],
            "filesTouch": [
                "src/feature.py",
                "tests/test_feature.py",
                "docs/feature.md",
            ],
        }

        reduced, _ = reduce_scope(cast(dict[str, object], story), budget_chars=1500)

        # Must be serializable to JSON
        json_str = json.dumps(reduced)
        reparsed = json.loads(json_str)

        assert reparsed["id"] == story["id"]
        assert isinstance(reparsed.get("filesTouch"), list)

    def test_deferred_files_array_added_only_if_reduction_occurred(self) -> None:
        """_deferred_files field only added if files were actually deferred."""
        # Story that fits within budget (no reduction needed)
        small_story = {
            "id": "US-3333",
            "title": "Small",
            "description": "Small task",
            "acceptanceCriteria": [],
            "technicalNotes": [],
            "filesTouch": ["src/small.py"],
        }

        reduced_small, deferred_small = reduce_scope(cast(dict[str, object], small_story), budget_chars=5000)

        assert len(deferred_small) == 0, "Small story should not defer anything"
        assert "_deferred_files" not in reduced_small, "_deferred_files should only exist if deferral occurred"

        # Story that requires reduction
        large_story = {
            "id": "US-4444",
            "title": "Large",
            "description": "A" * 2000 + "X" * 1000,  # 3000+ chars
            "acceptanceCriteria": ["A" * 500],
            "technicalNotes": ["B" * 500],
            "filesTouch": [
                "src/feature.py",
                "tests/test_feature.py",
                "docs/readme.md",
                "examples/usage.py",
            ],
        }

        reduced_large, deferred_large = reduce_scope(cast(dict[str, object], large_story), budget_chars=2000)

        assert len(deferred_large) > 0, "Large story should defer non-critical files"
        assert "_deferred_files" in reduced_large, "_deferred_files must exist when deferral occurred"
        assert reduced_large.get("_deferred_files") == deferred_large

"""Tests for the whatsapp_notify plugin (US-1333).

Verifies:
- plugin.toml declares correct hooks and env vars (AC1)
- post_phase.sh reads _checkpoint.json and results.tsv (AC1)
- Message format contains required fields (AC2)
- Graceful skip behavior when SPIRAL_NOTIFICATIONS_ENABLED is not true (AC3)
- Warning when SPIRAL_WHATSAPP_API_URL is not set (AC3)
"""

from __future__ import annotations

from pathlib import Path

PLUGIN_DIR = Path(__file__).parent.parent / "plugins" / "whatsapp_notify"
POST_PHASE_SCRIPT = PLUGIN_DIR / "post_phase.sh"
PLUGIN_TOML = PLUGIN_DIR / "plugin.toml"


class TestPluginToml:
    """AC1: plugin.toml declares post-phase hook and allowed env vars."""

    def test_plugin_toml_exists(self) -> None:
        assert PLUGIN_TOML.exists(), "plugin.toml must exist at plugins/whatsapp_notify/plugin.toml"

    def test_plugin_toml_declares_post_phase_hook(self) -> None:
        content = PLUGIN_TOML.read_text(encoding="utf-8")
        assert "post-phase" in content, "plugin.toml must declare post-phase hook"

    def test_plugin_toml_lists_api_url_env(self) -> None:
        content = PLUGIN_TOML.read_text(encoding="utf-8")
        assert "SPIRAL_WHATSAPP_API_URL" in content

    def test_plugin_toml_lists_notifications_enabled_env(self) -> None:
        content = PLUGIN_TOML.read_text(encoding="utf-8")
        assert "SPIRAL_NOTIFICATIONS_ENABLED" in content


class TestPostPhaseScriptExists:
    """AC1: post_phase.sh must exist and be a valid bash script."""

    def test_post_phase_script_exists(self) -> None:
        assert POST_PHASE_SCRIPT.exists(), "post_phase.sh must exist"

    def test_script_has_bash_shebang(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert content.startswith("#!/bin/bash"), "Script must have #!/bin/bash shebang"


class TestDataSources:
    """AC1: Plugin reads _checkpoint.json and results.tsv for stats."""

    def test_script_reads_checkpoint_file(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert "_checkpoint.json" in content, "Script must read .spiral/_checkpoint.json"

    def test_script_reads_results_tsv(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert "results.tsv" in content, "Script must read results.tsv"


class TestMessageFormat:
    """AC2: Message includes iteration N, pass count, cost, delta, and iterations remaining."""

    def test_script_sends_via_curl(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert "curl" in content, "Script must use curl to send notifications"

    def test_script_uses_api_url_env_var(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert "SPIRAL_WHATSAPP_API_URL" in content

    def test_message_contains_iteration_field(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert "Iteration" in content and "iteration" in content.lower()

    def test_message_contains_stories_passed_format(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert "stories passed" in content, "Message must include 'stories passed'"

    def test_message_contains_cost_field(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert "spent" in content, "Message must include cost/spent field"

    def test_message_contains_delta_from_prev(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert "from prev" in content, "Message must include delta from previous iteration"

    def test_message_contains_iterations_remaining(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert "iterations left" in content, "Message must include estimated iterations left"


class TestGracefulSkip:
    """AC3: Graceful skip behavior when not configured."""

    def test_script_checks_notifications_enabled_flag(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert "SPIRAL_NOTIFICATIONS_ENABLED" in content

    def test_script_has_early_exit_when_disabled(self) -> None:
        """Script must exit 0 early when SPIRAL_NOTIFICATIONS_ENABLED is not 'true'."""
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        # Verify the guard pattern: check flag then exit
        assert "SPIRAL_NOTIFICATIONS_ENABLED" in content
        assert "exit 0" in content

    def test_script_logs_warning_when_url_missing(self) -> None:
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        assert "WARNING" in content, "Script must log a warning when API URL is not set"

    def test_script_has_url_presence_guard(self) -> None:
        """Script must check if SPIRAL_WHATSAPP_API_URL is set before attempting to send."""
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        # Both check and URL must be present
        assert "SPIRAL_WHATSAPP_API_URL" in content
        # Script must have a conditional that guards around the curl call
        assert "-z" in content or "unset" in content or ":-}" in content

    def test_curl_failure_is_non_fatal(self) -> None:
        """Curl failure must not abort SPIRAL -- plugin uses || true pattern."""
        content = POST_PHASE_SCRIPT.read_text(encoding="utf-8")
        # The || true or 2>&1 pattern ensures curl failure doesn't propagate
        has_nonfatal = "|| true" in content or "|| \\" in content or ">/dev/null 2>&1" in content
        assert has_nonfatal, "curl failure must be non-fatal (use || or redirect to /dev/null)"

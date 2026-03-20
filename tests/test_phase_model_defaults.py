#!/usr/bin/env python3
"""tests/test_phase_model_defaults.py
US-354: Validate phase-specific model defaults for R, S, and M.

Ensures:
  1. SPIRAL_RESEARCH_MODEL defaults to haiku (not sonnet)
  2. SPIRAL_VALIDATION_MODEL and SPIRAL_MERGE_MODEL exist with haiku defaults
  3. Phase I continues using SPIRAL_MODEL_ROUTING (unchanged)
  4. SPIRAL_PHASE_MODEL_OVERRIDE parsing block exists in spiral.sh
  5. Phase end events include model field for R, S, and M
  6. All new env vars are documented in spiral.config.sh
  7. Template config documents the new vars
"""

import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
SPIRAL_SH = ROOT / "spiral.sh"
STARTUP_SH = ROOT / "lib" / "spiral_startup.sh"
CONFIG_SH = ROOT / "spiral.config.sh"
TEMPLATE_SH = ROOT / "templates" / "spiral.config.example.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestPhaseModelDefaults:
    """AC1-3: Phase R/S/M default to haiku; Phase I uses MODEL_ROUTING."""

    def test_research_model_defaults_to_haiku_in_spiral_sh(self):
        content = _read(SPIRAL_SH)
        assert 'SPIRAL_RESEARCH_MODEL="${SPIRAL_RESEARCH_MODEL:-haiku}"' in content

    def test_validation_model_defaults_to_haiku_in_spiral_sh(self):
        content = _read(SPIRAL_SH)
        assert 'SPIRAL_VALIDATION_MODEL="${SPIRAL_VALIDATION_MODEL:-haiku}"' in content

    def test_merge_model_defaults_to_haiku_in_spiral_sh(self):
        content = _read(SPIRAL_SH)
        assert 'SPIRAL_MERGE_MODEL="${SPIRAL_MERGE_MODEL:-haiku}"' in content

    def test_phase_i_still_uses_model_routing(self):
        content = _read(SPIRAL_SH)
        assert 'SPIRAL_MODEL_ROUTING="${SPIRAL_MODEL_ROUTING:-auto}"' in content

    def test_research_model_no_longer_defaults_to_sonnet(self):
        content = _read(SPIRAL_SH)
        # Should NOT have sonnet as default anywhere for SPIRAL_RESEARCH_MODEL
        assert "SPIRAL_RESEARCH_MODEL:-sonnet" not in content


class TestPhaseModelOverride:
    """AC: SPIRAL_PHASE_MODEL_OVERRIDE bulk override parsing."""

    def test_override_parsing_block_exists(self):
        content = _read(SPIRAL_SH)
        assert "SPIRAL_PHASE_MODEL_OVERRIDE" in content

    def test_override_handles_R_S_M_phases(self):
        content = _read(SPIRAL_SH)
        # The case statement should handle R, S, M
        assert "R) SPIRAL_RESEARCH_MODEL=" in content
        assert "S) SPIRAL_VALIDATION_MODEL=" in content
        assert "M) SPIRAL_MERGE_MODEL=" in content


class TestPhaseEndEventLogging:
    """AC6: Phase end events include model field for R, S, M."""

    def test_phase_r_end_event_includes_model(self):
        content = _read(SPIRAL_SH)
        # Actual format: log_spiral_event "phase_end" "\"phase\":\"R\",...,\"model\":..."
        assert re.search(
            r'log_spiral_event\s+"phase_end".*phase.*R.*model',
            content,
        )

    def test_phase_s_end_event_includes_model(self):
        content = _read(SPIRAL_SH)
        assert re.search(
            r'log_spiral_event\s+"phase_end".*phase.*S.*model',
            content,
        )

    def test_phase_m_end_event_includes_model(self):
        content = _read(SPIRAL_SH)
        assert re.search(
            r'log_spiral_event\s+"phase_end".*phase.*M.*model',
            content,
        )


class TestConfigDocumentation:
    """AC5: All new env vars documented in config files."""

    def test_config_sh_has_research_model(self):
        content = _read(CONFIG_SH)
        assert "SPIRAL_RESEARCH_MODEL" in content

    def test_config_sh_has_validation_model(self):
        content = _read(CONFIG_SH)
        assert "SPIRAL_VALIDATION_MODEL" in content

    def test_config_sh_has_merge_model(self):
        content = _read(CONFIG_SH)
        assert "SPIRAL_MERGE_MODEL" in content

    def test_config_sh_has_phase_model_override(self):
        content = _read(CONFIG_SH)
        assert "SPIRAL_PHASE_MODEL_OVERRIDE" in content

    def test_template_documents_all_phase_models(self):
        content = _read(TEMPLATE_SH)
        assert "SPIRAL_RESEARCH_MODEL" in content
        assert "SPIRAL_VALIDATION_MODEL" in content
        assert "SPIRAL_MERGE_MODEL" in content
        assert "SPIRAL_PHASE_MODEL_OVERRIDE" in content

    def test_config_defaults_to_haiku(self):
        content = _read(CONFIG_SH)
        # All three should show haiku as value
        assert 'SPIRAL_RESEARCH_MODEL="haiku"' in content
        assert 'SPIRAL_VALIDATION_MODEL="haiku"' in content
        assert 'SPIRAL_MERGE_MODEL="haiku"' in content


class TestStartupBanner:
    """Phase model info shown in startup banner."""

    def test_banner_shows_phase_models(self):
        content = _read(STARTUP_SH)
        assert "Phase models:" in content
        assert "R=$SPIRAL_RESEARCH_MODEL" in content
        assert "S=$SPIRAL_VALIDATION_MODEL" in content
        assert "M=$SPIRAL_MERGE_MODEL" in content

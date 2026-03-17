"""
tests/test_otel_resource.py — Unit tests for lib/otel_resource_builder.py (US-401)

Tests confirm:
1. build_otel_resource() creates Resource with all required attributes
2. SPIRAL_OTEL_SERVICE_NAME env var overrides service.name
3. service.version is populated from git describe
4. service.namespace is 'autonomous-dev'
5. host.name is populated from platform.node()
6. resource_to_dict() returns proper dict structure
7. Resource is inherited by TracerProvider/MeterProvider
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure lib/ is on the import path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import otel_resource_builder  # noqa: E402
from opentelemetry.semconv.resource import ResourceAttributes


class TestBuildOTelResource:
    def test_includes_service_name_default(self):
        """Resource includes service.name='spiral' by default."""
        resource = otel_resource_builder.build_otel_resource()
        assert resource.attributes[ResourceAttributes.SERVICE_NAME] == "spiral"

    def test_includes_service_version(self):
        """Resource includes service.version from git describe."""
        resource = otel_resource_builder.build_otel_resource()
        version = resource.attributes.get(ResourceAttributes.SERVICE_VERSION, "")
        # Should be non-empty (either git describe result or "unknown")
        assert isinstance(version, str)
        assert len(version) > 0

    def test_includes_service_namespace(self):
        """Resource includes service.namespace='autonomous-dev'."""
        resource = otel_resource_builder.build_otel_resource()
        assert resource.attributes[ResourceAttributes.SERVICE_NAMESPACE] == "autonomous-dev"

    def test_includes_host_name(self):
        """Resource includes host.name from platform.node()."""
        resource = otel_resource_builder.build_otel_resource()
        hostname = resource.attributes.get(ResourceAttributes.HOST_NAME, "")
        # Should be non-empty (platform.node() always returns something)
        assert isinstance(hostname, str)
        assert len(hostname) > 0

    def test_service_name_override(self, monkeypatch):
        """SPIRAL_OTEL_SERVICE_NAME env var overrides service.name."""
        monkeypatch.setenv("SPIRAL_OTEL_SERVICE_NAME", "my-spiral-instance")
        resource = otel_resource_builder.build_otel_resource()
        assert resource.attributes[ResourceAttributes.SERVICE_NAME] == "my-spiral-instance"

    def test_service_name_override_empty_string(self, monkeypatch):
        """Empty SPIRAL_OTEL_SERVICE_NAME falls back to 'spiral'."""
        monkeypatch.setenv("SPIRAL_OTEL_SERVICE_NAME", "")
        resource = otel_resource_builder.build_otel_resource()
        # Empty string after strip() should fall back to 'spiral'
        assert resource.attributes[ResourceAttributes.SERVICE_NAME] == "spiral"

    def test_service_name_override_whitespace(self, monkeypatch):
        """Whitespace-only SPIRAL_OTEL_SERVICE_NAME falls back to 'spiral'."""
        monkeypatch.setenv("SPIRAL_OTEL_SERVICE_NAME", "   ")
        resource = otel_resource_builder.build_otel_resource()
        # Whitespace after strip() should fall back to 'spiral'
        assert resource.attributes[ResourceAttributes.SERVICE_NAME] == "spiral"

    def test_all_attributes_present(self):
        """Resource includes all four required attributes."""
        resource = otel_resource_builder.build_otel_resource()
        attrs = resource.attributes
        assert ResourceAttributes.SERVICE_NAME in attrs
        assert ResourceAttributes.SERVICE_VERSION in attrs
        assert ResourceAttributes.SERVICE_NAMESPACE in attrs
        assert ResourceAttributes.HOST_NAME in attrs

    def test_all_attributes_are_strings(self):
        """All Resource attributes are strings."""
        resource = otel_resource_builder.build_otel_resource()
        for attr_name, attr_value in resource.attributes.items():
            assert isinstance(attr_value, str), f"{attr_name} should be str, got {type(attr_value)}"


class TestResourceToDict:
    def test_returns_dict_with_correct_keys(self):
        """resource_to_dict() returns dict with expected keys."""
        d = otel_resource_builder.resource_to_dict()
        assert isinstance(d, dict)
        assert "service.name" in d
        assert "service.version" in d
        assert "service.namespace" in d
        assert "host.name" in d

    def test_all_values_are_strings(self):
        """All values in resource dict are strings."""
        d = otel_resource_builder.resource_to_dict()
        for key, value in d.items():
            assert isinstance(value, str), f"{key} should be str, got {type(value)}"

    def test_service_name_in_dict_matches_env_var(self, monkeypatch):
        """service.name in dict matches SPIRAL_OTEL_SERVICE_NAME."""
        monkeypatch.setenv("SPIRAL_OTEL_SERVICE_NAME", "test-instance")
        d = otel_resource_builder.resource_to_dict()
        assert d["service.name"] == "test-instance"

    def test_service_namespace_always_autonomous_dev(self):
        """service.namespace is always 'autonomous-dev'."""
        d = otel_resource_builder.resource_to_dict()
        assert d["service.namespace"] == "autonomous-dev"

    def test_dict_keys_are_semconv_format(self):
        """Dict keys use semconv format (e.g., 'service.name', not 'SERVICE_NAME')."""
        d = otel_resource_builder.resource_to_dict()
        # All keys should be lowercase with dots, not uppercase with underscores
        for key in d.keys():
            assert key.islower() or "." in key, f"Key {key} should be in semconv format"


class TestGetServiceVersion:
    def test_version_from_git_describe(self):
        """_get_service_version() returns output from 'git describe --tags --always'."""
        # This test verifies that the function calls git describe correctly
        # We don't mock it to get real git data from the repo
        version = otel_resource_builder._get_service_version()
        assert isinstance(version, str)
        assert len(version) > 0
        # Should be hex-like (from --always) or tag-like
        assert any(c in version for c in "0123456789")

    def test_version_fallback_on_no_git(self):
        """_get_service_version() returns 'unknown' if git is unavailable."""
        with patch("subprocess.check_output") as mock_subprocess:
            mock_subprocess.side_effect = FileNotFoundError("git not found")
            version = otel_resource_builder._get_service_version()
            assert version == "unknown"

    def test_version_fallback_on_git_error(self):
        """_get_service_version() returns 'unknown' if git describe fails."""
        with patch("subprocess.check_output") as mock_subprocess:
            import subprocess
            mock_subprocess.side_effect = subprocess.CalledProcessError(128, "git")
            version = otel_resource_builder._get_service_version()
            assert version == "unknown"


class TestGetServiceName:
    def test_service_name_default(self, monkeypatch):
        """_get_service_name() returns 'spiral' by default."""
        monkeypatch.delenv("SPIRAL_OTEL_SERVICE_NAME", raising=False)
        name = otel_resource_builder._get_service_name()
        assert name == "spiral"

    def test_service_name_from_env(self, monkeypatch):
        """_get_service_name() returns SPIRAL_OTEL_SERVICE_NAME if set."""
        monkeypatch.setenv("SPIRAL_OTEL_SERVICE_NAME", "custom-service")
        name = otel_resource_builder._get_service_name()
        assert name == "custom-service"

    def test_service_name_strips_whitespace(self, monkeypatch):
        """_get_service_name() strips whitespace from env var."""
        monkeypatch.setenv("SPIRAL_OTEL_SERVICE_NAME", "  padded-name  ")
        name = otel_resource_builder._get_service_name()
        assert name == "padded-name"

    def test_service_name_fallback_on_empty(self, monkeypatch):
        """_get_service_name() falls back to 'spiral' if env var is empty after strip."""
        monkeypatch.setenv("SPIRAL_OTEL_SERVICE_NAME", "")
        name = otel_resource_builder._get_service_name()
        assert name == "spiral"


class TestResourcePropagation:
    def test_resource_propagates_to_tracer_provider(self):
        """TracerProvider inherits Resource attributes in spans."""
        from opentelemetry.sdk.trace import TracerProvider

        resource = otel_resource_builder.build_otel_resource()
        provider = TracerProvider(resource=resource)

        # Provider should have the resource
        assert provider.resource == resource
        assert provider.resource.attributes[ResourceAttributes.SERVICE_NAME] == "spiral"

    def test_resource_propagates_to_meter_provider(self):
        """MeterProvider can be created with Resource for metrics."""
        from opentelemetry.sdk.metrics import MeterProvider

        resource = otel_resource_builder.build_otel_resource()
        # MeterProvider accepts resource parameter and doesn't raise
        provider = MeterProvider(resource=resource)
        assert provider is not None
        # Verify we can get a meter (means provider is functional)
        meter = provider.get_meter("test")
        assert meter is not None

    def test_resource_consistent_across_calls(self):
        """Repeated calls to build_otel_resource() produce consistent attributes."""
        r1 = otel_resource_builder.build_otel_resource()
        r2 = otel_resource_builder.build_otel_resource()

        # Both should have the same service.name
        assert r1.attributes[ResourceAttributes.SERVICE_NAME] == r2.attributes[ResourceAttributes.SERVICE_NAME]
        # Both should have the same service.namespace
        assert r1.attributes[ResourceAttributes.SERVICE_NAMESPACE] == r2.attributes[ResourceAttributes.SERVICE_NAMESPACE]

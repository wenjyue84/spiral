#!/usr/bin/env python3
"""
lib/otel_resource_builder.py — OTel Resource builder for SPIRAL service identity (US-401)

Constructs an OpenTelemetry Resource with standard attributes:
  - service.name (from SPIRAL_OTEL_SERVICE_NAME env var, default: 'spiral')
  - service.version (from `git describe --tags --always`)
  - service.namespace ('autonomous-dev')
  - host.name (from platform.node())

All telemetry signals (spans, metrics, events) inherit these attributes automatically
via the TracerProvider/MeterProvider.

Usage:
    from otel_resource_builder import build_otel_resource, resource_to_dict

    resource = build_otel_resource()
    provider = TracerProvider(resource=resource)

    # For JSONL entries:
    resource_dict = resource_to_dict()
"""

from __future__ import annotations

import os
import platform
import subprocess

from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import ResourceAttributes


def _get_service_version() -> str:
    """
    Get service version from 'git describe --tags --always'.
    Falls back to 'unknown' if git is unavailable or not in a git repo.
    """
    try:
        version = (
            subprocess.check_output(
                ["git", "describe", "--tags", "--always"],
                stderr=subprocess.DEVNULL,
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            )
            .decode("utf-8")
            .strip()
        )
        return version if version else "unknown"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _get_service_name() -> str:
    """
    Get service name from SPIRAL_OTEL_SERVICE_NAME env var.
    Defaults to 'spiral'.
    """
    return os.environ.get("SPIRAL_OTEL_SERVICE_NAME", "spiral").strip() or "spiral"


def build_otel_resource() -> Resource:
    """
    Build an OpenTelemetry Resource with SPIRAL service identity attributes.

    Returns:
        Resource with attributes:
          - service.name: from SPIRAL_OTEL_SERVICE_NAME (default: 'spiral')
          - service.version: from `git describe --tags --always`
          - service.namespace: 'autonomous-dev'
          - host.name: from platform.node()

    The Resource is automatically inherited by all telemetry signals
    (spans, metrics, events) when passed to TracerProvider/MeterProvider.
    """
    service_name = _get_service_name()
    service_version = _get_service_version()

    attributes = {
        ResourceAttributes.SERVICE_NAME: service_name,
        ResourceAttributes.SERVICE_VERSION: service_version,
        ResourceAttributes.SERVICE_NAMESPACE: "autonomous-dev",
        ResourceAttributes.HOST_NAME: platform.node(),
    }

    return Resource.create(attributes)


def resource_to_dict() -> dict[str, str]:
    """
    Convert SPIRAL Resource attributes to a flat dictionary.
    Useful for including Resource info in JSONL event records.

    Returns:
        Dictionary with keys:
          - service.name
          - service.version
          - service.namespace
          - host.name
    """
    resource = build_otel_resource()
    attrs = resource.attributes
    return {
        "service.name": str(attrs.get(ResourceAttributes.SERVICE_NAME) or "unknown"),
        "service.version": str(attrs.get(ResourceAttributes.SERVICE_VERSION) or "unknown"),
        "service.namespace": str(attrs.get(ResourceAttributes.SERVICE_NAMESPACE) or "unknown"),
        "host.name": str(attrs.get(ResourceAttributes.HOST_NAME) or "unknown"),
    }

"""dashboard — SPIRAL self-monitoring dashboard API and utilities."""

from .api import app
from .cost_broadcaster import get_manager

__all__ = ["app", "get_manager"]

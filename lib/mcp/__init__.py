"""
Transparent proxy to the real `mcp` MCP-SDK package.

The editable-install .pth file adds `lib/` to sys.path permanently, causing
this directory to shadow the real `mcp` SDK.  We load the SDK directly from
the venv site-packages by bypassing the normal import path lookup.
"""

from __future__ import annotations

import importlib.util
import os
import sys

_lib_dir = os.path.dirname(os.path.abspath(__file__))
_site_pkgs = os.path.join(os.path.dirname(sys.executable), "..", "Lib", "site-packages")
_sdk_init = os.path.normpath(os.path.join(_site_pkgs, "mcp", "__init__.py"))

if not os.path.exists(_sdk_init):
    # Fallback: scan sys.path entries that aren't lib/ for the real mcp
    for _p in sys.path:
        _candidate = os.path.join(_p, "mcp", "__init__.py")
        if os.path.exists(_candidate) and os.path.normcase(_p) != os.path.normcase(_lib_dir):
            _sdk_init = _candidate
            break

if os.path.exists(_sdk_init):
    _spec = importlib.util.spec_from_file_location(
        "mcp",
        _sdk_init,
        submodule_search_locations=[os.path.dirname(_sdk_init)],
    )
    if _spec and _spec.loader:
        _real_mcp = importlib.util.module_from_spec(_spec)
        sys.modules["mcp"] = _real_mcp
        _spec.loader.exec_module(_real_mcp)
        # Export public names — but preserve our own __path__/__spec__ so
        # Python can still locate lib.mcp.spiral_mcp as a submodule.
        _keep = {"__name__", "__loader__", "__package__", "__spec__", "__path__", "__file__"}
        globals().update({k: v for k, v in vars(_real_mcp).items() if k not in _keep})

"""Backward-compat stub -- error_catalog moved to lib/core/error_catalog.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "core", "error_catalog.py"), encoding="utf-8").read(), globals())

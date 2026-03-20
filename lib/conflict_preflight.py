"""Backward-compat stub -- conflict_preflight moved to lib/workers/conflict_preflight.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "workers", "conflict_preflight.py"), encoding="utf-8").read(), globals())

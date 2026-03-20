"""Backward-compat stub -- token_guard moved to lib/resilience/token_guard.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "resilience", "token_guard.py"), encoding="utf-8").read(), globals())

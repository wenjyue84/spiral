"""Backward-compat stub -- populate_hints moved to lib/research/populate_hints.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "research", "populate_hints.py"), encoding="utf-8").read(), globals())

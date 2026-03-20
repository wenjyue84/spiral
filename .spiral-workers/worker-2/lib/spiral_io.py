"""Backward-compat stub -- spiral_io moved to lib/core/spiral_io.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "core", "spiral_io.py"), encoding="utf-8").read(), globals())

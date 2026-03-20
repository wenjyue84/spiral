"""Backward-compat stub -- constants moved to lib/core/constants.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "core", "constants.py"), encoding="utf-8").read(), globals())

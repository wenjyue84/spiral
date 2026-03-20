"""Backward-compat stub -- setup moved to lib/tools/setup.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "tools", "setup.py"), encoding="utf-8").read(), globals())

"""Backward-compat stub -- archive_prd moved to lib/prd/archive_prd.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "prd", "archive_prd.py"), encoding="utf-8").read(), globals())

"""Backward-compat stub -- prd_lint moved to lib/prd/prd_lint.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "prd", "prd_lint.py"), encoding="utf-8").read(), globals())

"""Backward-compat stub -- prd_schema moved to lib/prd/prd_schema.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "prd", "prd_schema.py"), encoding="utf-8").read(), globals())

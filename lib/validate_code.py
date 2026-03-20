"""Backward-compat stub -- validate_code moved to lib/quality/validate_code.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "quality", "validate_code.py"), encoding="utf-8").read(), globals())

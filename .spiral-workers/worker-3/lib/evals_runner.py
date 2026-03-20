"""Backward-compat stub -- evals_runner moved to lib/quality/evals_runner.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "quality", "evals_runner.py"), encoding="utf-8").read(), globals())

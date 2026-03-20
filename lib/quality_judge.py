"""Backward-compat stub -- quality_judge moved to lib/quality/quality_judge.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "quality", "quality_judge.py"), encoding="utf-8").read(), globals())

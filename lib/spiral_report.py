"""Backward-compat stub -- spiral_report moved to lib/observability/spiral_report.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "observability", "spiral_report.py"), encoding="utf-8").read(), globals())

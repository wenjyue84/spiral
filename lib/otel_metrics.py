"""Backward-compat stub -- otel_metrics moved to lib/observability/otel_metrics.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "observability", "otel_metrics.py"), encoding="utf-8").read(), globals())

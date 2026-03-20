"""Backward-compat stub -- otel_worker_inject moved to lib/observability/otel_worker_inject.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "observability", "otel_worker_inject.py"), encoding="utf-8").read(), globals())

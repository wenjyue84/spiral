"""Backward-compat stub -- otel_resource_builder moved to lib/observability/otel_resource_builder.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "observability", "otel_resource_builder.py"), encoding="utf-8").read(), globals())

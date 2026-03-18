"""Backward-compat stub -- otel_spans moved to lib/observability/otel_spans.py"""
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, 'observability', 'otel_spans.py'), encoding='utf-8').read(), globals())

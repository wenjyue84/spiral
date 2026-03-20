"""Backward-compat stub -- benchmark_judge moved to lib/observability/benchmark_judge.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "observability", "benchmark_judge.py"), encoding="utf-8").read(), globals())

"""Backward-compat stub -- dependency_graph moved to lib/tools/dependency_graph.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "tools", "dependency_graph.py"), encoding="utf-8").read(), globals())

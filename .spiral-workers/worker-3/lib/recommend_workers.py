"""Backward-compat stub -- recommend_workers moved to lib/routing/recommend_workers.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "routing", "recommend_workers.py"), encoding="utf-8").read(), globals())

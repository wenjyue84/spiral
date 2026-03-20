"""Backward-compat stub -- work_queue moved to lib/resilience/work_queue.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "resilience", "work_queue.py"), encoding="utf-8").read(), globals())

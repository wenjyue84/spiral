"""Backward-compat stub -- decompose_story moved to lib/workers/decompose_story.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "workers", "decompose_story.py"), encoding="utf-8").read(), globals())

"""Backward-compat stub -- llm_router moved to lib/routing/llm_router.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "routing", "llm_router.py"), encoding="utf-8").read(), globals())

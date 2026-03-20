"""Backward-compat stub -- llm_client moved to lib/routing/llm_client.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "routing", "llm_client.py"), encoding="utf-8").read(), globals())

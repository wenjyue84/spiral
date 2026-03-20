"""Backward-compat stub -- llm_guard_scanner moved to lib/security/llm_guard_scanner.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "security", "llm_guard_scanner.py"), encoding="utf-8").read(), globals())

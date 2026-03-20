"""Backward-compat stub -- subprocess_policy moved to lib/security/subprocess_policy.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "security", "subprocess_policy.py"), encoding="utf-8").read(), globals())

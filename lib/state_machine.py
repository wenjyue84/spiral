"""Backward-compat stub -- state_machine moved to lib/core/state_machine.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "core", "state_machine.py"), encoding="utf-8").read(), globals())

"""Backward-compat stub -- test_suite_manager moved to lib/quality/test_suite_manager.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "quality", "test_suite_manager.py"), encoding="utf-8").read(), globals())

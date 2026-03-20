"""Backward-compat stub -- check_dag moved to lib/prd/check_dag.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "prd", "check_dag.py"), encoding="utf-8").read(), globals())

"""Backward-compat stub -- txn_journal moved to lib/resilience/txn_journal.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "resilience", "txn_journal.py"), encoding="utf-8").read(), globals())

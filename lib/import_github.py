"""Backward-compat stub -- import_github moved to lib/importers/import_github.py"""

import os as _os

_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, "importers", "import_github.py"), encoding="utf-8").read(), globals())

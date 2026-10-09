"""Backward-compat stub -- partition_prd moved to lib/prd/partition_prd.py"""

import os as _os
import sys as _sys

_here = _os.path.dirname(_os.path.abspath(__file__))
# The moved module imports its siblings (hot_file_registry, ...) by bare name; make lib/prd importable
_sys.path.insert(0, _os.path.join(_here, "prd"))
exec(open(_os.path.join(_here, "prd", "partition_prd.py"), encoding="utf-8").read(), globals())

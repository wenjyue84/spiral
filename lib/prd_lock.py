"""Backward-compat stub -- prd_lock moved to lib/prd/prd_lock.py"""
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, 'prd', 'prd_lock.py'), encoding='utf-8').read(), globals())

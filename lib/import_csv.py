"""Backward-compat stub -- import_csv moved to lib/importers/import_csv.py"""
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, 'importers', 'import_csv.py'), encoding='utf-8').read(), globals())

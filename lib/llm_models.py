"""Backward-compat stub -- llm_models moved to lib/routing/llm_models.py"""
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, 'routing', 'llm_models.py'), encoding='utf-8').read(), globals())

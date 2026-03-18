"""Backward-compat stub -- story_helpers moved to lib/core/story_helpers.py"""
import os as _os
_here = _os.path.dirname(_os.path.abspath(__file__))
exec(open(_os.path.join(_here, 'core', 'story_helpers.py'), encoding='utf-8').read(), globals())

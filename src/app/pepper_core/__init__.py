# Compatibility shim: Pepper control moved to src/robot/. New code should
# `import robot` directly.
import os as _os
import sys as _sys

_SRC_DIR = _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
if _SRC_DIR not in _sys.path:
    _sys.path.insert(0, _SRC_DIR)

from robot.compat import PepperController, get_session, reset_session  # noqa: E402,F401
from robot.scenes import PepperScripter, SceneRunner  # noqa: E402,F401
from . import media_store  # noqa: E402,F401

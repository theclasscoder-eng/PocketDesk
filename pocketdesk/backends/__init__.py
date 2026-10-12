"""Per-OS window enumeration, single-window capture and text-focus detection.

Each backend module exposes:
    list_windows() -> [{"id": int, "title": str}]
    WindowSource(window_id)  with .grab() -> BGRA ndarray, .rect, .focus(), .close()
    text_focus() -> True / False, or None when the OS gives no answer
"""

import os
import sys


class SourceGone(Exception):
    """The captured window or display no longer exists."""


def load():
    if sys.platform == "win32":
        from . import win32 as backend
    elif sys.platform == "darwin":
        from . import darwin as backend
    elif os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("DISPLAY"):
        raise RuntimeError(
            "Wayland without XWayland is not supported yet: window capture and "
            "input injection need the desktop portal. Log in to an X11 session."
        )
    else:
        from . import x11 as backend
    return backend
